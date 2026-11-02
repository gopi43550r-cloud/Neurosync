"""Hypothesis endpoints."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Conflict, Hypothesis, enums
from ..schemas.common import Page
from ..schemas.hypothesis import HypothesisCreate, HypothesisOut
from ..services.serialization import hypothesis_to_out
from .pagination import paginate

router = APIRouter(tags=["hypotheses"])


@router.get("/conflicts/{conflict_id}/hypotheses", response_model=list[HypothesisOut])
def list_conflict_hypotheses(conflict_id: int, db: Session = Depends(get_db)) -> list[HypothesisOut]:
    if db.get(Conflict, conflict_id) is None:
        raise HTTPException(status_code=404, detail="Conflict not found.")
    items = db.query(Hypothesis).filter(Hypothesis.conflict_id == conflict_id).order_by(Hypothesis.id).all()
    return [hypothesis_to_out(h) for h in items]


@router.post("/conflicts/{conflict_id}/hypotheses", response_model=HypothesisOut, status_code=201)
def create_hypothesis(
    conflict_id: int, payload: HypothesisCreate, db: Session = Depends(get_db)
) -> HypothesisOut:
    if db.get(Conflict, conflict_id) is None:
        raise HTTPException(status_code=404, detail="Conflict not found.")
    if len(payload.title) > 300:
        raise HTTPException(status_code=422, detail="Hypothesis title is too long.")
    hyp = Hypothesis(
        conflict_id=conflict_id,
        title=payload.title,
        explanation=payload.explanation,
        assumptions=json.dumps(payload.assumptions),
        missing_information=json.dumps(payload.missing_information),
        confidence=0.3,
        support_score=0.5,
        status=enums.HypothesisStatus.PROPOSED.value,
        origin="user",
    )
    db.add(hyp)
    db.commit()
    db.refresh(hyp)
    return hypothesis_to_out(hyp)


@router.get("/hypotheses", response_model=Page[HypothesisOut])
def list_hypotheses(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    conflict_id: int | None = None,
    status: str | None = None,
    q: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> Page[HypothesisOut]:
    stmt = select(Hypothesis).order_by(Hypothesis.id.desc())
    if conflict_id is not None:
        stmt = stmt.where(Hypothesis.conflict_id == conflict_id)
    if status:
        stmt = stmt.where(Hypothesis.status == status)
    if q:
        stmt = stmt.where(Hypothesis.title.ilike(f"%{q}%"))
    items, total = paginate(db, stmt, page, page_size)
    return Page(
        items=[hypothesis_to_out(h) for h in items],
        total=total,
        page=page,
        page_size=page_size,
    )


class HypothesisReview(BaseModel):
    action: str  # "flag_for_investigation" | "human_review"
    note: str = ""


@router.patch("/hypotheses/{hypothesis_id}", response_model=HypothesisOut)
def review_hypothesis(
    hypothesis_id: int, payload: HypothesisReview, db: Session = Depends(get_db)
) -> HypothesisOut:
    hyp = db.get(Hypothesis, hypothesis_id)
    if hyp is None:
        raise HTTPException(status_code=404, detail="Hypothesis not found.")
    if payload.action == "flag_for_investigation":
        hyp.status = enums.HypothesisStatus.REVIEW_REQUIRED.value
    elif payload.action == "human_review":
        # A human review decision is explicitly recorded as such.
        hyp.status = enums.HypothesisStatus.HUMAN_REVIEWED.value
        hyp.origin = "human_review"
    else:
        raise HTTPException(status_code=422, detail="Unsupported action.")
    db.commit()
    db.refresh(hyp)
    return hypothesis_to_out(hyp)
