"""Agent 3 - Hypothesis Generator.

Reads unresolved conflicts and proposes multiple competing explanations as
provisional hypotheses. Records assumptions and missing information. Seeds
initial evidence that directly references the conflicting claims (with
provenance). Never selects a single hypothesis as correct.
"""
from __future__ import annotations

import json

from ..models import Claim, Conflict, enums
from ..services import audit_service
from ..services.evidence_service import create_evidence
from .base_agent import Action, AgentContext, AgentResult, BaseAgent

TEMPLATES: dict[str, list[dict]] = {
    "temporal_inconsistency": [
        {
            "title": "Genuine change in conditions over time",
            "explanation": "The reported values genuinely differ because the measurements were taken at different times and the machine conditions changed between them.",
            "assumptions": ["The recorded timestamps are accurate."],
            "missing_information": ["Evidence of a trend between the two measurement times."],
        },
        {
            "title": "Sensor measurement or calibration effect",
            "explanation": "A sensor recalibration or measurement drift made the readings non-comparable, so the apparent difference reflects instrument behaviour rather than the machine.",
            "assumptions": ["A sensor is involved and may have been recalibrated."],
            "missing_information": ["Whether the sensor was recalibrated between the readings."],
        },
        {
            "title": "Operating conditions differed between inspections",
            "explanation": "The machine was operated under different load or environmental conditions at each inspection, explaining the different readings.",
            "assumptions": ["Load/physical conditions are relevant to the measurement."],
            "missing_information": ["Load or operating-condition data for each inspection."],
        },
        {
            "title": "Incomplete reporting / missing context",
            "explanation": "The reports omit context (time, location, conditions) needed to compare the readings, so the difference cannot be interpreted.",
            "assumptions": ["The reports are not exhaustive."],
            "missing_information": ["Complete context for each measurement."],
        },
    ],
    "numerical_disagreement": [
        {
            "title": "Sensor or measurement-source issue",
            "explanation": (
                "The two readings may come from different measurement sources, or the "
                "sensor may have been miscalibrated or drifting, so the disagreement "
                "reflects instrumentation rather than a real change in the machine."
            ),
            "assumptions": ["A sensor or instrument was used and may not be fully trustworthy."],
            "missing_information": [
                "Calibration history of the sensor and the measurement source for each reading."
            ],
        },
        {
            "title": "Measurement or transcription error",
            "explanation": "One of the recorded values is erroneous due to a measurement or transcription error.",
            "assumptions": ["Only one of the values is correct."],
            "missing_information": ["Independent confirmation of either value."],
        },
        {
            "title": "Genuine difference under otherwise similar conditions",
            "explanation": "The machine genuinely produced different values with no distinguishing context recorded.",
            "assumptions": ["Conditions were comparable."],
            "missing_information": ["Conditions and exact timing for each measurement."],
        },
        {
            "title": "Incomplete reporting / missing context",
            "explanation": "Context that would explain the differing values was not recorded.",
            "assumptions": ["The reports omit relevant details."],
            "missing_information": ["Timing, location and conditions of each measurement."],
        },
    ],
    "missing_context": [
        {
            "title": "Measurements are not directly comparable (unit/context)",
            "explanation": "The values use different units or lack the context required for a valid comparison.",
            "assumptions": ["Units or measurement context differ."],
            "missing_information": ["Units and measurement context for each value."],
        },
        {
            "title": "Underlying quantity is genuinely the same",
            "explanation": "Once units and context are normalised, the measurements may actually agree.",
            "assumptions": ["A unit/scale conversion resolves the apparent difference."],
            "missing_information": ["Confirmation of the unit system used in each report."],
        },
    ],
    "direct_contradiction": [
        {
            "title": "Reports describe different states at different times",
            "explanation": "The opposing statements are both true but refer to different moments, so they are not actually contradictory.",
            "assumptions": ["The observations were made at different times."],
            "missing_information": ["Timestamps confirming the observations were at different times."],
        },
        {
            "title": "One report is inaccurate or incomplete",
            "explanation": "At least one report is incorrect or based on an incomplete observation.",
            "assumptions": ["The reports cannot both be correct for the same moment."],
            "missing_information": ["Independent observation or instrumentation data."],
        },
        {
            "title": "Different criteria were used to judge the state",
            "explanation": "The observers applied different thresholds or definitions when classifying the state.",
            "assumptions": ["Judgement of the state is subjective or threshold-dependent."],
            "missing_information": ["The criteria or thresholds used by each observer."],
        },
    ],
}

DEFAULT_TEMPLATE = [
    {
        "title": "Incomplete reporting / missing context",
        "explanation": "The available information is insufficient to determine the cause of the difference.",
        "assumptions": ["The reports are not exhaustive."],
        "missing_information": ["Additional context for the conflicting statements."],
    }
]


class HypothesisGenerator(BaseAgent):
    name = "Hypothesis Generator"
    responsibility = "Propose competing, evidence-linked explanations for each conflict."
    required_inputs = ["open conflicts with no hypotheses yet", "the two conflicting claims for each"]
    expected_outputs = [
        "competing hypotheses (proposed, with assumptions and missing information)",
        "seed evidence referencing the conflicting claims",
    ]
    run_conditions = [
        "an in-scope conflict is open and has no hypotheses",
    ]
    stop_conditions = [
        "every open conflict already has at least one hypothesis",
    ]

    def _conflicts_needing_hypotheses(self, bb, ctx) -> list[Conflict]:
        conflicts = bb.conflicts(ids=ctx.conflict_ids or None)
        return [c for c in conflicts if c.status in ("open",) and not bb.hypotheses(c.id)]

    def candidates(self, bb, ctx: AgentContext) -> list[Action]:
        conflicts = self._conflicts_needing_hypotheses(bb, ctx)
        if not conflicts:
            return []
        actions = []
        for c in conflicts:
            actions.append(
                Action(
                    agent_name=self.name,
                    objective=f"Generate hypotheses for conflict {c.id}",
                    conflict_id=c.id,
                    severity=c.severity,
                    uncertainty=0.7,
                    evidence_gap=0.7,
                    info_gain=0.75,
                    cost=0.08,
                    reason="Conflict has no competing explanations yet.",
                    payload={"conflict_id": c.id},
                )
            )
        return actions

    def run(self, bb, ctx: AgentContext, action: Action) -> AgentResult:
        conflict = bb.db.get(Conflict, action.conflict_id)
        if conflict is None:
            return AgentResult(
                status="skipped",
                action="generate_hypotheses",
                output_summary="Conflict not found.",
                input_record_ids=[action.conflict_id] if action.conflict_id else [],
            )

        claim_a = bb.db.get(Claim, conflict.claim_a_id)
        claim_b = bb.db.get(Claim, conflict.claim_b_id)

        seeds, llm_used = self._propose(bb, ctx, conflict, claim_a, claim_b)

        created_ids = []
        events = []

        # Seed direct evidence from the two conflicting claims (provenance preserved).
        seeded_evidence = []
        for claim, label in ((claim_a, "Claim A"), (claim_b, "Claim B")):
            if claim is None:
                continue
            ev = self._find_evidence(bb, conflict.id, claim.claim_text)
            if ev is None:
                ev = create_evidence(
                    bb.db,
                    conflict_id=conflict.id,
                    description=f"{label} states: \"{claim.claim_text}\"",
                    evidence_type="measurement" if claim.claim_type == "measurement" else "document_statement",
                    origin="document",
                    document_id=claim.document_id,
                    claim_id=claim.id,
                    source_reference=claim.source_reference,
                    source_location=claim.source_location,
                    relevance_score=0.6,
                    directness=0.85,
                    investigation_id=ctx.investigation_id,
                    actor="agent",
                )
            seeded_evidence.append(ev)

        for tmpl in seeds:
            origin = tmpl.get("origin", "agent")
            hyp = bb.add_hypothesis(
                conflict_id=conflict.id,
                title=tmpl["title"],
                explanation=tmpl["explanation"],
                assumptions=json.dumps(tmpl.get("assumptions", [])),
                missing_information=json.dumps(tmpl.get("missing_information", [])),
                confidence=0.3,
                support_score=0.5,
                status=enums.HypothesisStatus.PROPOSED.value,
                origin=origin,
            )
            created_ids.append(hyp.id)
            audit_service.record(
                bb.db,
                entity_type="hypothesis",
                entity_id=hyp.id,
                action="created",
                actor=origin,
                investigation_id=ctx.investigation_id,
                conflict_id=conflict.id,
                summary=(
                    f"{'AI-suggested' if origin == 'llm' else 'Proposed'} hypothesis "
                    f"'{hyp.title}' for conflict {conflict.id}."
                ),
                detail={
                    "assumptions": tmpl.get("assumptions", []),
                    "missing_information": tmpl.get("missing_information", []),
                    "origin": origin,
                    "grounded_quotes": tmpl.get("grounded_quotes", []),
                },
            )
            events.append(
                {
                    "event_type": enums.EventType.HYPOTHESIS_GENERATED.value,
                    "payload": {
                        "conflict_id": conflict.id,
                        "hypothesis_id": hyp.id,
                        "title": hyp.title,
                    },
                }
            )

        # The seeded claim evidence establishes that the readings disagree and
        # preserves their provenance, but it is deliberately NOT attributed to
        # any single cause hypothesis: a raw disagreement does not by itself
        # support one explanation over another. Competing hypotheses must earn
        # support from separately gathered, contextual evidence.
        conflict.status = enums.ConflictStatus.INVESTIGATING.value
        return AgentResult(
            action="generate_hypotheses",
            conflict_id=conflict.id,
            input_summary=f"Conflict {conflict.id} ({conflict.conflict_type})",
            output_summary=(
                f"Proposed {len(created_ids)} competing hypotheses"
                + (" (AI-assisted, validated against the claims)." if llm_used else ".")
            ),
            changes={"hypotheses_added": len(created_ids), "evidence_added": len(seeded_evidence)},
            events=events,
            input_record_ids=[conflict.id],
            output_record_ids=sorted(set(created_ids) | {ev.id for ev in seeded_evidence}),
        )

    def _propose(self, bb, ctx, conflict, claim_a, claim_b) -> tuple[list[dict], bool]:
        """Return hypotheses to create and whether validated LLM output was used.

        LLM suggestions are only accepted when structurally sound; any supporting
        quote that is not present verbatim in the conflicting claims is dropped so
        the model cannot fabricate evidence. On any failure we fall back to the
        deterministic templates, preserving explainable behaviour.
        """
        if ctx.enable_llm and claim_a is not None and claim_b is not None:
            from ..services.llm_service import is_grounded, llm_service

            sources = [claim_a.claim_text, claim_b.claim_text]
            suggestions = llm_service.generate_hypotheses(
                claim_a.claim_text, claim_b.claim_text, conflict.conflict_type
            )
            proposed: list[dict] = []
            for s in suggestions:
                title = (s.title or "").strip()
                if not title:
                    continue
                grounded = [q for q in s.supporting_quotes if is_grounded(q, sources)]
                explanation = (s.explanation or "").strip()
                if grounded:
                    explanation = (
                        f"{explanation} Supporting excerpt(s) from the claims: "
                        + " ".join(f"\"{q}\"" for q in grounded[:2])
                    )
                proposed.append(
                    {
                        "title": title,
                        "explanation": explanation,
                        "assumptions": [a for a in s.assumptions if a],
                        "missing_information": [m for m in s.missing_information if m],
                        "origin": "llm",
                        "grounded_quotes": grounded,
                    }
                )
            if proposed:
                return proposed, True

        templates = TEMPLATES.get(conflict.conflict_type, DEFAULT_TEMPLATE)
        return [{**t, "origin": "agent"} for t in templates], False

    @staticmethod
    def _find_evidence(bb, conflict_id: int, marker: str):
        from ..models import Evidence

        for ev in bb.db.query(Evidence).filter(Evidence.conflict_id == conflict_id).all():
            if marker and marker in ev.description:
                return ev
        return None
