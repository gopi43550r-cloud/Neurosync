"""Evidence model: material that supports or contradicts hypotheses."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Evidence(Base):
    __tablename__ = "evidence"
    __table_args__ = (
        Index("ix_evidence_conflict_id_id", "conflict_id", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    conflict_id: Mapped[int] = mapped_column(
        ForeignKey("conflicts.id", ondelete="CASCADE"), index=True
    )
    claim_id: Mapped[int | None] = mapped_column(
        ForeignKey("claims.id", ondelete="SET NULL"), nullable=True, index=True
    )
    document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    evidence_type: Mapped[str] = mapped_column(String(40), default="contextual", index=True)
    origin: Mapped[str] = mapped_column(String(20), default="document", index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    source_reference: Mapped[str] = mapped_column(String(300), default="")
    source_location: Mapped[str] = mapped_column(String(200), default="")
    supports_hypothesis_id: Mapped[int | None] = mapped_column(
        ForeignKey("hypotheses.id", ondelete="SET NULL"), nullable=True, index=True
    )
    contradicts_hypothesis_id: Mapped[int | None] = mapped_column(
        ForeignKey("hypotheses.id", ondelete="SET NULL"), nullable=True, index=True
    )
    relevance_score: Mapped[float] = mapped_column(Float, default=0.5)
    reliability_score: Mapped[float] = mapped_column(Float, default=0.5)
    directness: Mapped[float] = mapped_column(Float, default=0.5)
    verification_status: Mapped[str] = mapped_column(String(30), default="unverified", index=True)
    meta: Mapped[str] = mapped_column("metadata", Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    conflict: Mapped["Conflict"] = relationship(back_populates="evidence")  # noqa: F821
