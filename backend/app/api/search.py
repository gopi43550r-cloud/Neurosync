"""Application-wide search across blackboard entities."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Claim, Conflict, Document, Evidence, Hypothesis, Investigation

router = APIRouter(prefix="/search", tags=["search"])


@router.get("")
def search(
    q: str = Query(min_length=1, max_length=200),
    limit: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict:
    like = f"%{q}%"

    documents = list(
        db.execute(select(Document).where(Document.filename.ilike(like)).limit(limit)).scalars()
    )
    claims = list(
        db.execute(select(Claim).where(Claim.claim_text.ilike(like)).limit(limit)).scalars()
    )
    conflicts = list(
        db.execute(select(Conflict).where(Conflict.description.ilike(like)).limit(limit)).scalars()
    )
    evidence = list(
        db.execute(select(Evidence).where(Evidence.description.ilike(like)).limit(limit)).scalars()
    )
    hypotheses = list(
        db.execute(select(Hypothesis).where(Hypothesis.title.ilike(like)).limit(limit)).scalars()
    )
    investigations = list(
        db.execute(select(Investigation).where(Investigation.name.ilike(like)).limit(limit)).scalars()
    )

    return {
        "query": q,
        "documents": [{"id": d.id, "label": d.filename} for d in documents],
        "claims": [{"id": c.id, "label": c.claim_text[:120]} for c in claims],
        "conflicts": [{"id": c.id, "label": c.description[:120]} for c in conflicts],
        "evidence": [{"id": e.id, "label": e.description[:120]} for e in evidence],
        "hypotheses": [{"id": h.id, "label": h.title} for h in hypotheses],
        "investigations": [{"id": i.id, "label": i.name} for i in investigations],
    }
