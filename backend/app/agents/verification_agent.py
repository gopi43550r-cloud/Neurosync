"""Agent 5 - Verification Agent.

Evaluates each hypothesis against the available evidence using the transparent
scoring service, checks source reliability and directness, recomputes confidence
and marks hypotheses supported / contradicted / inconclusive / review-required.
"""
from __future__ import annotations

import json

from ..models import Conflict, Evidence, Hypothesis, enums
from ..services import audit_service
from ..services.scoring_service import score_hypothesis
from .base_agent import Action, AgentContext, AgentResult, BaseAgent


class VerificationAgent(BaseAgent):
    name = "Verification Agent"
    responsibility = "Evaluate hypotheses against evidence and compute transparent support scores."
    required_inputs = ["a conflict with hypotheses", "the evidence recorded for that conflict"]
    expected_outputs = [
        "updated hypothesis status/support scores",
        "updated evidence verification statuses",
    ]
    run_conditions = [
        "a conflict has hypotheses that are still 'proposed'",
        "or has evidence that has not been evaluated yet",
    ]
    stop_conditions = [
        "all hypotheses are scored and all evidence is verified",
    ]

    def _conflicts_to_verify(self, bb, ctx) -> list[Conflict]:
        conflicts = bb.conflicts(ids=ctx.conflict_ids or None)
        result = []
        for c in conflicts:
            hyps = bb.hypotheses(c.id)
            if not hyps:
                continue
            proposed = any(h.status == enums.HypothesisStatus.PROPOSED.value for h in hyps)
            unverified = any(e.verification_status == "unverified" for e in bb.evidence(c.id))
            if proposed or unverified:
                result.append(c)
        return result

    def candidates(self, bb, ctx: AgentContext) -> list[Action]:
        actions = []
        for c in self._conflicts_to_verify(bb, ctx):
            actions.append(
                Action(
                    agent_name=self.name,
                    objective=f"Evaluate hypotheses for conflict {c.id}",
                    conflict_id=c.id,
                    severity=c.severity,
                    uncertainty=0.45,
                    evidence_gap=0.5,
                    info_gain=0.6,
                    cost=0.1,
                    reason="Hypotheses and/or evidence have not been evaluated against each other yet.",
                    payload={"conflict_id": c.id},
                )
            )
        return actions

    def run(self, bb, ctx: AgentContext, action: Action) -> AgentResult:
        conflict = bb.db.get(Conflict, action.conflict_id)
        if conflict is None:
            return AgentResult(
                status="skipped",
                action="verify",
                output_summary="Conflict not found.",
                input_record_ids=[action.conflict_id] if action.conflict_id else [],
            )

        hypotheses = bb.hypotheses(conflict.id)
        events = []
        scored = 0
        scored_ids: list[int] = []
        for hyp in hypotheses:
            score = score_hypothesis(bb.db, hyp)
            hyp.support_score = score.support_score
            hyp.confidence = score.confidence
            hyp.status = score.status
            hyp.supporting_evidence_ids = json.dumps(sorted(score.supporting_ids))
            hyp.contradicting_evidence_ids = json.dumps(sorted(score.contradicting_ids))
            scored += 1
            scored_ids.append(hyp.id)
            audit_service.record(
                bb.db,
                entity_type="hypothesis",
                entity_id=hyp.id,
                action="verified",
                actor="agent",
                investigation_id=ctx.investigation_id,
                conflict_id=conflict.id,
                summary=(
                    f"Hypothesis '{hyp.title}' evaluated as {hyp.status} "
                    f"(support={hyp.support_score:.2f}, confidence={hyp.confidence:.2f})."
                ),
                detail={
                    "status": hyp.status,
                    "support_score": hyp.support_score,
                    "confidence": hyp.confidence,
                    "supporting_evidence_ids": sorted(score.supporting_ids),
                    "contradicting_evidence_ids": sorted(score.contradicting_ids),
                },
            )
            events.append(
                {
                    "event_type": enums.EventType.HYPOTHESIS_VERIFIED.value,
                    "payload": {
                        "conflict_id": conflict.id,
                        "hypothesis_id": hyp.id,
                        "status": hyp.status,
                        "support_score": hyp.support_score,
                        "explanation": score.explanation,
                    },
                }
            )
            if ctx.enable_llm:
                self._record_llm_explanation(bb, ctx, conflict, hyp)

        # Mark evidence as verified based on provenance quality. Missing/inferred
        # evidence is explicitly left as unsupported.
        for ev in bb.evidence(conflict.id):
            if ev.evidence_type == "missing":
                ev.verification_status = enums.VerificationStatus.UNSUPPORTED.value
            elif ev.origin == "inferred":
                ev.verification_status = enums.VerificationStatus.REQUIRES_REVIEW.value
            elif ev.directness >= 0.7 and ev.reliability_score >= 0.6:
                ev.verification_status = enums.VerificationStatus.VERIFIED.value
            elif ev.relevance_score >= 0.4:
                ev.verification_status = enums.VerificationStatus.PARTIALLY_VERIFIED.value
            else:
                ev.verification_status = enums.VerificationStatus.UNSUPPORTED.value

        evidence_items = bb.evidence(conflict.id)
        audit_service.record(
            bb.db,
            entity_type="evidence",
            action="verification_completed",
            actor="agent",
            investigation_id=ctx.investigation_id,
            conflict_id=conflict.id,
            summary=(
                f"Verified {len(evidence_items)} evidence item(s) for conflict {conflict.id}."
            ),
            detail={
                "verified": sum(
                    1 for e in evidence_items if e.verification_status == "verified"
                ),
                "partially_verified": sum(
                    1 for e in evidence_items if e.verification_status == "partially_verified"
                ),
                "requires_review": sum(
                    1 for e in evidence_items if e.verification_status == "requires_review"
                ),
                "unsupported": sum(
                    1 for e in evidence_items if e.verification_status == "unsupported"
                ),
            },
        )

        # If every hypothesis is weak, the conflict needs human review.
        if hypotheses and all(
            h.status in ("inconclusive", "review_required") for h in hypotheses
        ) and conflict.severity in ("high", "critical"):
            conflict.status = enums.ConflictStatus.HUMAN_REVIEW.value

        return AgentResult(
            action="verify_hypotheses",
            conflict_id=conflict.id,
            input_summary=f"{len(hypotheses)} hypothesis(es), {len(bb.evidence(conflict.id))} evidence item(s).",
            output_summary=f"Scored {scored} hypothesis(es) using transparent evidence weighting.",
            changes={"hypotheses_scored": scored},
            events=events,
            input_record_ids=[conflict.id],
            output_record_ids=scored_ids,
        )

    def _record_llm_explanation(self, bb, ctx, conflict, hyp) -> None:
        """Ask the model to explain a hypothesis, then validate its citations.

        Any cited evidence id that does not exist for this conflict means the
        explanation is rejected outright and nothing is recorded as accepted, so
        a fabricated citation can never reach the report.
        """
        from ..services.llm_service import llm_service, valid_evidence_ids

        items = bb.evidence(conflict.id)
        allowed = {e.id for e in items}
        payload = [{"id": e.id, "description": e.description} for e in items]
        explanation = llm_service.explain_hypothesis(hyp.title, payload)
        if explanation is None or not explanation.explanation.strip():
            return
        cited = valid_evidence_ids(explanation.cited_evidence_ids, allowed)
        fabricated = [i for i in explanation.cited_evidence_ids if i not in allowed]
        accepted = not fabricated
        audit_service.record(
            bb.db,
            entity_type="hypothesis",
            entity_id=hyp.id,
            action="llm_explanation",
            actor="llm",
            investigation_id=ctx.investigation_id,
            conflict_id=conflict.id,
            summary=(
                f"AI-assisted explanation for hypothesis '{hyp.title}' "
                + ("accepted (citations validated)." if accepted else "rejected: cited non-existent evidence.")
            ),
            detail={
                "accepted": accepted,
                "explanation": explanation.explanation if accepted else "",
                "cited_evidence_ids": cited,
                "rejected_citation_ids": fabricated,
            },
        )
