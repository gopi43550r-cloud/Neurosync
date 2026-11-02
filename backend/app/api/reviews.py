"""Human-review endpoints.

Records explicit human decisions on conclusions and exposes the review history.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas.common import Page
from ..schemas.review import HumanReviewCreate, HumanReviewOut, ReviewResultOut
from ..services import review_service

router = APIRouter(tags=["reviews"])


@router.post(
    "/conclusions/{conclusion_id}/review",
    response_model=ReviewResultOut,
    status_code=201,
)
def create_review(
    conclusion_id: int, payload: HumanReviewCreate, db: Session = Depends(get_db)
) -> ReviewResultOut:
    try:
        result = review_service.submit_review(
            db,
            conclusion_id=conclusion_id,
            decision=payload.decision,
            reviewer=payload.reviewer,
            note=payload.note,
        )
    except review_service.ReviewError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ReviewResultOut(
        review=HumanReviewOut.model_validate(result["review"]),
        conflict_status=result["conflict_status"],
        conclusion_decision_type=result["conclusion_decision_type"],
        message=result["message"],
    )


@router.get("/conclusions/{conclusion_id}/reviews", response_model=list[HumanReviewOut])
def list_conclusion_reviews(
    conclusion_id: int, db: Session = Depends(get_db)
) -> list[HumanReviewOut]:
    reviews = review_service.list_reviews(db, conclusion_id=conclusion_id)
    return [HumanReviewOut.model_validate(r) for r in reviews]


@router.get("/conflicts/{conflict_id}/reviews", response_model=list[HumanReviewOut])
def list_conflict_reviews(
    conflict_id: int, db: Session = Depends(get_db)
) -> list[HumanReviewOut]:
    reviews = review_service.list_reviews(db, conflict_id=conflict_id)
    return [HumanReviewOut.model_validate(r) for r in reviews]


@router.get("/reviews", response_model=Page[HumanReviewOut])
def list_reviews(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    investigation_id: int | None = None,
    db: Session = Depends(get_db),
) -> Page[HumanReviewOut]:
    total = review_service.count_reviews(db, investigation_id=investigation_id)
    reviews = review_service.list_reviews(
        db,
        investigation_id=investigation_id,
        offset=(page - 1) * page_size,
        limit=page_size,
    )
    return Page(
        items=[HumanReviewOut.model_validate(r) for r in reviews],
        total=total,
        page=page,
        page_size=page_size,
    )
