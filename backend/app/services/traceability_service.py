"""Traceability service.

Answers the two explainability questions the intelligence layer must be able to
answer for any blackboard record:

* **Why was this record created or updated?**  (:func:`why`)
* **Which earlier records influenced it?** (:func:`trace`)

The answers are assembled from three real, persisted sources: the typed
relations between records, the audit trail, and the event log. Nothing is
inferred or invented - every statement is backed by a stored row.
"""
from __future__ import annotations

import json
from datetime import timezone
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..models import (
    Claim,
    Conclusion,
    Conflict,
    Document,
    EventLog,
    Evidence,
    Hypothesis,
    Investigation,
)
from ..services import audit_service
from ..services import relation_service

_MODEL = {
    "document": Document,
    "claim": Claim,
    "conflict": Conflict,
    "evidence": Evidence,
    "hypothesis": Hypothesis,
    "conclusion": Conclusion,
    "investigation": Investigation,
}


def _label(db: Session, record_type: str, record_id: int) -> str:
    model = _MODEL.get(record_type)
    record = db.get(model, record_id) if model else None
    if record is None:
        return f"{record_type} {record_id}"
    if record_type == "document":
        return record.filename
    if record_type == "claim":
        return record.claim_text[:120]
    if record_type == "conflict":
        return f"C{record.id}: {record.conflict_type}"
    if record_type == "evidence":
        return record.description[:120]
    if record_type == "hypothesis":
        return record.title
    if record_type == "conclusion":
        return f"{record.decision_type} (conf {record.confidence:.2f})"
    if record_type == "investigation":
        return record.name
    return f"{record_type} {record_id}"


def _iso(value) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def trace(db: Session, record_type: str, record_id: int, investigation_id: int | None = None) -> dict[str, Any]:
    """Return the full provenance of a record: relations, events and audit."""
    model = _MODEL.get(record_type)
    record = db.get(model, record_id) if model else None

    relations = relation_service.connected(db, record_type, record_id, investigation_id)

    event_stmt = select(EventLog).where(
        or_(
            (EventLog.entity_type == record_type) & (EventLog.entity_id == record_id),
            EventLog.related.like(f'%"type": "{record_type}", "id": {record_id}%'),
        )
    ).order_by(EventLog.id.desc()).limit(50)
    events = [
        {
            "id": e.id,
            "event_type": e.event_type,
            "agent_name": e.agent_name,
            "entity_type": e.entity_type,
            "entity_id": e.entity_id,
            "created_at": _iso(e.created_at),
        }
        for e in db.execute(event_stmt).scalars()
    ]

    audit = [
        {
            "id": a.id,
            "action": a.action,
            "actor": a.actor,
            "summary": a.summary,
            "created_at": _iso(a.created_at),
            "detail": json.loads(a.detail or "{}"),
        }
        for a in audit_service.list_events(db, entity_type=record_type, entity_id=record_id, limit=50)
    ]

    provenance = [
        {"type": r["other"]["type"], "id": r["other"]["id"], "via": r["relation_type"], "direction": r["direction"]}
        for r in relations
        if r["direction"] == "incoming"
    ]

    reasons = _reasons(record_type, record_id, relations, audit, events)
    return {
        "record": {
            "type": record_type,
            "id": record_id,
            "exists": record is not None,
            "label": _label(db, record_type, record_id),
        },
        "relations": relations,
        "events": events,
        "audit": audit,
        "influenced_by": provenance,
        "why": reasons,
    }


def why(db: Session, record_type: str, record_id: int) -> list[str]:
    """Return only the human-readable reasons a record exists in its current form."""
    return trace(db, record_type, record_id)["why"]


def _reasons(record_type, record_id, relations, audit, events) -> list[str]:
    reasons: list[str] = []
    for a in audit:
        if a["summary"]:
            actor = a["actor"] or "system"
            reasons.append(f"Audit [{a['action']}] by {actor}: {a['summary']}")
    if not reasons:
        for r in relations:
            if r["direction"] == "incoming" and r.get("reason"):
                reasons.append(f"Linked from {r['other']['type']} {r['other']['id']}: {r['reason']}")
    if not reasons:
        for e in events:
            agent = e.get("agent_name") or "system"
            reasons.append(f"Produced by event '{e['event_type']}' ({agent}).")
    if not reasons:
        reasons.append("No recorded provenance for this record yet.")
    return reasons
