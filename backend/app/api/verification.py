"""Claim-level fact-verification endpoints.

The verifier is deterministic and reads the records already stored in
NeuroSync, so these endpoints never call an external search engine and never
write to the blackboard. Results are computed on demand, which means a verdict
always reflects the current documents and evidence (no stale snapshot).

Scope rules
-----------
* ``/verification/claims`` verifies every claim matching the filters, because
  accurate verdict counts and verdict-based filtering require looking at the
  whole scope. Results are then paginated in memory. This is cheap for the
  local, single-tenant datasets NeuroSync targets; ``page_size`` bounds the
  response, not the analysis.
* ``/investigations/{id}/claim-verifications`` uses exactly the documents and
  conflicts attached to that investigation.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Claim, Investigation
from ..models.enums import FactVerdict
from ..schemas.verification import (
    FactVerificationList,
    FactVerificationOut,
    FactVerificationSummary,
    VerdictBreakdown,
)
from ..services.fact_verification_service import (
    CAVEAT,
    METHODOLOGY,
    build_index,
    claims_for_investigation,
    verdict_counts,
    verify_claim,
)

router = APIRouter(tags=["verification"])

_VERDICTS = {v.value for v in FactVerdict}


def _breakdown(items: list[dict]) -> VerdictBreakdown:
    counts = verdict_counts(items)
    return VerdictBreakdown(**counts)


def _verify_all(
    db: Session, claims: list[Claim], *, use_llm: bool = False
) -> tuple[list[dict], int]:
    """Verify ``claims`` with one shared index; return results and document count."""
    index = build_index(db)
    results = [
        verify_claim(db, claim, index=index, use_llm=use_llm) for claim in claims
    ]
    return results, index.document_count


def _scoped_claims(
    db: Session,
    *,
    document_id: int | None,
    claim_type: str | None,
    q: str | None,
) -> list[Claim]:
    stmt = select(Claim).order_by(Claim.id)
    if document_id is not None:
        stmt = stmt.where(Claim.document_id == document_id)
    if claim_type:
        stmt = stmt.where(Claim.claim_type == claim_type)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Claim.claim_text.ilike(like), Claim.subject.ilike(like)))
    return list(db.execute(stmt).scalars())


@router.get("/verification/claims", response_model=FactVerificationList)
def list_claim_verifications(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    document_id: int | None = None,
    claim_type: str | None = None,
    verdict: str | None = Query(default=None, description="supported | contradicted | partially_supported | unverified"),
    q: str | None = Query(default=None, description="Free-text search over claim text and subject"),
    use_llm: bool = Query(default=False, description="Attach an AI-written rationale (verdict is never changed)"),
    db: Session = Depends(get_db),
) -> FactVerificationList:
    claims = _scoped_claims(db, document_id=document_id, claim_type=claim_type, q=q)
    results, document_count = _verify_all(db, claims, use_llm=use_llm)
    counts = _breakdown(results)

    if verdict:
        if verdict not in _VERDICTS:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown verdict '{verdict}'. Expected one of: {', '.join(sorted(_VERDICTS))}.",
            )
        results = [r for r in results if r["verdict"] == verdict]

    total = len(results)
    start = (page - 1) * page_size
    return FactVerificationList(
        items=results[start : start + page_size],
        total=total,
        page=page,
        page_size=page_size,
        counts=counts,
        documents_considered=document_count,
        methodology=METHODOLOGY,
        caveat=CAVEAT,
    )


@router.get("/verification/summary", response_model=FactVerificationSummary)
def verification_summary(
    document_id: int | None = None,
    claim_type: str | None = None,
    q: str | None = Query(default=None, description="Free-text search over claim text and subject"),
    db: Session = Depends(get_db),
) -> FactVerificationSummary:
    claims = _scoped_claims(db, document_id=document_id, claim_type=claim_type, q=q)
    results, document_count = _verify_all(db, claims)
    counts = verdict_counts(results)
    return FactVerificationSummary(
        total_claims=len(results),
        counts=VerdictBreakdown(**counts),
        documents_considered=document_count,
        claims_with_contradictions=sum(
            1 for r in results if r["contradicting_evidence"]
        ),
        claims_missing_context=sum(
            1 for r in results if r["verdict"] == FactVerdict.UNVERIFIED.value
        ),
        methodology=METHODOLOGY,
        caveat=CAVEAT,
    )


@router.get("/claims/{claim_id}/verification", response_model=FactVerificationOut)
def get_claim_verification(
    claim_id: int,
    use_llm: bool = Query(default=False, description="Attach an AI-written rationale (verdict is never changed)"),
    db: Session = Depends(get_db),
) -> FactVerificationOut:
    claim = db.get(Claim, claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found.")
    return verify_claim(db, claim, use_llm=use_llm)


@router.get(
    "/investigations/{investigation_id}/claim-verifications",
    response_model=FactVerificationList,
)
def investigation_claim_verifications(
    investigation_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    verdict: str | None = Query(default=None, description="supported | contradicted | partially_supported | unverified"),
    use_llm: bool = Query(default=False, description="Attach an AI-written rationale (verdict is never changed)"),
    db: Session = Depends(get_db),
) -> FactVerificationList:
    investigation = db.get(Investigation, investigation_id)
    if investigation is None:
        raise HTTPException(status_code=404, detail="Investigation not found.")

    claims = claims_for_investigation(db, investigation)
    results, document_count = _verify_all(db, claims, use_llm=use_llm)
    counts = _breakdown(results)

    if verdict:
        if verdict not in _VERDICTS:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown verdict '{verdict}'. Expected one of: {', '.join(sorted(_VERDICTS))}.",
            )
        results = [r for r in results if r["verdict"] == verdict]

    total = len(results)
    start = (page - 1) * page_size
    return FactVerificationList(
        items=results[start : start + page_size],
        total=total,
        page=page,
        page_size=page_size,
        counts=counts,
        documents_considered=document_count,
        investigation_id=investigation.id,
        investigation_name=investigation.name,
        methodology=METHODOLOGY,
        caveat=CAVEAT,
    )
