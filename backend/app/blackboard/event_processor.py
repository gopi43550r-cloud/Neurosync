"""Event-driven reasoning.

The processor is the bridge between "something changed on the blackboard" (an
:class:`~app.models.EventLog` row) and "which piece of reasoning now needs to be
recomputed". It is deliberately conservative:

* Only a small whitelist of *meaningful* events schedules work. Routine events
  (``iteration_completed``, ``agent_selected``, ...) are marked processed and do
  nothing.
* Work is **scoped to a single conflict** (and a single kind of reasoning), so a
  new piece of evidence re-opens the relevant hypotheses rather than re-running
  every agent.
* Enqueueing is idempotent - the same ``(conflict, kind)`` is never queued twice
  while a task is pending - and each event is marked ``processed_at`` exactly
  once, so an event is never processed repeatedly.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    Conflict,
    Evidence,
    EventLog,
    Hypothesis,
    Investigation,
    ReevaluationTask,
    investigation_conflicts,
    enums,
)
from .events import event_bus

# event_type -> ordered list of reasoning kinds it makes stale.
TRIGGERS: dict[str, list[str]] = {
    enums.EventType.EVIDENCE_ADDED.value: ["verify", "decide"],
    enums.EventType.EVIDENCE_EVALUATED.value: ["verify"],
    enums.EventType.HYPOTHESIS_UPDATED.value: ["verify", "decide"],
    enums.EventType.HYPOTHESIS_GENERATED.value: ["verify"],
    enums.EventType.HYPOTHESIS_VERIFIED.value: ["decide"],
    enums.EventType.CONFLICT_DETECTED.value: ["hypothesize"],
    enums.EventType.CLAIM_EXTRACTED.value: ["detect"],
    enums.EventType.DOCUMENT_PROCESSED.value: ["detect"],
}

TRIGGER_AGENT = "Event Processor"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _payload(event: EventLog) -> dict[str, Any]:
    try:
        return json.loads(event.payload or "{}")
    except json.JSONDecodeError:
        return {}


def resolve_investigation_id(db: Session, conflict_id: int | None) -> int | None:
    if conflict_id is None:
        return None
    row = db.execute(
        select(investigation_conflicts.c.investigation_id).where(
            investigation_conflicts.c.conflict_id == conflict_id
        )
    ).first()
    return int(row[0]) if row else None


def resolve_conflict_id(db: Session, event: EventLog) -> int | None:
    """Find the conflict an event concerns, from its structured fields."""
    if event.entity_type == "conflict" and event.entity_id:
        return event.entity_id
    if event.entity_type == "evidence" and event.entity_id:
        ev = db.get(Evidence, event.entity_id)
        if ev is not None:
            return ev.conflict_id
    if event.entity_type == "hypothesis" and event.entity_id:
        hyp = db.get(Hypothesis, event.entity_id)
        if hyp is not None:
            return hyp.conflict_id
    payload = _payload(event)
    if isinstance(payload.get("conflict_id"), int):
        return payload["conflict_id"]
    for key, model in (("hypothesis_id", Hypothesis), ("evidence_id", Evidence)):
        value = payload.get(key)
        if isinstance(value, int):
            obj = db.get(model, value)
            if obj is not None:
                return obj.conflict_id
    return None


def enqueue(
    db: Session,
    *,
    investigation_id: int | None,
    conflict_id: int | None,
    kind: str,
    reason: str,
    trigger_event_id: int | None = None,
    detail: dict[str, Any] | None = None,
) -> ReevaluationTask | None:
    """Queue a scoped re-evaluation unless an identical one is already pending."""
    existing = db.execute(
        select(ReevaluationTask).where(
            ReevaluationTask.investigation_id == investigation_id,
            ReevaluationTask.conflict_id == conflict_id,
            ReevaluationTask.kind == kind,
            ReevaluationTask.status == "pending",
        )
    ).scalars().first()
    if existing is not None:
        return None
    task = ReevaluationTask(
        investigation_id=investigation_id,
        conflict_id=conflict_id,
        kind=kind,
        reason=reason,
        trigger_event_id=trigger_event_id,
        detail=json.dumps(detail or {}),
    )
    db.add(task)
    db.flush()
    return task


def process_event(db: Session, event: EventLog) -> list[ReevaluationTask]:
    """Enqueue the reasoning work implied by a single event (idempotent)."""
    if event.processed_at is not None:
        return []
    kinds = TRIGGERS.get(event.event_type, [])
    created: list[ReevaluationTask] = []
    if kinds:
        conflict_id = resolve_conflict_id(db, event)
        investigation_id = event.investigation_id or resolve_investigation_id(db, conflict_id)
        for kind in kinds:
            task = enqueue(
                db,
                investigation_id=investigation_id,
                conflict_id=conflict_id,
                kind=kind,
                reason=(
                    f"Event '{event.event_type}' changed the blackboard; "
                    f"{kind} for conflict {conflict_id} is now stale."
                ),
                trigger_event_id=event.id,
                detail={"event_type": event.event_type, "trigger_event_id": event.id},
            )
            if task is not None:
                created.append(task)
        if created:
            event_bus.publish(
                db,
                investigation_id,
                enums.EventType.REEVALUATION_SCHEDULED.value,
                {
                    "conflict_id": conflict_id,
                    "kinds": kinds,
                    "trigger_event_id": event.id,
                    "trigger_event_type": event.event_type,
                },
                agent_name=TRIGGER_AGENT,
                entity_type="conflict" if conflict_id else None,
                entity_id=conflict_id,
            )
    event.processed_at = _now()
    db.flush()
    return created


def process_pending_events(
    db: Session,
    investigation_id: int | None = None,
    limit: int = 500,
) -> dict[str, int]:
    """Process every unprocessed event exactly once. Returns task counts."""
    stmt = select(EventLog).where(EventLog.processed_at.is_(None)).order_by(EventLog.id).limit(limit)
    if investigation_id is not None:
        stmt = select(EventLog).where(
            EventLog.processed_at.is_(None),
            EventLog.investigation_id == investigation_id,
        ).order_by(EventLog.id).limit(limit)
    events = list(db.execute(stmt).scalars())
    scheduled = 0
    for event in events:
        scheduled += len(process_event(db, event))
    db.commit()
    return {"events_processed": len(events), "tasks_scheduled": scheduled}


def pending_tasks(db: Session, investigation_id: int | None = None) -> list[ReevaluationTask]:
    stmt = select(ReevaluationTask).where(ReevaluationTask.status == "pending").order_by(ReevaluationTask.id)
    if investigation_id is not None:
        stmt = stmt.where(ReevaluationTask.investigation_id == investigation_id)
    return list(db.execute(stmt).scalars())
