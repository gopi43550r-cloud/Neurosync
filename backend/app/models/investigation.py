"""Investigation, association tables and final conclusion models."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    Boolean,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


investigation_documents = Table(
    "investigation_documents",
    Base.metadata,
    Column("investigation_id", ForeignKey("investigations.id", ondelete="CASCADE"), primary_key=True),
    Column("document_id", ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True),
)

investigation_conflicts = Table(
    "investigation_conflicts",
    Base.metadata,
    Column("investigation_id", ForeignKey("investigations.id", ondelete="CASCADE"), primary_key=True),
    Column("conflict_id", ForeignKey("conflicts.id", ondelete="CASCADE"), primary_key=True),
)


class Investigation(Base):
    __tablename__ = "investigations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    research_question: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(30), default="created", index=True)
    iteration_limit: Mapped[int] = mapped_column(Integer, default=25)
    min_evidence_threshold: Mapped[int] = mapped_column(Integer, default=1)
    enable_llm: Mapped[bool] = mapped_column(Boolean, default=True)
    iteration_count: Mapped[int] = mapped_column(Integer, default=0)
    current_objective: Mapped[str] = mapped_column(Text, default="")
    current_agent: Mapped[str] = mapped_column(String(80), default="")
    current_priority: Mapped[float] = mapped_column(Float, default=0.0)
    current_info_gain: Mapped[float] = mapped_column(Float, default=0.0)
    stop_reason: Mapped[str] = mapped_column(String(60), default="")
    is_demo: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, index=True)

    documents: Mapped[list["Document"]] = relationship(  # noqa: F821
        secondary=investigation_documents
    )
    conflicts: Mapped[list["Conflict"]] = relationship(  # noqa: F821
        secondary=investigation_conflicts
    )
    conclusions: Mapped[list["Conclusion"]] = relationship(
        back_populates="investigation", cascade="all, delete-orphan"
    )


class Conclusion(Base):
    __tablename__ = "conclusions"
    __table_args__ = (
        Index("ix_conclusions_investigation_id_id", "investigation_id", "id"),
        Index("ix_conclusions_conflict_id_id", "conflict_id", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    investigation_id: Mapped[int | None] = mapped_column(
        ForeignKey("investigations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    conflict_id: Mapped[int | None] = mapped_column(
        ForeignKey("conflicts.id", ondelete="CASCADE"), nullable=True, index=True
    )
    decision_type: Mapped[str] = mapped_column(String(40), default="inconclusive")
    conclusion: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    supporting_evidence_ids: Mapped[str] = mapped_column(Text, default="[]")
    unresolved_questions: Mapped[str] = mapped_column(Text, default="[]")
    limitations: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    # Set when an event-driven re-evaluation replaces this conclusion. The old
    # row is retained (never deleted) so the reasoning history stays auditable.
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    superseded_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    investigation: Mapped[Investigation | None] = relationship(back_populates="conclusions")
