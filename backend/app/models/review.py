"""Human review model.

Records a person's decision about an automated conclusion: approve it, reject it,
or request further investigation. The decision and its timestamp are stored so the
review history is fully auditable and never overwritten.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class HumanReview(Base):
    __tablename__ = "human_reviews"
    __table_args__ = (
        Index("ix_human_reviews_investigation_id_created_at", "investigation_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    conclusion_id: Mapped[int | None] = mapped_column(
        ForeignKey("conclusions.id", ondelete="CASCADE"), nullable=True, index=True
    )
    conflict_id: Mapped[int | None] = mapped_column(
        ForeignKey("conflicts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    investigation_id: Mapped[int | None] = mapped_column(
        ForeignKey("investigations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    decision: Mapped[str] = mapped_column(String(40), index=True)
    reviewer: Mapped[str] = mapped_column(String(120), default="human reviewer")
    note: Mapped[str] = mapped_column(Text, default="")
    previous_decision_type: Mapped[str] = mapped_column(String(40), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
