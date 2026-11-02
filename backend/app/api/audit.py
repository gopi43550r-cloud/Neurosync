"""Audit-trail endpoints.

Exposes the append-only history of changes made to the blackboard: claims,
evidence, hypotheses, verifications, conflicts, conclusions and human reviews.
Every entry is timestamped and attributed to an actor (agent or human).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas.audit import AuditEventOut
from ..schemas.common import Page
from ..services import audit_service

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_model=Page[AuditEventOut])
def list_audit_events(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=200),
    entity_type: str | None = Query(default=None),
    entity_id: int | None = Query(default=None),
    investigation_id: int | None = Query(default=None),
    conflict_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> Page[AuditEventOut]:
    filters = dict(
        entity_type=entity_type,
        entity_id=entity_id,
        investigation_id=investigation_id,
        conflict_id=conflict_id,
    )
    total = audit_service.count_events(db, **filters)
    events = audit_service.list_events(
        db,
        offset=(page - 1) * page_size,
        limit=page_size,
        **filters,
    )
    return Page(
        items=[AuditEventOut.model_validate(e) for e in events],
        total=total,
        page=page,
        page_size=page_size,
    )
