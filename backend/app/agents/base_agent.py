"""Base agent interface.

Every agent declares an explicit *contract* - what it is responsible for, what
inputs it needs, what outputs it produces, and the conditions under which it
should run or stop - and implements two methods:

  1. ``candidates`` - read the blackboard and return the schedulable actions it
     currently has useful work for (empty means "nothing to do");
  2. ``run`` - execute one action and write structured results back.

The controller (see ``blackboard/controller.py``) owns the loop: it selects an
action via the scheduler, runs the agent with failure isolation and bounded
retries, records an execution ledger entry, and repeats until a stopping
condition is met. Agents never decide the schedule themselves and never produce
a final answer independently: all shared state lives on the blackboard.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from ..blackboard.blackboard_service import Blackboard


@dataclass
class AgentContext:
    investigation_id: int | None = None
    investigation_name: str = ""
    research_question: str = ""
    document_ids: list[int] = field(default_factory=list)
    conflict_ids: list[int] = field(default_factory=list)
    enable_llm: bool = False
    min_evidence: int = 1
    # Optional cooperative-cancellation hook supplied by the controller. Agents
    # with long inner loops may poll ``ctx.cancelled()``; when it is ``None``
    # cancellation is only honoured between agent steps.
    cancel_check: Callable[[], bool] | None = None

    def cancelled(self) -> bool:
        return bool(self.cancel_check and self.cancel_check())


@dataclass
class Action:
    """A schedulable unit of work proposed by an agent."""

    agent_name: str
    objective: str
    conflict_id: int | None = None
    severity: str = "medium"
    uncertainty: float = 0.5
    evidence_gap: float = 0.5
    info_gain: float = 0.5
    cost: float = 0.1
    reason: str = ""
    payload: dict[str, Any] = field(default_factory=dict)

    def signature(self) -> str:
        """Identify the same unit of work for repeated-processing detection."""
        return f"{self.agent_name}|{self.objective}|{self.conflict_id}"


@dataclass
class AgentResult:
    status: str = "success"  # success | skipped | failed
    action: str = ""
    input_summary: str = ""
    output_summary: str = ""
    changes: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    conflict_id: int | None = None
    event_type: str | None = None
    event_payload: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    # Blackboard record ids this run consumed and produced, for the execution
    # ledger (requirement: track input and output record IDs).
    input_record_ids: list[int] = field(default_factory=list)
    output_record_ids: list[int] = field(default_factory=list)


class BaseAgent(ABC):
    # --- identity ---------------------------------------------------------
    name: str = "Agent"
    responsibility: str = ""

    # --- declarative contract --------------------------------------------
    # Blackboard data the agent reads before it can act.
    required_inputs: list[str] = []
    # Blackboard records the agent creates or updates.
    expected_outputs: list[str] = []
    # Conditions "on the blackboard" that make this agent eligible to run.
    run_conditions: list[str] = []
    # Conditions that mean this agent has no further useful work.
    stop_conditions: list[str] = []

    @abstractmethod
    def candidates(self, bb: "Blackboard", ctx: AgentContext) -> list[Action]:
        """Return schedulable actions; an empty list means no useful work."""

    @abstractmethod
    def run(self, bb: "Blackboard", ctx: AgentContext, action: Action) -> AgentResult:
        """Execute the action against the blackboard."""

    def manifest(self) -> dict[str, Any]:
        """A serialisable description of the agent's contract."""
        return {
            "name": self.name,
            "responsibility": self.responsibility,
            "required_inputs": list(self.required_inputs),
            "expected_outputs": list(self.expected_outputs),
            "run_conditions": list(self.run_conditions),
            "stop_conditions": list(self.stop_conditions),
        }

    def safe_run(self, bb: "Blackboard", ctx: AgentContext, action: Action) -> AgentResult:
        """Wrap ``run`` with failure isolation.

        A failing agent never crashes the application and never corrupts the
        shared blackboard: the session is rolled back, so any partial writes from
        the failed attempt are discarded while everything committed by earlier
        agents is preserved. The failure is returned as a structured result so
        the controller can record it and retry.
        """
        try:
            result = self.run(bb, ctx, action)
            bb.commit()
            return result
        except Exception as exc:  # noqa: BLE001 - isolate agent failures
            bb.rollback()
            return AgentResult(
                status="failed",
                action=action.objective,
                input_summary=action.objective,
                output_summary=f"{self.name} failed: {type(exc).__name__}",
                error=f"{type(exc).__name__}: {exc}",
                conflict_id=action.conflict_id,
                input_record_ids=_ids_from_payload(action.payload),
            )


def _ids_from_payload(payload: dict[str, Any]) -> list[int]:
    """Best-effort extraction of record ids an action referred to (for failures)."""
    ids: list[int] = []
    for key in ("document_ids", "claim_ids", "hypothesis_ids", "evidence_ids", "conflict_ids"):
        value = payload.get(key)
        if isinstance(value, list):
            ids.extend(v for v in value if isinstance(v, int))
    for key in ("conflict_id", "document_id"):
        value = payload.get(key)
        if isinstance(value, int):
            ids.append(value)
    return sorted(set(ids))
