"""Hypothesis model: provisional explanations for a conflict."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Hypothesis(Base):
    __tablename__ = "hypotheses"

    id: Mapped[int] = mapped_column(primary_key=True)
    conflict_id: Mapped[int] = mapped_column(
        ForeignKey("conflicts.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, default="")
    supporting_evidence_ids: Mapped[str] = mapped_column(Text, default="[]")  # JSON list
    contradicting_evidence_ids: Mapped[str] = mapped_column(Text, default="[]")  # JSON list
    assumptions: Mapped[str] = mapped_column(Text, default="[]")  # JSON list
    missing_information: Mapped[str] = mapped_column(Text, default="[]")  # JSON list
    confidence: Mapped[float] = mapped_column(Float, default=0.3)
    support_score: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(30), default="proposed", index=True)
    origin: Mapped[str] = mapped_column(String(20), default="agent")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    conflict: Mapped["Conflict"] = relationship(back_populates="hypotheses")  # noqa: F821
