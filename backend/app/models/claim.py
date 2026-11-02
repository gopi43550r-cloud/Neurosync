"""Observation and Claim models.

Observations are raw extracted facts from documents. Claims are structured
assertions derived from observations that agents can reason about.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Observation(Base):
    __tablename__ = "observations"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    observation_type: Mapped[str] = mapped_column(String(50), default="statement")
    source_location: Mapped[str] = mapped_column(String(200), default="")
    extracted_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    extraction_method: Mapped[str] = mapped_column(String(50), default="rule_based")
    meta: Mapped[str] = mapped_column("metadata", Text, default="{}")

    document: Mapped["Document"] = relationship(  # noqa: F821
        back_populates="observations"
    )
    claims: Mapped[list["Claim"]] = relationship(
        back_populates="observation", cascade="all, delete-orphan"
    )


class Claim(Base):
    __tablename__ = "claims"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    observation_id: Mapped[int | None] = mapped_column(
        ForeignKey("observations.id", ondelete="SET NULL"), nullable=True
    )
    claim_text: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[str] = mapped_column(String(200), default="", index=True)
    predicate: Mapped[str] = mapped_column(String(120), default="", index=True)
    object_value: Mapped[str] = mapped_column(String(300), default="")
    numeric_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str] = mapped_column(String(40), default="")
    polarity: Mapped[str] = mapped_column(String(20), default="affirmative")
    claim_type: Mapped[str] = mapped_column(String(40), default="statement", index=True)
    timestamp_value: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    source_reference: Mapped[str] = mapped_column(String(300), default="")
    source_location: Mapped[str] = mapped_column(String(200), default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.6)
    meta: Mapped[str] = mapped_column("metadata", Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    document: Mapped["Document"] = relationship()  # noqa: F821
    observation: Mapped[Observation | None] = relationship(back_populates="claims")
