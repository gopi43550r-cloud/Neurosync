"""Audit-trail service.

A single, low-friction entry point for recording timestamped, immutable audit
entries whenever the blackboard changes. Callers never need to manage the
transaction: entries are flushed onto the current session so they commit (or roll
back) together with the change they describe.
"""
from __future__ import annotations

import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import AuditEvent


def count_events(
    db: Session,
    *,
    entity_type: str | None = None,
    entity_id: int | None = None,
    investigation_id: int | None = None,
    conflict_id: int | None = None,
) -> int:
    stmt = select(func.count()).select_from(AuditEvent)
    if entity_type:
        stmt = stmt.where(AuditEvent.entity_type == entity_type)
    if entity_id is not None:
        stmt = stmt.where(AuditEvent.entity_id == entity_id)
    if investigation_id is not None:
        stmt = stmt.where(AuditEvent.investigation_id == investigation_id)
    if conflict_id is not None:
        stmt = stmt.where(AuditEvent.conflict_id == conflict_id)
    return int(db.execute(stmt).scalar() or 0)


def record(
    db: Session,
    *,
    entity_type: str,
    action: str,
    entity_id: int | None = None,
    summary: str = "",
    actor: str = "system",
    detail: dict | None = None,
    investigation_id: int | None = None,
    conflict_id: int | None = None,
) -> AuditEvent:
    """Append an audit entry describing a change to a blackboard entity."""
    event = AuditEvent(
        investigation_id=investigation_id,
        conflict_id=conflict_id,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        actor=actor,
        summary=summary[:1000],
        detail=json.dumps(detail or {}, default=str),
    )
    db.add(event)
    db.flush()
    return event


def list_events(
    db: Session,
    *,
    entity_type: str | None = None,
    entity_id: int | None = None,
    investigation_id: int | None = None,
    conflict_id: int | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> list[AuditEvent]:
    stmt = select(AuditEvent).order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
    if entity_type:
        stmt = stmt.where(AuditEvent.entity_type == entity_type)
    if entity_id is not None:
        stmt = stmt.where(AuditEvent.entity_id == entity_id)
    if investigation_id is not None:
        stmt = stmt.where(AuditEvent.investigation_id == investigation_id)
    if conflict_id is not None:
        stmt = stmt.where(AuditEvent.conflict_id == conflict_id)
    if offset:
        stmt = stmt.offset(offset)
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(db.execute(stmt).scalars())
