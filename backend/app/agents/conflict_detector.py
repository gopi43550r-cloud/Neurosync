"""Agent 2 - Conflict Detector.

Compares relevant claims, identifies potential contradictions and incompatible
measurements, considers units and timestamps, assigns severity and confidence,
and stores conflicts. Uses deterministic rules. Prevents duplicate conflicts.
"""
from __future__ import annotations

from sqlalchemy import select

from ..models import Claim, Conflict, Investigation, enums
from ..services import audit_service
from ..services.conflict_service import conflict_exists, detect_conflicts
from .base_agent import Action, AgentContext, AgentResult, BaseAgent


class ConflictDetector(BaseAgent):
    name = "Conflict Detector"
    responsibility = "Identify potential contradictions between claims and record them."
    required_inputs = ["at least two claims in scope with comparable subjects"]
    expected_outputs = ["conflicts (typed, with severity and confidence)"]
    run_conditions = [
        "two or more in-scope claims exist",
        "and no conflict of the same pair/type has already been recorded",
    ]
    stop_conditions = [
        "no new contradictions are found among the current claims",
        "fewer than two claims are available to compare",
    ]

    def _scope_claims(self, bb, ctx) -> list[Claim]:
        if ctx.document_ids:
            return bb.claims(ctx.document_ids)
        return bb.claims()

    def candidates(self, bb, ctx: AgentContext) -> list[Action]:
        claims = self._scope_claims(bb, ctx)
        if len(claims) < 2:
            return []
        existing = len(bb.conflicts())
        # Once conflicts exist the detector has mostly done its work, so its
        # priority drops sharply and other agents (investigation, verification,
        # decision) take precedence.
        if existing == 0:
            return [
                Action(
                    agent_name=self.name,
                    objective="Compare cross-document claims for contradictions",
                    severity="high",
                    uncertainty=0.5,
                    evidence_gap=0.7,
                    info_gain=0.55,
                    cost=0.05,
                    reason=(
                        "Claims from multiple documents share comparable subjects; "
                        "cross-document comparison may reveal contradictions."
                    ),
                    payload={"claim_ids": [c.id for c in claims]},
                )
            ]
        return [
            Action(
                agent_name=self.name,
                objective="Re-scan claims for any newly introduced contradictions",
                severity="low",
                uncertainty=0.15,
                evidence_gap=0.1,
                info_gain=0.1,
                cost=0.05,
                reason="Conflicts already exist; a low-priority re-scan is available.",
                payload={"claim_ids": [c.id for c in claims]},
            )
        ]

    def run(self, bb, ctx: AgentContext, action: Action) -> AgentResult:
        claims = self._scope_claims(bb, ctx)
        detected = detect_conflicts(claims)
        created = 0
        created_ids: list[int] = []
        events = []
        for d in detected:
            if conflict_exists(bb.db, d.claim_a_id, d.claim_b_id, d.conflict_type):
                continue
            meta = dict(d.meta or {})
            # LLM provides a *second opinion* only. Conflicts are created solely
            # from the deterministic, evidence-based detector, so the model can
            # never introduce a conflict that is not supported by the claims.
            if ctx.enable_llm:
                assessment = self._assess(bb, d.claim_a_id, d.claim_b_id)
                if assessment is not None:
                    meta["llm_assessment"] = assessment
            conflict = bb.add_conflict(
                claim_a_id=d.claim_a_id,
                claim_b_id=d.claim_b_id,
                conflict_type=d.conflict_type,
                description=d.description,
                severity=d.severity,
                detection_method=d.detection_method,
                confidence=d.confidence,
                status=enums.ConflictStatus.OPEN.value,
                meta=__import__("json").dumps(meta),
            )
            created += 1
            created_ids.append(conflict.id)
            # Associate the newly discovered conflict with its investigation so
            # that reports, statistics and detail views include it. Conflicts are
            # discovered during the run, so they are not known at creation time.
            if ctx.investigation_id:
                investigation = bb.db.get(Investigation, ctx.investigation_id)
                if investigation is not None and conflict not in investigation.conflicts:
                    investigation.conflicts.append(conflict)
            audit_service.record(
                bb.db,
                entity_type="conflict",
                entity_id=conflict.id,
                action="created",
                actor="agent",
                investigation_id=ctx.investigation_id,
                conflict_id=conflict.id,
                summary=(
                    f"Detected {conflict.conflict_type} (severity={conflict.severity}): "
                    f"{conflict.description[:180]}"
                ),
                detail={
                    "claim_a_id": conflict.claim_a_id,
                    "claim_b_id": conflict.claim_b_id,
                    "conflict_type": conflict.conflict_type,
                    "severity": conflict.severity,
                    "confidence": conflict.confidence,
                    "meta": meta,
                },
            )
            events.append(
                {
                    "event_type": enums.EventType.CONFLICT_DETECTED.value,
                    "payload": {
                        "conflict_id": conflict.id,
                        "conflict_type": conflict.conflict_type,
                        "severity": conflict.severity,
                        "description": conflict.description[:240],
                    },
                }
            )
        if created == 0:
            return AgentResult(
                status="skipped",
                action="detect_conflicts",
                input_summary=f"Compared {len(claims)} claim(s).",
                output_summary="No new conflicts found.",
                changes={},
                input_record_ids=[c.id for c in claims],
            )
        return AgentResult(
            action="detect_conflicts",
            input_summary=f"Compared {len(claims)} claim(s).",
            output_summary=f"Detected {created} new conflict(s).",
            changes={"conflicts_added": created},
            events=events,
            input_record_ids=[c.id for c in claims],
            output_record_ids=created_ids,
        )

    @staticmethod
    def _assess(bb, claim_a_id: int, claim_b_id: int) -> dict | None:
        """Ask the model for a second opinion on a pair the rules already flagged."""
        from ..services.llm_service import llm_service

        claim_a = bb.db.get(Claim, claim_a_id)
        claim_b = bb.db.get(Claim, claim_b_id)
        if claim_a is None or claim_b is None:
            return None
        assessment = llm_service.assess_conflict(claim_a.claim_text, claim_b.claim_text)
        if assessment is None:
            return None
        return {
            "is_conflict": assessment.is_conflict,
            "conflict_type": assessment.conflict_type,
            "reason": assessment.reason,
            "note": "Second opinion only; the conflict was created by deterministic, evidence-based rules.",
        }
