"""Persistent storage for the AI evaluation and performance dashboard.

The dashboard never stores derived performance numbers directly. It stores the
*labelled test cases* and the *raw per-case outcomes* of a run; every metric is
recomputed from those rows, so a displayed score can always be traced back to
the exact prediction and human-authored expectation that produced it.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EvaluationDataset(Base):
    """A named collection of labelled evaluation cases."""

    __tablename__ = "evaluation_datasets"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Stable string key so built-in datasets can be seeded idempotently.
    key: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    # conflict_detection | evidence_verification
    kind: Mapped[str] = mapped_column(String(40), index=True)
    # reference | user
    source: Mapped[str] = mapped_column(String(20), default="user", index=True)
    version: Mapped[str] = mapped_column(String(40), default="1.0.0")
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    cases: Mapped[list["EvaluationCase"]] = relationship(
        back_populates="dataset",
        cascade="all, delete-orphan",
        order_by="EvaluationCase.id",
    )
    runs: Mapped[list["EvaluationRun"]] = relationship(
        back_populates="dataset",
        cascade="all, delete-orphan",
    )


class EvaluationCase(Base):
    """One labelled test case.

    ``payload`` holds the inputs the production pipeline consumes and
    ``expected`` holds the human-authored ground truth. Keeping them as JSON
    documents means both evaluation types can share a table without inventing
    columns that only apply to one of them.
    """

    __tablename__ = "evaluation_cases"
    __table_args__ = (
        UniqueConstraint("dataset_id", "case_key", name="uq_evaluation_cases_dataset_case"),
        Index("ix_evaluation_cases_dataset_id_category", "dataset_id", "category"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(
        ForeignKey("evaluation_datasets.id", ondelete="CASCADE"), index=True
    )
    case_key: Mapped[str] = mapped_column(String(160), nullable=False)
    category: Mapped[str] = mapped_column(String(120), default="general", index=True)
    payload: Mapped[str] = mapped_column(Text, default="{}")
    expected: Mapped[str] = mapped_column(Text, default="{}")
    rationale: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    dataset: Mapped[EvaluationDataset] = relationship(back_populates="cases")


class EvaluationRun(Base):
    """A single execution of one dataset through the production pipeline."""

    __tablename__ = "evaluation_runs"
    __table_args__ = (
        Index("ix_evaluation_runs_kind_status", "kind", "status"),
        Index("ix_evaluation_runs_dataset_id_started_at", "dataset_id", "started_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(
        ForeignKey("evaluation_datasets.id", ondelete="CASCADE"), index=True
    )
    # Snapshot so an old run stays readable even if the dataset is renamed.
    dataset_name: Mapped[str] = mapped_column(String(300), default="")
    kind: Mapped[str] = mapped_column(String(40), index=True)
    # reference_labelled | user_labelled
    provenance: Mapped[str] = mapped_column(String(40), default="user_labelled", index=True)
    status: Mapped[str] = mapped_column(String(20), default="running", index=True)
    case_count: Mapped[int] = mapped_column(Integer, default=0)
    passed: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    # JSON blobs; everything is recomputable from the per-case results below.
    metrics: Mapped[str] = mapped_column(Text, default="{}")
    confusion: Mapped[str] = mapped_column(Text, default="{}")
    by_category: Mapped[str] = mapped_column(Text, default="{}")
    failures: Mapped[str] = mapped_column(Text, default="[]")
    config: Mapped[str] = mapped_column(Text, default="{}")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    dataset: Mapped[EvaluationDataset] = relationship(back_populates="runs")
    results: Mapped[list["EvaluationCaseResult"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="EvaluationCaseResult.id",
    )


class EvaluationCaseResult(Base):
    """The expected vs predicted outcome for one case in one run."""

    __tablename__ = "evaluation_case_results"
    __table_args__ = (
        Index("ix_evaluation_case_results_run_id_passed", "run_id", "passed"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("evaluation_runs.id", ondelete="CASCADE"), index=True
    )
    case_key: Mapped[str] = mapped_column(String(160), index=True)
    category: Mapped[str] = mapped_column(String(120), default="general", index=True)
    expected: Mapped[str] = mapped_column(Text, default="{}")
    predicted: Mapped[str] = mapped_column(Text, default="{}")
    passed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    explanation: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    run: Mapped[EvaluationRun] = relationship(back_populates="results")
