"""Evidence endpoints (nested under conflicts and a global explorer list)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..blackboard import event_processor
from ..blackboard.events import event_bus
from ..models import Conflict, Evidence, Hypothesis, enums
from ..schemas.common import Page
from ..schemas.evidence import EvidenceCreate, EvidenceOut
from ..services import evidence_service
from ..services.serialization import evidence_to_out, evidence_list_to_out
from .pagination import paginate

router = APIRouter(tags=["evidence"])


@router.get("/conflicts/{conflict_id}/evidence", response_model=list[EvidenceOut])
def list_conflict_evidence(conflict_id: int, db: Session = Depends(get_db)) -> list[EvidenceOut]:
    if db.get(Conflict, conflict_id) is None:
        raise HTTPException(status_code=404, detail="Conflict not found.")
    return [evidence_to_out(db, e) for e in evidence_service.list_evidence(db, conflict_id)]


@router.post("/conflicts/{conflict_id}/evidence", response_model=EvidenceOut, status_code=201)
def add_evidence(
    conflict_id: int, payload: EvidenceCreate, db: Session = Depends(get_db)
) -> EvidenceOut:
    if db.get(Conflict, conflict_id) is None:
        raise HTTPException(status_code=404, detail="Conflict not found.")
    if payload.supports_hypothesis_id and db.get(Hypothesis, payload.supports_hypothesis_id) is None:
        raise HTTPException(status_code=404, detail="Supporting hypothesis not found.")
    if payload.contradicts_hypothesis_id and db.get(Hypothesis, payload.contradicts_hypothesis_id) is None:
        raise HTTPException(status_code=404, detail="Contradicting hypothesis not found.")
    ev = evidence_service.create_evidence(
        db,
        conflict_id=conflict_id,
        description=payload.description,
        evidence_type=payload.evidence_type,
        origin="user",
        source_reference=payload.source_reference or "User-supplied",
        source_location=payload.source_location,
        relevance_score=payload.relevance_score,
        reliability_score=payload.reliability_score,
        directness=0.5,
        supports_hypothesis_id=payload.supports_hypothesis_id,
        contradicts_hypothesis_id=payload.contradicts_hypothesis_id,
        verification_status="requires_review",
    )
    db.commit()
    db.refresh(ev)
    # Intelligence layer: user-supplied evidence is a real blackboard change, so
    # record it as an event and schedule a scoped re-evaluation of just this
    # conflict (verify its hypotheses / revisit its conclusion).
    investigation_id = event_processor.resolve_investigation_id(db, conflict_id)
    event_bus.publish(
        db,
        investigation_id,
        enums.EventType.EVIDENCE_ADDED.value,
        {"evidence_id": ev.id, "conflict_id": conflict_id, "origin": "user"},
        agent_name="Evidence Collector",
        entity_type="evidence",
        entity_id=ev.id,
    )
    event_processor.process_pending_events(db, investigation_id)
    return evidence_to_out(db, ev)


@router.get("/evidence", response_model=Page[EvidenceOut])
def list_evidence(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    conflict_id: int | None = None,
    origin: str | None = None,
    evidence_type: str | None = None,
    verification_status: str | None = None,
    q: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> Page[EvidenceOut]:
    stmt = select(Evidence).order_by(Evidence.id.desc())
    if conflict_id is not None:
        stmt = stmt.where(Evidence.conflict_id == conflict_id)
    if origin:
        stmt = stmt.where(Evidence.origin == origin)
    if evidence_type:
        stmt = stmt.where(Evidence.evidence_type == evidence_type)
    if verification_status:
        stmt = stmt.where(Evidence.verification_status == verification_status)
    if q:
        stmt = stmt.where(Evidence.description.ilike(f"%{q}%"))
    items, total = paginate(db, stmt, page, page_size)
    return Page(
        items=evidence_list_to_out(db, items),
        total=total,
        page=page,
        page_size=page_size,
    )
