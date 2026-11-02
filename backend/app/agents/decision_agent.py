"""Agent 6 - Decision Agent.

Reads the blackboard, decides whether enough evidence exists for a defensible
conclusion, summarises the best-supported explanation, explains why competing
hypotheses are weaker or remain plausible, lists unresolved questions and
limitations, and decides whether to continue or request human review.

Never forces a definitive answer when the evidence is insufficient.
"""
from __future__ import annotations

import json

from ..models import Claim, Conflict, Conclusion, Document, Evidence, Hypothesis, enums
from ..services import audit_service
from .base_agent import Action, AgentContext, AgentResult, BaseAgent


def _loads(value: str) -> list:
    try:
        return json.loads(value or "[]")
    except json.JSONDecodeError:
        return []


class DecisionAgent(BaseAgent):
    name = "Decision Agent"
    responsibility = "Decide whether a defensible conclusion can be drawn and produce it."
    required_inputs = [
        "a conflict whose hypotheses have all been evaluated",
        "at least the configured minimum number of evidence items",
    ]
    expected_outputs = [
        "a conclusion (supported / tentative / inconclusive / human-review) with citations",
        "an updated conflict status",
    ]
    run_conditions = [
        "a conflict has evaluated hypotheses, enough evidence, and no active conclusion",
    ]
    stop_conditions = [
        "every conflict with evaluated hypotheses already has an active conclusion",
        "insufficient evidence to reach a defensible conclusion",
    ]

    def _ready_conflicts(self, bb, ctx) -> list[Conflict]:
        conflicts = bb.conflicts(ids=ctx.conflict_ids or None)
        ready = []
        for c in conflicts:
            hyps = bb.hypotheses(c.id)
            if not hyps:
                continue
            if any(h.status == enums.HypothesisStatus.PROPOSED.value for h in hyps):
                continue
            # A conclusion only blocks a new decision while it is current. A
            # conclusion superseded by an event-driven re-evaluation is retained
            # for the audit trail but no longer counts as an active decision.
            active = [
                x
                for x in bb.conclusions()
                if x.conflict_id == c.id and getattr(x, "superseded_at", None) is None
            ]
            if active:
                continue
            ready.append(c)
        return ready

    def candidates(self, bb, ctx: AgentContext) -> list[Action]:
        actions = []
        for c in self._ready_conflicts(bb, ctx):
            evidence_count = len(bb.evidence(c.id))
            if evidence_count < ctx.min_evidence:
                continue
            actions.append(
                Action(
                    agent_name=self.name,
                    objective=f"Synthesise a conclusion for conflict {c.id}",
                    conflict_id=c.id,
                    severity=c.severity,
                    uncertainty=0.3,
                    evidence_gap=0.3,
                    info_gain=0.2,
                    cost=0.15,
                    reason="All hypotheses have been evaluated; a decision can now be synthesised.",
                    payload={"conflict_id": c.id},
                )
            )
        return actions

    def run(self, bb, ctx: AgentContext, action: Action) -> AgentResult:
        conflict = bb.db.get(Conflict, action.conflict_id)
        if conflict is None:
            return AgentResult(
                status="skipped",
                action="decide",
                output_summary="Conflict not found.",
                input_record_ids=[action.conflict_id] if action.conflict_id else [],
            )

        hypotheses = sorted(bb.hypotheses(conflict.id), key=lambda h: h.support_score, reverse=True)
        top = hypotheses[0]
        second = hypotheses[1] if len(hypotheses) > 1 else None
        margin = top.support_score - (second.support_score if second else 0.0)

        top_evidence = [e for e in bb.evidence(conflict.id) if e.supports_hypothesis_id == top.id]
        distinct_sources = {e.document_id for e in top_evidence if e.document_id}

        # Explicit traceability: name the evidence that actually supports the
        # best explanation so the conclusion can be checked against its sources.
        citations = ""
        if top_evidence:
            refs = []
            for e in top_evidence[:3]:
                src = f" from {e.source_reference}" if e.source_reference else ""
                refs.append(f"Evidence {e.id} ({e.evidence_type}{src}): {e.description[:160]}")
            citations = " Supporting evidence: " + " ".join(refs) + "."
        else:
            citations = " No evidence in the available documents supports this explanation directly."

        unresolved = []
        for h in hypotheses:
            for q in _loads(h.missing_information):
                if q not in unresolved:
                    unresolved.append(q)
            for a in _loads(h.assumptions):
                note = f"Assumption: {a}"
                if note not in unresolved:
                    unresolved.append(note)

        limitations = [
            "Confidence scores are bounded support indicators, not calibrated probabilities.",
            "Only information present in the uploaded documents was considered.",
        ]

        # Decision logic (conservative).
        decision = enums.ConclusionType.INCONCLUSIVE
        if top.status == "supported" and top.support_score >= 0.7 and margin >= 0.15 and len(distinct_sources) >= 2:
            decision = enums.ConclusionType.SUPPORTED
        elif top.status == "supported" and top.support_score >= 0.55 and margin >= 0.1:
            decision = enums.ConclusionType.TENTATIVE
        elif top.status == "review_required" or conflict.status == enums.ConflictStatus.HUMAN_REVIEW.value:
            # A plausible lead exists but it is not independently corroborated
            # (single source) or the conflict was already flagged, so it cannot
            # be resolved automatically. Contextual evidence is not proof.
            decision = enums.ConclusionType.HUMAN_REVIEW

        confidence = round(min(0.9, top.support_score * (0.7 if decision == enums.ConclusionType.SUPPORTED else 0.6)), 3)

        best = (
            f"Best-supported explanation: \"{top.title}\" (support {top.support_score:.2f}). "
            f"{top.explanation}"
        )
        weaker = ""
        if second:
            weaker = (
                f" Competing explanation \"{second.title}\" is weaker (support "
                f"{second.support_score:.2f}); remaining hypotheses are less supported."
            )

        lead_claim_a = bb.db.get(Claim, conflict.claim_a_id)
        lead_claim_b = bb.db.get(Claim, conflict.claim_b_id)
        sources = sorted({c.source_reference for c in (lead_claim_a, lead_claim_b) if c and c.source_reference})

        if decision == enums.ConclusionType.SUPPORTED:
            text = f"{best}{weaker} The evidence is consistent with this explanation."
        elif decision == enums.ConclusionType.TENTATIVE:
            text = f"{best}{weaker} This remains tentative: the available evidence is insufficient to rule out competing explanations."
        elif decision == enums.ConclusionType.HUMAN_REVIEW:
            text = (
                f"The evidence about '{conflict.conflict_type}' could not be resolved "
                f"automatically from the available documents. Human review is recommended. {best}"
            )
        else:
            text = (
                "The available evidence does not establish a single definitive explanation. "
                f"{best}{weaker} The conflict remains inconclusive."
            )

        text = f"{text}{citations}"

        if ctx.enable_llm:
            text = self._append_llm_explanation(bb, ctx, conflict, top, second, decision, top_evidence, text)

        conclusion = Conclusion(
            investigation_id=ctx.investigation_id,
            conflict_id=conflict.id,
            decision_type=decision.value,
            conclusion=text,
            confidence=confidence,
            supporting_evidence_ids=json.dumps([e.id for e in top_evidence]),
            unresolved_questions=json.dumps(unresolved),
            limitations=json.dumps(limitations),
        )
        bb.db.add(conclusion)
        bb.db.flush()

        audit_service.record(
            bb.db,
            entity_type="conclusion",
            entity_id=conclusion.id,
            action="created",
            actor="agent",
            investigation_id=ctx.investigation_id,
            conflict_id=conflict.id,
            summary=f"Conclusion for conflict {conflict.id}: {decision.value} (confidence {confidence:.2f}).",
            detail={
                "decision_type": decision.value,
                "confidence": confidence,
                "best_hypothesis_id": top.id,
                "supporting_evidence_ids": [e.id for e in top_evidence],
                "unresolved_questions": unresolved,
            },
        )

        conflict.status = (
            enums.ConflictStatus.RESOLVED.value
            if decision == enums.ConclusionType.SUPPORTED
            else (
                enums.ConflictStatus.HUMAN_REVIEW.value
                if decision == enums.ConclusionType.HUMAN_REVIEW
                else enums.ConflictStatus.INCONCLUSIVE.value
            )
        )
        conflict.resolution_summary = text[:500]

        events = [
            {
                "event_type": enums.EventType.CONCLUSION_REACHED.value,
                "payload": {
                    "conflict_id": conflict.id,
                    "conclusion_id": conclusion.id,
                    "decision_type": decision.value,
                    "confidence": confidence,
                    "sources": sources,
                },
            }
        ]
        if decision == enums.ConclusionType.HUMAN_REVIEW:
            events.append(
                {
                    "event_type": enums.EventType.HUMAN_REVIEW_REQUESTED.value,
                    "payload": {
                        "conflict_id": conflict.id,
                        "reason": "Conflict could not be resolved automatically from available evidence.",
                    },
                }
            )

        return AgentResult(
            action="decide",
            conflict_id=conflict.id,
            input_summary=f"{len(hypotheses)} hypothesis(es), {len(bb.evidence(conflict.id))} evidence item(s).",
            output_summary=f"Decision: {decision.value} (confidence {confidence:.2f}).",
            changes={"conclusions_added": 1, "decision_type": decision.value},
            events=events,
            input_record_ids=[conflict.id],
            output_record_ids=[conclusion.id],
        )

    def _append_llm_explanation(self, bb, ctx, conflict, top, second, decision, top_evidence, text) -> str:
        """Append a grounded, citation-validated explanation when AI is enabled.

        The model may only cite evidence that actually supports the best
        hypothesis. If it cites anything else, the explanation is discarded, so a
        fabricated citation is never written into a conclusion.
        """
        from ..services.llm_service import llm_service, valid_evidence_ids

        allowed = {e.id for e in top_evidence}
        competitors = ", ".join(
            f"{h.title} (support {h.support_score:.2f})" for h in bb.hypotheses(conflict.id)[:4]
        )
        summary = (
            f"Conflict type: {conflict.conflict_type}. "
            f"Best explanation: \"{top.title}\" (support {top.support_score:.2f}). "
            f"Decision: {decision.value}. Candidate explanations: {competitors}."
        )
        explanation = llm_service.explain_decision(summary, sorted(allowed))
        if explanation is None or not explanation.explanation.strip():
            return text
        cited = valid_evidence_ids(explanation.cited_evidence_ids, allowed)
        fabricated = [i for i in explanation.cited_evidence_ids if i not in allowed]
        accepted = not fabricated
        audit_service.record(
            bb.db,
            entity_type="conclusion",
            entity_id=conflict.id,
            action="llm_explanation",
            actor="llm",
            investigation_id=ctx.investigation_id,
            conflict_id=conflict.id,
            summary=(
                "AI-assisted decision explanation "
                + ("accepted (citations validated)." if accepted else "rejected: cited non-existent evidence.")
            ),
            detail={
                "accepted": accepted,
                "explanation": explanation.explanation if accepted else "",
                "cited_evidence_ids": cited,
                "rejected_citation_ids": fabricated,
                "best_hypothesis_id": top.id,
            },
        )
        if not accepted:
            return text
        refs = f" Evidence referenced: {cited}." if cited else ""
        return f"{text} AI-assisted explanation (grounded in the cited evidence).{refs} {explanation.explanation}"
