"""Scoped, event-driven re-evaluation.

:mod:`app.blackboard.event_processor` decides *that* some reasoning is stale and
records a :class:`~app.models.ReevaluationTask`. This module decides whether the
task is **genuine new information** and, if so, re-runs only the affected agent(s)
for the affected conflict.

The "genuine" test is what keeps the deterministic baseline investigation
unchanged: a task is only acted on when its triggering event happened *after* the
conflict's most recent conclusion. Events that merely preceded the conclusion
(which is always the case during a normal run) are marked processed without
re-running anything.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..agents.base_agent import AgentContext
from ..agents.decision_agent import DecisionAgent
from ..agents.verification_agent import VerificationAgent
from ..blackboard.blackboard_service import Blackboard
from ..blackboard.event_processor import pending_tasks
from ..blackboard.events import event_bus
from ..models import Conclusion, Conflict, EventLog, Investigation, enums
from . import audit_service, settings_service

logger = logging.getLogger("neurosync.reevaluation")

TERMINAL_CONFLICT_STATUSES = {"resolved", "inconclusive", "human_review"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def latest_conclusion(db: Session, conflict_id: int) -> Conclusion | None:
    return db.execute(
        select(Conclusion).where(Conclusion.conflict_id == conflict_id).order_by(Conclusion.id.desc())
    ).scalars().first()


def _is_genuine(task_trigger: EventLog | None, conclusion: Conclusion | None) -> bool:
    """True only when the trigger happened after the latest conclusion."""
    if conclusion is None:
        return False  # not terminal yet; the normal loop owns this conflict
    if task_trigger is None or task_trigger.created_at is None:
        return True
    if conclusion.created_at is None:
        return True
    return task_trigger.created_at > conclusion.created_at


def _context(db: Session, investigation: Investigation, conflict_id: int) -> AgentContext:
    return AgentContext(
        investigation_id=investigation.id,
        investigation_name=investigation.name,
        research_question=investigation.research_question,
        document_ids=[d.id for d in investigation.documents],
        conflict_ids=[conflict_id],
        enable_llm=bool(investigation.enable_llm and settings_service.llm_enabled(db)),
        min_evidence=investigation.min_evidence_threshold,
    )


def drain(db: Session, investigation_id: int | None = None, max_tasks: int = 100) -> dict[str, int]:
    """Consume pending re-evaluation tasks, re-running only what is necessary."""
    summary = {"tasks": 0, "genuine": 0, "reopened": 0, "hypotheses_rescored": 0, "conclusions_revised": 0, "skipped": 0}
    tasks = pending_tasks(db, investigation_id)[:max_tasks]
    for task in tasks:
        summary["tasks"] += 1
        conflict = db.get(Conflict, task.conflict_id) if task.conflict_id else None
        if conflict is None:
            task.status = "processed"
            task.processed_at = _now()
            summary["skipped"] += 1
            continue
        trigger = db.get(EventLog, task.trigger_event_id) if task.trigger_event_id else None
        conclusion = latest_conclusion(db, conflict.id)

        if not _is_genuine(trigger, conclusion):
            task.status = "processed"
            task.processed_at = _now()
            summary["skipped"] += 1
            continue

        summary["genuine"] += 1
        investigation = db.get(Investigation, task.investigation_id) if task.investigation_id else None
        if investigation is None:
            task.status = "processed"
            task.processed_at = _now()
            continue

        bb = Blackboard(db)
        ctx = _context(db, investigation, conflict.id)

        if conflict.status in TERMINAL_CONFLICT_STATUSES:
            conflict.status = enums.ConflictStatus.INVESTIGATING.value
            summary["reopened"] += 1

        audit_service.record(
            db,
            entity_type="conflict",
            entity_id=conflict.id,
            action="reevaluated",
            actor="Event Processor",
            investigation_id=investigation.id,
            conflict_id=conflict.id,
            summary=(
                f"Re-opened conflict {conflict.id} because "
                f"'{trigger.event_type if trigger else 'new information'}' arrived after the last conclusion."
            ),
            detail={"kind": task.kind, "trigger_event_id": task.trigger_event_id, "reason": task.reason},
        )

        verify_agent = VerificationAgent()
        verify_actions = verify_agent.candidates(bb, ctx)
        verify_result = verify_agent.safe_run(
            bb,
            ctx,
            verify_actions[0] if verify_actions else _manual_action(conflict.id, "verify_hypotheses"),
        )
        if verify_result.status == "success":
            summary["hypotheses_rescored"] += 1

        # Publish before any revised decision so this event always predates the
        # new conclusion; the "genuine" guard then treats the follow-up work as
        # already satisfied instead of re-opening the conflict forever.
        event_bus.publish(
            db,
            investigation.id,
            enums.EventType.HYPOTHESIS_UPDATED.value,
            {
                "conflict_id": conflict.id,
                "kind": task.kind,
                "trigger_event_id": task.trigger_event_id,
            },
            agent_name="Event Processor",
            entity_type="conflict",
            entity_id=conflict.id,
        )

        new_conclusion_id: int | None = None
        if task.kind == "decide" and conclusion is not None:
            # The prior conclusion is stale (its trigger predates it no longer);
            # temporarily mark it superseded so the Decision Agent is allowed to
            # synthesise a revised conclusion for the same conflict.
            conclusion.superseded_at = _now()
            db.flush()
            decision_agent = DecisionAgent()
            actions = decision_agent.candidates(bb, ctx)
            if actions:
                result = decision_agent.safe_run(bb, ctx, actions[0])
                if result.status == "success":
                    revised = latest_conclusion(db, conflict.id)
                    if revised is not None and revised.id != conclusion.id:
                        new_conclusion_id = revised.id
                        summary["conclusions_revised"] += 1
            if new_conclusion_id is not None:
                conclusion.superseded_by_id = new_conclusion_id
            else:
                # No revised conclusion could be produced: keep the original
                # conclusion active rather than leaving the conflict unresolved.
                conclusion.superseded_at = None

        task.status = "processed"
        task.processed_at = _now()
        db.flush()

    db.commit()
    return summary


def _manual_action(conflict_id: int, objective: str):
    from ..agents.base_agent import Action

    return Action(agent_name="Verification Agent", objective=objective, conflict_id=conflict_id)
