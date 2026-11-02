"""Advanced Blackboard Intelligence models.

Two additive tables power the intelligence layer:

* ``BlackboardRelation`` - a first-class, queryable edge between any two
  blackboard records (document/observation/claim/conflict/evidence/hypothesis/
  conclusion/investigation). It records *why* two records are connected and
  which agent was responsible, which is what makes lineage traceable.
* ``ReevaluationTask`` - a small, durable agenda of pending re-evaluations.
  Meaningful events enqueue tasks scoped to the affected conflict so new
  evidence re-opens only the relevant reasoning, not every agent.

Both tables are brand new, so ``Base.metadata.create_all`` creates them without
touching existing data.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BlackboardRelation(Base):
    """A typed, agent-attributed relationship between two blackboard records."""

    __tablename__ = "blackboard_relations"
    __table_args__ = (
        UniqueConstraint(
            "source_type",
            "source_id",
            "target_type",
            "target_id",
            "relation_type",
            name="uq_blackboard_relation",
        ),
        Index("ix_bb_relation_source", "source_type", "source_id"),
        Index("ix_bb_relation_target", "target_type", "target_id"),
        Index("ix_bb_relation_investigation_id_id", "investigation_id", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    investigation_id: Mapped[int | None] = mapped_column(
        ForeignKey("investigations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    source_type: Mapped[str] = mapped_column(String(40))
    source_id: Mapped[int] = mapped_column(Integer)
    target_type: Mapped[str] = mapped_column(String(40))
    target_id: Mapped[int] = mapped_column(Integer)
    relation_type: Mapped[str] = mapped_column(String(40), index=True)
    agent_name: Mapped[str] = mapped_column(String(80), default="")
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class ReevaluationTask(Base):
    """A pending, conflict-scoped re-evaluation request (event-driven agenda)."""

    __tablename__ = "reevaluation_tasks"
    __table_args__ = (
        Index("ix_reeval_pending", "investigation_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    investigation_id: Mapped[int | None] = mapped_column(
        ForeignKey("investigations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    conflict_id: Mapped[int | None] = mapped_column(
        ForeignKey("conflicts.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # detect | hypothesize | investigate | verify | decide
    kind: Mapped[str] = mapped_column(String(30), default="verify", index=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    trigger_event_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    detail: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
