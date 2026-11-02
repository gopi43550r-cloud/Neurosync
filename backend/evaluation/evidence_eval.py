"""Evidence-sufficiency and conclusion-traceability evaluation.

Two independent measurements, both driven by production components:

1. Evidence sufficiency (``run_evidence_evaluation``): materialises real
   Conflict/Hypothesis/Evidence rows for each labeled scenario and scores the
   hypothesis with ``app.services.scoring_service.score_hypothesis``. This
   measures whether the transparent scoring decides correctly that a conclusion
   has (or lacks) sufficient supporting evidence.

2. Conclusion traceability (``run_traceability_evaluation``): runs the shipped
   Machine M-17 demonstration through the real blackboard controller in
   deterministic mode and checks that every conclusion references the conflict,
   the underlying claims and (for supported/tentative decisions) the specific
   supporting evidence -- and never cites evidence that does not exist.
"""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.models import (
    Claim,
    Conclusion,
    Conflict,
    Document,
    Evidence,
    Hypothesis,
    Investigation,
)
from app.services.evidence_service import create_evidence
from app.services.scoring_service import score_hypothesis

from .metrics import compute_status_accuracy


def _make_documents(db: Session, count: int) -> list[Document]:
    docs = []
    for i in range(max(1, count)):
        d = Document(
            filename=f"evidence_eval_doc_{i}.txt",
            stored_filename=f"evidence_eval_doc_{i}.txt",
            file_type="txt",
            content_type="text/plain",
            checksum=f"evidence-eval-{i}",
            status="processed",
        )
        db.add(d)
        db.flush()
        docs.append(d)
    return docs


def _make_claims(db: Session, document_id: int) -> tuple[Claim, Claim]:
    a = Claim(document_id=document_id, claim_text="eval claim a", subject="temperature",
              predicate="measured_value", claim_type="measurement", numeric_value=90.0, unit="°C")
    b = Claim(document_id=document_id, claim_text="eval claim b", subject="temperature",
              predicate="measured_value", claim_type="measurement", numeric_value=40.0, unit="°C")
    db.add_all([a, b])
    db.flush()
    return a, b


def _create_evidence_item(
    db: Session,
    conflict_id: int,
    hypothesis_id: int,
    spec: dict,
    docs: list[Document],
    supports: bool,
) -> Evidence:
    doc = docs[spec.get("document_index", 0) % len(docs)]
    return create_evidence(
        db,
        conflict_id=conflict_id,
        description=f"{'supporting' if supports else 'contradicting'} evidence ({spec.get('evidence_type')})",
        evidence_type=spec.get("evidence_type", "contextual"),
        origin=spec.get("origin", "document"),
        document_id=doc.id,
        claim_id=None,
        relevance_score=spec.get("relevance"),
        reliability_score=spec.get("reliability"),
        directness=spec.get("directness", 0.5),
        supports_hypothesis_id=hypothesis_id if supports else None,
        contradicts_hypothesis_id=None if supports else hypothesis_id,
        actor="evaluation",
        dedupe=False,
    )


def run_evidence_evaluation(db: Session, dataset: dict) -> dict:
    results: list[dict] = []
    expected: list[str] = []
    predicted: list[str] = []

    for scenario in dataset["scenarios"]:
        docs = _make_documents(db, scenario.get("documents", 1))
        claim_a, claim_b = _make_claims(db, docs[0].id)
        conflict = Conflict(
            claim_a_id=claim_a.id,
            claim_b_id=claim_b.id,
            conflict_type="numerical_disagreement",
            description=f"evaluation conflict ({scenario['id']})",
            severity="medium",
            status="investigating",
        )
        db.add(conflict)
        db.flush()
        hyp = Hypothesis(
            conflict_id=conflict.id,
            title=f"eval hypothesis ({scenario['id']})",
            explanation="evaluation-only hypothesis",
            confidence=0.3,
            support_score=0.5,
            status="proposed",
        )
        db.add(hyp)
        db.flush()

        actual_support_ids = []
        actual_contradict_ids = []
        for spec in scenario.get("supporting", []):
            ev = _create_evidence_item(db, conflict.id, hyp.id, spec, docs, supports=True)
            actual_support_ids.append(ev.id)
        for spec in scenario.get("contradicting", []):
            ev = _create_evidence_item(db, conflict.id, hyp.id, spec, docs, supports=False)
            actual_contradict_ids.append(ev.id)

        score = score_hypothesis(db, hyp)
        status = score.status

        partition_correct = (
            set(score.supporting_ids) == set(actual_support_ids)
            and set(score.contradicting_ids) == set(actual_contradict_ids)
        )

        expected.append(scenario["expected_status"])
        predicted.append(status)
        results.append(
            {
                "id": scenario["id"],
                "category": scenario["category"],
                "description": scenario["description"],
                "expected_status": scenario["expected_status"],
                "predicted_status": status,
                "correct": scenario["expected_status"] == status,
                "support_score": score.support_score,
                "confidence": score.confidence,
                "distinct_sources": score.distinct_sources,
                "supporting_count": len(actual_support_ids),
                "contradicting_count": len(actual_contradict_ids),
                "supporting_weight": score.supporting_weight,
                "contradicting_weight": score.contradicting_weight,
                "has_direct_evidence": score.has_direct_evidence,
                "partition_correct": partition_correct,
                "scoring_explanation": score.explanation,
                "rationale": scenario["rationale"],
            }
        )

    accuracy = compute_status_accuracy(expected, predicted)
    partition_rate = (
        round(sum(1 for r in results if r["partition_correct"]) / len(results), 4)
        if results
        else None
    )
    return {
        "dataset": {
            "name": dataset["name"],
            "version": dataset["version"],
            "num_scenarios": len(results),
        },
        "accuracy": accuracy,
        "partition_traceability_rate": partition_rate,
        "scenarios": results,
    }


def run_traceability_evaluation(db: Session) -> dict:
    """Run the demo investigation and audit conclusion -> conflict -> claim ->
    evidence links. Deterministic mode (no LLM)."""
    from app.blackboard.controller import InvestigationControl, InvestigationController
    from app.demo import scenario

    _docs, inv_id = scenario.load_demo(db, auto_start=False)
    InvestigationController(db).run(inv_id, InvestigationControl())
    db.expire_all()

    conclusions = db.query(Conclusion).filter(Conclusion.investigation_id == inv_id).all()

    details = []
    for conc in conclusions:
        conflict = db.get(Conflict, conc.conflict_id) if conc.conflict_id else None
        conflict_linked = conflict is not None
        claim_a = db.get(Claim, conflict.claim_a_id) if conflict else None
        claim_b = db.get(Claim, conflict.claim_b_id) if conflict else None
        claims_traceable = bool(claim_a and claim_b)

        try:
            supporting_ids = json.loads(conc.supporting_evidence_ids or "[]")
        except (json.JSONDecodeError, TypeError):
            supporting_ids = []
        evidence_objs = [db.get(Evidence, i) for i in supporting_ids]
        support_ids_exist = all(e is not None for e in evidence_objs)
        support_ids_belong = all(
            e is not None and e.conflict_id == conc.conflict_id for e in evidence_objs
        )
        requires_support = conc.decision_type in ("supported_conclusion", "tentative_conclusion")
        support_sufficient = (not requires_support) or len(supporting_ids) > 0

        fully_traceable = (
            conflict_linked
            and claims_traceable
            and support_ids_exist
            and support_ids_belong
            and support_sufficient
        )
        details.append(
            {
                "conclusion_id": conc.id,
                "conflict_id": conc.conflict_id,
                "decision_type": conc.decision_type,
                "conflict_linked": conflict_linked,
                "claims_traceable": claims_traceable,
                "supporting_evidence_ids": supporting_ids,
                "support_ids_exist": support_ids_exist,
                "support_ids_belong_to_conflict": support_ids_belong,
                "requires_explicit_support": requires_support,
                "support_sufficient": support_sufficient,
                "fully_traceable": fully_traceable,
                "references_conflict_claims": claims_traceable,
            }
        )

    total = len(details)
    fully = sum(1 for d in details if d["fully_traceable"])
    return {
        "investigation_id": inv_id,
        "conclusions_total": total,
        "fully_traceable": fully,
        "traceability_rate": round(fully / total, 4) if total else None,
        "conclusions_linked_to_conflict": sum(1 for d in details if d["conflict_linked"]),
        "conclusions_linked_to_claims": sum(1 for d in details if d["claims_traceable"]),
        "decisions": sorted({d["decision_type"] for d in details}),
        "conclusions": details,
    }
