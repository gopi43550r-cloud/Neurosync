"""Audit trail model.

Every important change to the blackboard (claims, evidence, hypotheses,
verification results, conclusions, conflicts and human-review decisions) is
recorded here as an immutable, timestamped audit entry. This is separate from the
per-agent activity log: activity records *what an agent did and why*, whereas the
audit trail records *what changed on the blackboard* and who changed it.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_investigation_id_created_at", "investigation_id", "created_at"),
        Index("ix_audit_events_conflict_id_created_at", "conflict_id", "created_at"),
        Index("ix_audit_events_entity_lookup", "entity_type", "action", "entity_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    investigation_id: Mapped[int | None] = mapped_column(
        ForeignKey("investigations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    conflict_id: Mapped[int | None] = mapped_column(
        ForeignKey("conflicts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    entity_type: Mapped[str] = mapped_column(String(40), index=True)
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(60), index=True)
    actor: Mapped[str] = mapped_column(String(80), default="system")
    summary: Mapped[str] = mapped_column(Text, default="")
    detail: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
