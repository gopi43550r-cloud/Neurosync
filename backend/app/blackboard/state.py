"""Blackboard state assessment.

The scheduler does not guess what to do next: it selects the highest-priority
action proposed by the agents, and every action is derived from an explicit
reading of the shared blackboard. :func:`assess` produces that reading as a
single, serialisable snapshot of the decision-relevant state:

* available evidence,
* unresolved conflicts,
* hypothesis status,
* verification status,
* missing information.

The snapshot is attached to each scheduler decision (and recorded on the
matching execution-ledger entry) so the *reason* an agent was chosen is
reproducible and auditable rather than implied.
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

from ..models import enums

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..agents.base_agent import AgentContext
    from .blackboard_service import Blackboard

UNRESOLVED_STATUSES = {"open", "investigating", "human_review"}


@dataclass
class BlackboardState:
    documents_total: int = 0
    documents_awaiting_extraction: int = 0
    claims_total: int = 0
    conflicts_total: int = 0
    unresolved_conflicts: int = 0
    hypotheses_total: int = 0
    hypotheses_proposed: int = 0
    evidence_total: int = 0
    evidence_unverified: int = 0
    evidence_missing: int = 0
    ready_for_decision: int = 0
    missing_information_flags: int = 0

    def as_dict(self) -> dict[str, int]:
        return asdict(self)

    def summary(self) -> str:
        """A compact, human-readable description of the decision state."""
        return (
            f"evidence={self.evidence_total} (unverified={self.evidence_unverified}, "
            f"missing={self.evidence_missing}); unresolved_conflicts={self.unresolved_conflicts}; "
            f"hypotheses={self.hypotheses_total} (proposed={self.hypotheses_proposed}); "
            f"ready_for_decision={self.ready_for_decision}; "
            f"missing_information_flags={self.missing_information_flags}; "
            f"claims={self.claims_total}; documents_awaiting_extraction={self.documents_awaiting_extraction}"
        )


def _loads(value: str | None) -> list:
    try:
        return json.loads(value or "[]")
    except (TypeError, json.JSONDecodeError):
        return []


def assess(bb: "Blackboard", ctx: "AgentContext") -> BlackboardState:
    """Read the decision-relevant state of the blackboard for ``ctx``'s scope."""
    state = BlackboardState()

    documents = bb.documents(ctx.document_ids or None)
    state.documents_total = len(documents)
    claims = bb.claims(ctx.document_ids or None)
    claim_doc_ids = {c.document_id for c in claims}
    state.documents_awaiting_extraction = sum(
        1 for d in documents if d.status == "processed" and d.id not in claim_doc_ids
    )
    state.claims_total = len(claims)

    conflicts = bb.conflicts(ids=ctx.conflict_ids or None)
    state.conflicts_total = len(conflicts)
    conflict_ids = [c.id for c in conflicts]

    # Batch-load the per-conflict children once instead of querying hypotheses
    # and evidence for every conflict (the old N+1).
    hypotheses_by_conflict: dict[int, list] = defaultdict(list)
    for h in bb.hypotheses_for(conflict_ids):
        hypotheses_by_conflict[h.conflict_id].append(h)
    evidence_by_conflict: dict[int, list] = defaultdict(list)
    for e in bb.evidence_for(conflict_ids):
        evidence_by_conflict[e.conflict_id].append(e)
    active_conclusion_conflicts = {
        c.conflict_id for c in bb.conclusions() if getattr(c, "superseded_at", None) is None
    }

    for conflict in conflicts:
        if conflict.status in UNRESOLVED_STATUSES:
            state.unresolved_conflicts += 1

        hypotheses = hypotheses_by_conflict.get(conflict.id, [])
        state.hypotheses_total += len(hypotheses)
        state.hypotheses_proposed += sum(
            1 for h in hypotheses if h.status == enums.HypothesisStatus.PROPOSED.value
        )
        for h in hypotheses:
            state.missing_information_flags += len(_loads(h.missing_information))

        evidence = evidence_by_conflict.get(conflict.id, [])
        state.evidence_total += len(evidence)
        state.evidence_unverified += sum(
            1 for e in evidence if e.verification_status == enums.VerificationStatus.UNVERIFIED.value
        )
        state.evidence_missing += sum(1 for e in evidence if e.evidence_type == "missing")

        evaluated = hypotheses and all(
            h.status != enums.HypothesisStatus.PROPOSED.value for h in hypotheses
        )
        active_conclusion = conflict.id in active_conclusion_conflicts
        if evaluated and not active_conclusion and len(evidence) >= ctx.min_evidence:
            state.ready_for_decision += 1

    return state
