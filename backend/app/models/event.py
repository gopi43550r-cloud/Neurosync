"""Persistent event log used for the real-time SSE stream and replay."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EventLog(Base):
    __tablename__ = "event_log"
    __table_args__ = (
        Index("ix_event_log_investigation_id_id", "investigation_id", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    investigation_id: Mapped[int | None] = mapped_column(
        ForeignKey("investigations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    event_type: Mapped[str] = mapped_column(String(60), index=True)
    # Intelligence layer: which agent caused the event and which blackboard
    # record it concerns, plus a JSON array of related record references
    # (``[{"type": "evidence", "id": 7}, ...]``). All nullable so the columns
    # can be added to an existing SQLite database additively.
    agent_name: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    entity_type: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    related: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    # Set once the intelligence layer has consumed the event, so an event is
    # never processed twice (idempotent event-driven reasoning).
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
