"""Blackboard controller: the orchestration loop.

The controller owns the *state-driven* investigation workflow:

1. read the current blackboard (``blackboard.state.assess``);
2. ask every eligible agent for its candidate actions, score them, and select
   the single highest-value action;
3. execute the responsible agent with failure isolation and bounded retries;
4. record an execution-ledger entry (status, duration, input/output record ids,
   failure reason, attempt, sequence, and the state the choice was based on);
5. repeat until a stopping condition is met.

Guarantees:

* **No infinite loops.** Three independent guards: an iteration limit (steps),
   a global execution limit (counts retries), and per-action de-duplication that
   ignores an action once it has run ``max_attempts_per_action`` times without a
   blackboard change.
* **No silent data loss.** A failed agent attempt is rolled back, so partial
   writes are discarded while everything committed by earlier agents remains.
   Failures are recorded and retried, then the agent is parked and the loop
   continues with the others.
* **Re-runnable.** When an agent succeeds *and changes the blackboard*, the
   revision advances and previously parked agents become eligible again - so new
   evidence re-opens the relevant reasoning.
* **Cancellable.** Cooperative cancellation is checked before every step,
   before every retry, and exposed to agents via ``ctx.cancelled()``.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..agents import AgentContext, default_agents
from ..agents.base_agent import BaseAgent
from ..config import settings
from ..models import AgentActivity, Investigation, enums
from ..services import reevaluation_service, relation_service, settings_service
from . import event_processor
from .blackboard_service import Blackboard
from .events import event_bus
from .scheduler import Scheduler

logger = logging.getLogger("neurosync.controller")

MIN_PRIORITY = 5.0
TERMINAL_CONFLICT_STATUSES = {"resolved", "inconclusive", "human_review"}


class InvestigationControl:
    def __init__(self) -> None:
        self._pause = threading.Event()
        self._cancel = threading.Event()

    def pause(self) -> None:
        self._pause.set()

    def resume(self) -> None:
        self._pause.clear()

    def cancel(self) -> None:
        self._cancel.set()
        self._pause.clear()

    @property
    def paused(self) -> bool:
        return self._pause.is_set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()


class InvestigationRegistry:
    """Tracks running investigations to prevent duplicates and enable control."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._controls: dict[int, InvestigationControl] = {}

    def register(self, investigation_id: int) -> InvestigationControl | None:
        with self._lock:
            if investigation_id in self._controls:
                return None
            control = InvestigationControl()
            self._controls[investigation_id] = control
            return control

    def get(self, investigation_id: int) -> InvestigationControl | None:
        with self._lock:
            return self._controls.get(investigation_id)

    def is_running(self, investigation_id: int) -> bool:
        with self._lock:
            return investigation_id in self._controls

    def release(self, investigation_id: int) -> None:
        with self._lock:
            self._controls.pop(investigation_id, None)


registry = InvestigationRegistry()


class InvestigationController:
    def __init__(self, db: Session, agents: list[BaseAgent] | None = None) -> None:
        self.db = db
        self.bb = Blackboard(db)
        self.scheduler = Scheduler()
        self.agents = agents or default_agents()
        # Bounds. Read once per run so a single investigation is internally
        # consistent even if the environment changes mid-flight.
        self.max_retries = max(0, int(settings.agent_max_retries))
        self.execution_limit = max(1, int(settings.max_agent_executions))
        self.attempt_cap = max(1, int(settings.max_attempts_per_action))

    # ------------------------------------------------------------------ helpers
    def _build_context(self, investigation: Investigation, control: InvestigationControl) -> AgentContext:
        return AgentContext(
            investigation_id=investigation.id,
            investigation_name=investigation.name,
            research_question=investigation.research_question,
            document_ids=[d.id for d in investigation.documents],
            conflict_ids=[c.id for c in investigation.conflicts],
            enable_llm=bool(investigation.enable_llm and settings_service.llm_enabled(self.db)),
            min_evidence=investigation.min_evidence_threshold,
            cancel_check=lambda: control.cancelled,
        )

    def _record_activity(
        self,
        investigation: Investigation,
        agent_name: str,
        decision,
        result,
        duration_ms: int,
        *,
        sequence: int,
        attempt: int,
        state_summary: str = "",
    ) -> None:
        activity = AgentActivity(
            investigation_id=investigation.id,
            conflict_id=result.conflict_id,
            agent_name=agent_name,
            action=result.action or decision.action.objective,
            input_summary=result.input_summary,
            output_summary=result.output_summary,
            reason=decision.factors,
            blackboard_changes=json.dumps(result.changes or {}),
            status=result.status,
            duration_ms=duration_ms,
            sequence=sequence,
            attempt=attempt,
            input_record_ids=json.dumps(result.input_record_ids or []),
            output_record_ids=json.dumps(result.output_record_ids or []),
            error=result.error or "",
            state_summary=state_summary,
        )
        self.db.add(activity)
        self.db.flush()
        payload = {
            "activity_id": activity.id,
            "agent": agent_name,
            "action": result.action,
            "status": result.status,
            "attempt": attempt,
            "sequence": sequence,
            "output_summary": result.output_summary,
            "priority": decision.priority,
            "reason": decision.factors,
            "breakdown": decision.breakdown,
            "state": state_summary,
            "conflict_id": result.conflict_id,
            "input_record_ids": result.input_record_ids,
            "output_record_ids": result.output_record_ids,
            "error": result.error,
        }
        event_bus.publish(
            self.db,
            investigation.id,
            enums.EventType.AGENT_SELECTED.value,
            payload,
            agent_name=agent_name,
        )
        for ev in result.events:
            event_bus.publish(
                self.db,
                investigation.id,
                ev["event_type"],
                ev.get("payload", {}),
                agent_name=agent_name,
            )

    def _pause_until_resumed(self, investigation: Investigation, control: InvestigationControl) -> None:
        investigation.status = enums.InvestigationStatus.PAUSED.value
        self.db.commit()
        event_bus.publish(
            self.db, investigation.id,
            enums.EventType.INVESTIGATION_PAUSED.value, {"investigation_id": investigation.id},
        )
        while control.paused and not control.cancelled:
            time.sleep(0.2)
        if control.cancelled:
            return
        investigation.status = enums.InvestigationStatus.RUNNING.value
        self.db.commit()
        event_bus.publish(
            self.db, investigation.id,
            enums.EventType.INVESTIGATION_RESUMED.value, {"investigation_id": investigation.id},
        )

    # --------------------------------------------------------------------- run
    def run(self, investigation_id: int, control: InvestigationControl | None = None) -> str:
        investigation = self.db.get(Investigation, investigation_id)
        if investigation is None:
            return enums.InvestigationStopReason.ERROR.value

        control = control or registry.get(investigation_id) or InvestigationControl()

        investigation.status = enums.InvestigationStatus.RUNNING.value
        investigation.started_at = investigation.started_at or datetime.now(timezone.utc)
        self.db.commit()
        event_bus.publish(
            self.db,
            investigation.id,
            enums.EventType.INVESTIGATION_STARTED.value,
            {"investigation_id": investigation.id, "name": investigation.name},
        )

        consecutive_skips = 0
        exhausted: set[str] = set()
        # (revision, action-signature) -> number of times executed this revision.
        executed: dict[tuple[int, str], int] = {}
        revision = 0
        executions = 0
        sequence = 0
        stop_reason = enums.InvestigationStopReason.COMPLETED.value

        try:
            while True:
                self.db.refresh(investigation)
                # Rebuild the context each iteration: documents/conflicts are
                # discovered while the investigation runs, so scoping must track
                # the current blackboard state.
                ctx = self._build_context(investigation, control)

                if control.cancelled:
                    stop_reason = enums.InvestigationStopReason.CANCELLED.value
                    investigation.status = enums.InvestigationStatus.CANCELLED.value
                    break

                if control.paused:
                    self._pause_until_resumed(investigation, control)
                    continue

                if investigation.iteration_count >= investigation.iteration_limit:
                    stop_reason = enums.InvestigationStopReason.ITERATION_LIMIT.value
                    break

                if executions >= self.execution_limit:
                    stop_reason = enums.InvestigationStopReason.EXECUTION_LIMIT.value
                    break

                active_agents = [a for a in self.agents if a.name not in exhausted]
                if not active_agents:
                    stop_reason = enums.InvestigationStopReason.NO_USEFUL_ACTIONS.value
                    break

                decision = self.scheduler.select(active_agents, self.bb, ctx)
                if decision is None or decision.priority < MIN_PRIORITY:
                    stop_reason = enums.InvestigationStopReason.NO_USEFUL_ACTIONS.value
                    break

                action = decision.action
                signature = (revision, action.signature())
                already = executed.get(signature, 0)

                # Anti-infinite-loop guard: identical work that keeps recurring
                # without a blackboard change is stopped, not repeated forever.
                if already >= self.attempt_cap:
                    exhausted.add(action.agent_name)
                    consecutive_skips += 1
                    if consecutive_skips >= len(self.agents):
                        stop_reason = enums.InvestigationStopReason.NO_USEFUL_ACTIONS.value
                        break
                    continue

                investigation.current_agent = action.agent_name
                investigation.current_objective = action.objective
                investigation.current_priority = decision.priority
                investigation.current_info_gain = action.info_gain
                self.db.commit()

                agent = next((a for a in self.agents if a.name == action.agent_name), None)
                if agent is None:
                    stop_reason = enums.InvestigationStopReason.ERROR.value
                    break

                state_summary = decision.state.summary() if decision.state else ""

                # --- execute with bounded retries -------------------------
                logger.info(
                    "running '%s' (%s) revision=%d attempt-capped=%d state[%s]",
                    agent.name, action.objective, revision, already, state_summary,
                )
                result = None
                attempt = 0
                while attempt <= self.max_retries:
                    attempt += 1
                    if control.cancelled:
                        break
                    executions += 1
                    sequence += 1
                    start = time.perf_counter()
                    result = agent.safe_run(self.bb, ctx, action)
                    duration_ms = int((time.perf_counter() - start) * 1000)
                    self._record_activity(
                        investigation,
                        agent.name,
                        decision,
                        result,
                        duration_ms,
                        sequence=sequence,
                        attempt=attempt,
                        state_summary=state_summary,
                    )
                    if result.status != "failed":
                        break  # success or skipped: no retry
                    if result.error:
                        logger.warning(
                            "agent '%s' attempt %d/%d failed: %s",
                            agent.name, attempt, self.max_retries + 1, result.error,
                        )

                if control.cancelled:
                    stop_reason = enums.InvestigationStopReason.CANCELLED.value
                    investigation.status = enums.InvestigationStatus.CANCELLED.value
                    break

                # Count the scheduler step once, regardless of retries.
                executed[signature] = already + 1
                investigation.iteration_count += 1
                self.db.commit()
                event_bus.publish(
                    self.db,
                    investigation.id,
                    enums.EventType.ITERATION_COMPLETED.value,
                    {
                        "iteration": investigation.iteration_count,
                        "agent": agent.name,
                        "status": result.status,
                        "attempts": attempt,
                    },
                )

                # Intelligence layer: reflect new records as typed relations and
                # let the event processor schedule scoped re-evaluation. This
                # never changes which agent the scheduler runs next.
                try:
                    relation_service.sync_relations(self.db, investigation.id, agent_name=agent.name)
                    event_processor.process_pending_events(self.db, investigation.id)
                except Exception:  # pragma: no cover - intelligence layer must not break a run
                    logger.exception("Relation/event processing failed for investigation %s", investigation.id)
                    self.db.rollback()

                if result.status == "success":
                    consecutive_skips = 0
                    # A real change to the blackboard may make previously parked
                    # agents useful again (requirement: re-run on new evidence).
                    if result.changes:
                        revision += 1
                    exhausted.clear()
                else:
                    # Failed (after retries) or produced nothing: park the agent
                    # but keep going with the others - its committed results and
                    # every earlier agent's results are preserved.
                    exhausted.add(agent.name)
                    consecutive_skips += 1
                    if consecutive_skips >= len(self.agents):
                        stop_reason = enums.InvestigationStopReason.NO_USEFUL_ACTIONS.value
                        break

        except Exception as exc:  # pragma: no cover - safety net
            logger.exception("Investigation %s failed", investigation_id)
            investigation.status = enums.InvestigationStatus.ERROR.value
            investigation.error_message = f"Investigation error: {type(exc).__name__}"
            investigation.stop_reason = enums.InvestigationStopReason.ERROR.value
            investigation.current_agent = ""
            investigation.current_objective = ""
            self.db.commit()
            event_bus.publish(
                self.db, investigation.id,
                enums.EventType.INVESTIGATION_COMPLETED.value,
                {"reason": investigation.stop_reason, "error": investigation.error_message},
            )
            return investigation.stop_reason

        investigation.stop_reason = stop_reason
        if investigation.status not in (
            enums.InvestigationStatus.CANCELLED.value,
            enums.InvestigationStatus.ERROR.value,
        ):
            investigation.status = enums.InvestigationStatus.COMPLETED.value
        investigation.completed_at = datetime.now(timezone.utc)
        # No agent is "currently running" once the loop has stopped.
        investigation.current_agent = ""
        investigation.current_objective = ""
        investigation.current_priority = 0.0
        investigation.current_info_gain = 0.0
        self.db.commit()

        event_bus.publish(
            self.db,
            investigation.id,
            enums.EventType.INVESTIGATION_COMPLETED.value,
            {"investigation_id": investigation.id, "reason": stop_reason, "iterations": investigation.iteration_count},
        )

        # Consume any genuinely new information that arrived during the run (for
        # example evidence added while the investigation was finishing). During a
        # normal run every trigger predates the conclusions, so this is a no-op.
        try:
            reevaluation_service.drain(self.db, investigation.id)
        except Exception:  # pragma: no cover - never fail a completed investigation
            logger.exception("Reevaluation failed for investigation %s", investigation.id)
            self.db.rollback()

        return stop_reason
