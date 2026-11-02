"""Conflict model: potentially contradictory claims."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Conflict(Base):
    __tablename__ = "conflicts"

    id: Mapped[int] = mapped_column(primary_key=True)
    claim_a_id: Mapped[int] = mapped_column(
        ForeignKey("claims.id", ondelete="CASCADE"), index=True
    )
    claim_b_id: Mapped[int] = mapped_column(
        ForeignKey("claims.id", ondelete="CASCADE"), index=True
    )
    conflict_type: Mapped[str] = mapped_column(String(40), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    severity: Mapped[str] = mapped_column(String(20), default="medium", index=True)
    detection_method: Mapped[str] = mapped_column(String(50), default="rule_based")
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    status: Mapped[str] = mapped_column(String(30), default="open", index=True)
    resolution_summary: Mapped[str] = mapped_column(Text, default="")
    meta: Mapped[str] = mapped_column("metadata", Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    claim_a: Mapped["Claim"] = relationship(foreign_keys=[claim_a_id])  # noqa: F821
    claim_b: Mapped["Claim"] = relationship(foreign_keys=[claim_b_id])  # noqa: F821
    evidence: Mapped[list["Evidence"]] = relationship(  # noqa: F821
        back_populates="conflict", cascade="all, delete-orphan"
    )
    hypotheses: Mapped[list["Hypothesis"]] = relationship(  # noqa: F821
        back_populates="conflict", cascade="all, delete-orphan"
    )
