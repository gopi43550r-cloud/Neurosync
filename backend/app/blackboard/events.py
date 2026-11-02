"""Blackboard event bus.

Events are persisted to the database so they survive restarts and can be
replayed, and are also pushed to an in-process queue for the live SSE stream.
Every event originates from an actual state change; nothing is simulated.

Each event may also carry *structured provenance*: the responsible agent, the
blackboard record it concerns and any related records. This is what lets the
intelligence layer trace "which agent did what, to which record, and why".
Callers may pass these explicitly; when omitted they are derived from the
payload, so every existing ``publish`` call becomes traceable for free.
"""
from __future__ import annotations

import json
import queue
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from ..models import EventLog

# Payload keys (in priority order) that identify the primary record an event is
# about, together with the record type they imply.
_ENTITY_KEYS: list[tuple[str, str]] = [
    ("activity_id", "agent_action"),
    ("conflict_id", "conflict"),
    ("hypothesis_id", "hypothesis"),
    ("evidence_id", "evidence"),
    ("conclusion_id", "conclusion"),
    ("claim_id", "claim"),
    ("document_id", "document"),
    ("investigation_id", "investigation"),
]

# Payload keys that are *related* records (not the primary subject).
_RELATED_KEYS: list[tuple[str, str]] = [
    ("conflict_id", "conflict"),
    ("hypothesis_id", "hypothesis"),
    ("evidence_id", "evidence"),
    ("document_id", "document"),
    ("claim_id", "claim"),
    ("conclusion_id", "conclusion"),
]


def _derive_entity(payload: dict[str, Any]) -> tuple[str | None, int | None]:
    for key, record_type in _ENTITY_KEYS:
        value = payload.get(key)
        if isinstance(value, int):
            return record_type, value
    return None, None


def _derive_related(payload: dict[str, Any], primary_type: str | None, primary_id: int | None) -> list[dict[str, Any]]:
    related: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for key, record_type in _RELATED_KEYS:
        value = payload.get(key)
        if not isinstance(value, int):
            continue
        if record_type == primary_type and value == primary_id:
            continue
        marker = (record_type, value)
        if marker in seen:
            continue
        seen.add(marker)
        related.append({"type": record_type, "id": value})
    return related


class EventBus:
    """Thread-safe in-memory fan-out of events plus persistence."""

    def __init__(self) -> None:
        self._subscribers: dict[int, list[queue.Queue]] = {}

    def publish(
        self,
        db: Session,
        investigation_id: int | None,
        event_type: str,
        payload: dict[str, Any],
        *,
        agent_name: str | None = None,
        entity_type: str | None = None,
        entity_id: int | None = None,
        related: list[dict[str, Any]] | None = None,
    ) -> EventLog:
        """Persist an event and notify live subscribers.

        ``agent_name``, ``entity_type``/``entity_id`` and ``related`` are
        optional provenance fields; when not supplied they are inferred from the
        payload so old call sites keep working.
        """
        payload = payload or {}
        if agent_name is None:
            agent_name = payload.get("agent") or payload.get("actor") or None
        derived_type, derived_id = _derive_entity(payload)
        if entity_type is None:
            entity_type = derived_type
        if entity_id is None:
            entity_id = derived_id
        if related is None:
            related = _derive_related(payload, entity_type, entity_id)

        event = EventLog(
            investigation_id=investigation_id,
            event_type=event_type,
            payload=json.dumps(payload, default=str),
            agent_name=agent_name,
            entity_type=entity_type,
            entity_id=entity_id,
            related=json.dumps(related, default=str) if related else None,
        )
        db.add(event)
        db.commit()
        db.refresh(event)

        envelope = {
            "id": event.id,
            "investigation_id": investigation_id,
            "event_type": event_type,
            "payload": payload,
            "agent_name": event.agent_name,
            "entity_type": event.entity_type,
            "entity_id": event.entity_id,
            "related": related,
            "created_at": event.created_at.replace(tzinfo=timezone.utc).isoformat(),
        }
        if investigation_id in self._subscribers:
            for q in list(self._subscribers[investigation_id]):
                try:
                    q.put_nowait(envelope)
                except queue.Full:  # pragma: no cover
                    pass
        return event

    def subscribe(self, investigation_id: int) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=1000)
        self._subscribers.setdefault(investigation_id, []).append(q)
        return q

    def unsubscribe(self, investigation_id: int, q: queue.Queue) -> None:
        subs = self._subscribers.get(investigation_id)
        if not subs:
            return
        if q in subs:
            subs.remove(q)
        if not subs:
            self._subscribers.pop(investigation_id, None)


event_bus = EventBus()
