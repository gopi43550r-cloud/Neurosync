"""Dynamic investigation scheduler.

Collects candidate actions from all eligible agents, estimates the value of
each, and selects the highest-priority useful action. This is a transparent
heuristic, not a proven optimal algorithm.

Priority (normalized 0-100)::

    Priority = 100 * ( w_sev*Severity + w_unc*Uncertainty
                       + w_gap*EvidenceGap + w_gain*InfoGain )
             - CostPenalty

where CostPenalty = cost * 100 * 0.15 (bounded). Weights are configurable via
environment variables (see ``config.Settings.weights``).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..agents.base_agent import Action, AgentContext, BaseAgent
from ..blackboard.blackboard_service import Blackboard
from ..config import settings
from ..services.scoring_service import scheduler_priority
from .state import BlackboardState, assess


@dataclass
class SchedulerDecision:
    action: Action
    priority: float
    breakdown: dict[str, float] = field(default_factory=dict)
    factors: str = ""
    state: BlackboardState | None = None


class Scheduler:
    def __init__(self, weights: dict[str, float] | None = None) -> None:
        self.weights = weights or settings.weights

    def collect(self, agents: list[BaseAgent], bb: Blackboard, ctx: AgentContext) -> list[Action]:
        actions: list[Action] = []
        for agent in agents:
            try:
                actions.extend(agent.candidates(bb, ctx))
            except Exception:  # noqa: BLE001 - one agent must not break scheduling
                continue
        return actions

    def score(self, action: Action) -> SchedulerDecision:
        base = scheduler_priority(
            action.severity,
            action.uncertainty,
            action.evidence_gap,
            action.info_gain,
            self.weights,
        )
        cost_penalty = round(min(30.0, action.cost * 100.0 * 0.15), 2)
        priority = round(max(0.0, base - cost_penalty), 2)
        breakdown = {
            "severity_component": round(100 * self.weights["severity"] * self._sev(action.severity), 2),
            "uncertainty_component": round(100 * self.weights["uncertainty"] * action.uncertainty, 2),
            "evidence_gap_component": round(100 * self.weights["evidence_gap"] * action.evidence_gap, 2),
            "info_gain_component": round(100 * self.weights["info_gain"] * action.info_gain, 2),
            "cost_penalty": -cost_penalty,
        }
        factors = (
            f"severity={action.severity} (w={self.weights['severity']:.2f}), "
            f"uncertainty={action.uncertainty:.2f} (w={self.weights['uncertainty']:.2f}), "
            f"evidence_gap={action.evidence_gap:.2f} (w={self.weights['evidence_gap']:.2f}), "
            f"info_gain={action.info_gain:.2f} (w={self.weights['info_gain']:.2f}), "
            f"cost={action.cost:.2f}"
        )
        return SchedulerDecision(action=action, priority=priority, breakdown=breakdown, factors=factors)

    def select(self, agents: list[BaseAgent], bb: Blackboard, ctx: AgentContext) -> SchedulerDecision | None:
        actions = self.collect(agents, bb, ctx)
        if not actions:
            return None
        scored = [self.score(a) for a in actions]
        scored.sort(key=lambda d: d.priority, reverse=True)
        best = scored[0]
        # Attach the blackboard state the decision was derived from, so the
        # choice is explainable and auditable.
        best.state = assess(bb, ctx)
        return best

    @staticmethod
    def _sev(severity: str) -> float:
        return {"low": 0.25, "medium": 0.5, "high": 0.75, "critical": 1.0}.get(severity, 0.5)
