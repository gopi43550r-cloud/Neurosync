"""Agent activity model: an auditable record of every agent action."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AgentActivity(Base):
    __tablename__ = "agent_activities"
    __table_args__ = (
        Index("ix_agent_activities_investigation_id_created_at", "investigation_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    investigation_id: Mapped[int | None] = mapped_column(
        ForeignKey("investigations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    conflict_id: Mapped[int | None] = mapped_column(
        ForeignKey("conflicts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    agent_name: Mapped[str] = mapped_column(String(80), index=True)
    action: Mapped[str] = mapped_column(String(120), default="")
    input_summary: Mapped[str] = mapped_column(Text, default="")
    output_summary: Mapped[str] = mapped_column(Text, default="")
    reason: Mapped[str] = mapped_column(Text, default="")
    blackboard_changes: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(20), default="success")
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    # --- orchestration ledger -------------------------------------------
    # 1-based position of this execution in the investigation's sequence.
    sequence: Mapped[int] = mapped_column(Integer, default=0)
    # 1-based attempt number for this action (1 = first try, >1 = a retry).
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    # JSON arrays of the blackboard record ids consumed / produced.
    input_record_ids: Mapped[str] = mapped_column(Text, default="[]")
    output_record_ids: Mapped[str] = mapped_column(Text, default="[]")
    # Failure reason (exception type/message) when status == "failed".
    error: Mapped[str] = mapped_column(Text, default="")
    # Human-readable blackboard state the scheduler used to pick this action.
    state_summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
