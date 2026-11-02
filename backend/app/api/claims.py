"""Claim endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Claim
from ..schemas.claim import ClaimOut
from ..schemas.common import Page
from ..services.serialization import claim_to_out, claims_to_out
from .pagination import paginate

router = APIRouter(prefix="/claims", tags=["claims"])


@router.get("", response_model=Page[ClaimOut])
def list_claims(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    document_id: int | None = None,
    subject: str | None = None,
    claim_type: str | None = None,
    q: str | None = Query(default=None, description="Free-text search"),
    db: Session = Depends(get_db),
) -> Page[ClaimOut]:
    stmt = select(Claim).order_by(Claim.id)
    if document_id is not None:
        stmt = stmt.where(Claim.document_id == document_id)
    if subject:
        stmt = stmt.where(Claim.subject == subject)
    if claim_type:
        stmt = stmt.where(Claim.claim_type == claim_type)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Claim.claim_text.ilike(like), Claim.subject.ilike(like)))
    claims, total = paginate(db, stmt, page, page_size)
    return Page(
        items=claims_to_out(db, claims),
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{claim_id}", response_model=ClaimOut)
def get_claim(claim_id: int, db: Session = Depends(get_db)) -> ClaimOut:
    claim = db.get(Claim, claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found.")
    return claim_to_out(db, claim)
