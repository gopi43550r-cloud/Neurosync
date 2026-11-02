"""Conflict endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Claim, Conclusion, Conflict, Evidence, Hypothesis, enums
from ..schemas.common import Page
from ..schemas.conflict import ConflictDetail, ConflictOut, ConflictUpdate
from ..schemas.hypothesis import HypothesisRanking
from ..services import ranking_service
from ..services.serialization import (
    claim_to_out,
    conflict_to_out,
    conflicts_to_out,
    evidence_to_out,
    hypothesis_to_out,
)
from .pagination import paginate

router = APIRouter(prefix="/conflicts", tags=["conflicts"])

WHY_FLAGGED = {
    "direct_contradiction": "Two sources make directly opposed assertions about the same subject.",
    "numerical_disagreement": "The same quantity is reported with different values and no distinguishing context.",
    "temporal_inconsistency": "Values differ but were measured at different times; this may reflect genuine change.",
    "source_disagreement": "Independent sources disagree about the same fact.",
    "missing_context": "The measurements cannot be compared because context (unit/time) is missing.",
    "semantic_inconsistency": "The statements describe the same subject in incompatible ways.",
}


@router.get("", response_model=Page[ConflictOut])
def list_conflicts(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    severity: str | None = None,
    conflict_type: str | None = None,
    status: str | None = None,
    document_id: int | None = None,
    min_confidence: float | None = Query(default=None, ge=0, le=1),
    max_confidence: float | None = Query(default=None, ge=0, le=1),
    q: str | None = None,
    db: Session = Depends(get_db),
) -> Page[ConflictOut]:
    stmt = select(Conflict).order_by(Conflict.updated_at.desc())
    if severity:
        stmt = stmt.where(Conflict.severity == severity)
    if conflict_type:
        stmt = stmt.where(Conflict.conflict_type == conflict_type)
    if status:
        stmt = stmt.where(Conflict.status == status)
    if min_confidence is not None:
        stmt = stmt.where(Conflict.confidence >= min_confidence)
    if max_confidence is not None:
        stmt = stmt.where(Conflict.confidence <= max_confidence)
    if q:
        stmt = stmt.where(Conflict.description.ilike(f"%{q}%"))
    if document_id is not None:
        doc_claim_ids = select(Claim.id).where(Claim.document_id == document_id)
        stmt = stmt.where(
            or_(
                Conflict.claim_a_id.in_(doc_claim_ids),
                Conflict.claim_b_id.in_(doc_claim_ids),
            )
        )

    conflicts, total = paginate(db, stmt, page, page_size)
    return Page(
        items=conflicts_to_out(db, conflicts),
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{conflict_id}", response_model=ConflictDetail)
def get_conflict(conflict_id: int, db: Session = Depends(get_db)) -> ConflictDetail:
    conflict = db.get(Conflict, conflict_id)
    if conflict is None:
        raise HTTPException(status_code=404, detail="Conflict not found.")

    base = conflict_to_out(db, conflict)
    evidence = db.query(Evidence).filter(Evidence.conflict_id == conflict_id).all()
    hypotheses = db.query(Hypothesis).filter(Hypothesis.conflict_id == conflict_id).all()
    conclusion = (
        db.query(Conclusion).filter(Conclusion.conflict_id == conflict_id).order_by(Conclusion.id.desc()).first()
    )

    investigations = []
    for inv in conflict_investigations(db, conflict_id):
        investigations.append(
            {
                "id": inv.id,
                "name": inv.name,
                "status": inv.status,
                "iteration_count": inv.iteration_count,
                "stop_reason": inv.stop_reason,
            }
        )

    return ConflictDetail(
        **base.model_dump(),
        claim_a=claim_to_out(db, conflict.claim_a) if conflict.claim_a else None,
        claim_b=claim_to_out(db, conflict.claim_b) if conflict.claim_b else None,
        evidence=[evidence_to_out(db, e).model_dump() for e in evidence],
        hypotheses=[hypothesis_to_out(h).model_dump() for h in hypotheses],
        investigations=investigations,
        conclusion=_conclusion_dict(conclusion) if conclusion else None,
        why_flagged=WHY_FLAGGED.get(conflict.conflict_type, "Potential contradiction detected."),
    )


@router.get("/{conflict_id}/hypotheses/ranking", response_model=list[HypothesisRanking])
def rank_conflict_hypotheses(
    conflict_id: int, db: Session = Depends(get_db)
) -> list[HypothesisRanking]:
    if db.get(Conflict, conflict_id) is None:
        raise HTTPException(status_code=404, detail="Conflict not found.")
    ranked = ranking_service.rank_hypotheses(db, conflict_id)
    return [HypothesisRanking.model_validate(item) for item in ranked]


@router.get("/{conflict_id}/evidence-gaps", response_model=list[str])
def conflict_evidence_gaps(conflict_id: int, db: Session = Depends(get_db)) -> list[str]:
    if db.get(Conflict, conflict_id) is None:
        raise HTTPException(status_code=404, detail="Conflict not found.")
    return ranking_service.missing_evidence(db, conflict_id)


@router.patch("/{conflict_id}", response_model=ConflictOut)
def update_conflict(
    conflict_id: int, payload: ConflictUpdate, db: Session = Depends(get_db)
) -> ConflictOut:
    conflict = db.get(Conflict, conflict_id)
    if conflict is None:
        raise HTTPException(status_code=404, detail="Conflict not found.")
    valid_status = {s.value for s in enums.ConflictStatus}
    valid_severity = {s.value for s in enums.Severity}
    if payload.status and payload.status not in valid_status:
        raise HTTPException(status_code=422, detail=f"Invalid status. Allowed: {sorted(valid_status)}")
    if payload.severity and payload.severity not in valid_severity:
        raise HTTPException(status_code=422, detail=f"Invalid severity. Allowed: {sorted(valid_severity)}")
    for key, value in payload.model_dump(exclude_none=True).items():
        setattr(conflict, key, value)
    db.commit()
    db.refresh(conflict)
    return conflict_to_out(db, conflict)


def conflict_investigations(db: Session, conflict_id: int):
    from ..models import Investigation

    return [
        inv
        for inv in db.execute(select(Investigation)).scalars()
        if any(c.id == conflict_id for c in inv.conflicts)
    ]


def _conclusion_dict(c: Conclusion) -> dict:
    import json

    def loads(v):
        try:
            return json.loads(v or "[]")
        except json.JSONDecodeError:
            return []

    return {
        "id": c.id,
        "decision_type": c.decision_type,
        "conclusion": c.conclusion,
        "confidence": c.confidence,
        "supporting_evidence_ids": loads(c.supporting_evidence_ids),
        "unresolved_questions": loads(c.unresolved_questions),
        "limitations": loads(c.limitations),
    }
