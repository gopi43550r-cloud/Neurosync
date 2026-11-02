"""Explainable hypothesis ranking.

Ranks the competing hypotheses for a conflict using transparent, reproducible
criteria and exposes, for every hypothesis, the evidence that supports it, the
evidence that opposes it, its assumptions and its confidence level.

Nothing here is a probabilistic model: ``support_score`` and ``confidence`` are
bounded *support indicators* derived from documented evidence weights (see
``scoring_service``). They are never presented as calibrated probabilities.
"""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

from ..models import Document, Evidence, Hypothesis
from .scoring_service import evidence_weight, score_hypothesis

CONFIDENCE_CAVEAT = (
    "Bounded support indicator derived from evidence weights; NOT a statistically "
    "calibrated probability."
)


def _loads(value: str) -> list:
    try:
        return json.loads(value or "[]")
    except (json.JSONDecodeError, TypeError):
        return []


def _evidence_detail(db: Session, evidence: Evidence) -> dict:
    doc = db.get(Document, evidence.document_id) if evidence.document_id else None
    return {
        "id": evidence.id,
        "evidence_type": evidence.evidence_type,
        "origin": evidence.origin,
        "description": evidence.description,
        "source_reference": evidence.source_reference,
        "document_filename": doc.filename if doc else None,
        "verification_status": evidence.verification_status,
        "weight": round(evidence_weight(evidence), 3),
    }


def explain_hypothesis(db: Session, hypothesis: Hypothesis) -> dict:
    """Return a transparent, self-contained explanation of one hypothesis."""
    score = score_hypothesis(db, hypothesis)
    items = db.query(Evidence).filter(Evidence.conflict_id == hypothesis.conflict_id).all()
    supporting = [_evidence_detail(db, e) for e in items if e.id in set(score.supporting_ids)]
    contradicting = [_evidence_detail(db, e) for e in items if e.id in set(score.contradicting_ids)]

    return {
        "hypothesis_id": hypothesis.id,
        "conflict_id": hypothesis.conflict_id,
        "rank": 0,
        "title": hypothesis.title,
        "explanation": hypothesis.explanation,
        "status": hypothesis.status,
        "support_score": hypothesis.support_score,
        "confidence": hypothesis.confidence,
        "confidence_caveat": CONFIDENCE_CAVEAT,
        "criteria": {
            "supporting_evidence_weight": score.supporting_weight,
            "contradicting_evidence_weight": score.contradicting_weight,
            "distinct_supporting_sources": score.distinct_sources,
            "has_direct_supporting_evidence": score.has_direct_evidence,
            "supporting_evidence_count": len(supporting),
            "contradicting_evidence_count": len(contradicting),
        },
        "assumptions": _loads(hypothesis.assumptions),
        "missing_information": _loads(hypothesis.missing_information),
        "supporting_evidence": supporting,
        "contradicting_evidence": contradicting,
        "ranking_explanation": score.explanation,
        "margin_to_next": None,
    }


def rank_hypotheses(db: Session, conflict_id: int) -> list[dict]:
    """Rank all hypotheses for a conflict, highest support first.

    Ordering is by ``support_score`` then ``confidence`` (a deterministic
    tie-break). The margin to the next hypothesis is included so a reader can see
    whether the top explanation is clearly ahead or effectively tied.
    """
    hypotheses = (
        db.query(Hypothesis).filter(Hypothesis.conflict_id == conflict_id).all()
    )
    if not hypotheses:
        return []

    explained = [explain_hypothesis(db, h) for h in hypotheses]
    explained.sort(key=lambda x: (x["support_score"], x["confidence"]), reverse=True)

    for index, item in enumerate(explained):
        item["rank"] = index + 1
        if index + 1 < len(explained):
            item["margin_to_next"] = round(
                item["support_score"] - explained[index + 1]["support_score"], 3
            )
    return explained


def missing_evidence(db: Session, conflict_id: int) -> list[str]:
    """Consolidated list of information whose absence blocks a resolution."""
    gaps: list[str] = []
    # Explicit "missing" evidence records.
    for e in (
        db.query(Evidence)
        .filter(Evidence.conflict_id == conflict_id, Evidence.evidence_type == "missing")
        .all()
    ):
        if e.description not in gaps:
            gaps.append(e.description)
    # Information requested by each hypothesis.
    for h in db.query(Hypothesis).filter(Hypothesis.conflict_id == conflict_id).all():
        for item in _loads(h.missing_information):
            if item not in gaps:
                gaps.append(item)
    return gaps
