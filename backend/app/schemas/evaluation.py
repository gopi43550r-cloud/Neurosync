"""Schemas for the AI evaluation and performance dashboard.

All metrics in these responses are derived from persisted ``EvaluationRun`` and
``EvaluationCaseResult`` rows. No schema exposes a hand-entered score, and every
rate with an undefined denominator is ``None`` rather than zero.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

EvaluationKind = Literal["conflict_detection", "evidence_verification"]


class EvaluationDocumentIn(BaseModel):
    filename: str = Field(min_length=1, max_length=500)
    text: str = Field(min_length=1)
    role: str = "context"


class EvaluationCaseIn(BaseModel):
    """A labelled case, accepted in the same shape for create and upload."""

    model_config = ConfigDict(populate_by_name=True)

    case_key: str = Field(
        validation_alias=AliasChoices("case_key", "id"),
        min_length=1,
        max_length=160,
    )
    category: str = Field(default="general", max_length=120)
    # Conflict-detection inputs (two short source texts).
    text_a: str = ""
    text_b: str = ""
    # Evidence-verification inputs (one target claim plus comparison sources).
    claim_text: str = ""
    documents: list[EvaluationDocumentIn] = Field(default_factory=list)
    expected: dict[str, Any]
    rationale: str = ""

    @field_validator("expected")
    @classmethod
    def _expected_not_empty(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise ValueError("expected ground truth cannot be empty")
        return value


class EvaluationDatasetIn(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    kind: EvaluationKind
    description: str = ""
    version: str = Field(default="1.0.0", max_length=40)
    cases: list[EvaluationCaseIn] = Field(min_length=1)

    @field_validator("cases")
    @classmethod
    def _unique_keys(cls, cases: list[EvaluationCaseIn]) -> list[EvaluationCaseIn]:
        keys = [case.case_key for case in cases]
        if len(set(keys)) != len(keys):
            raise ValueError("case keys must be unique within a dataset")
        return cases


class EvaluationCaseOut(BaseModel):
    id: int
    case_key: str
    category: str
    payload: dict[str, Any]
    expected: dict[str, Any]
    rationale: str
    created_at: datetime | None = None


class EvaluationRunSummaryOut(BaseModel):
    id: int
    dataset_id: int
    dataset_name: str
    kind: str
    provenance: str
    status: str
    case_count: int
    passed: int
    failed: int
    duration_ms: int
    error: str = ""
    metrics: dict[str, Any] = Field(default_factory=dict)
    confusion: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime | None = None
    completed_at: datetime | None = None


class EvaluationCaseResultOut(BaseModel):
    id: int
    case_key: str
    category: str
    expected: dict[str, Any]
    predicted: dict[str, Any]
    passed: bool
    duration_ms: int
    explanation: str = ""


class EvaluationRunOut(EvaluationRunSummaryOut):
    by_category: dict[str, Any] = Field(default_factory=dict)
    failures: list[dict[str, Any]] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)
    results: list[EvaluationCaseResultOut] = Field(default_factory=list)


class EvaluationDatasetOut(BaseModel):
    id: int
    key: str
    name: str
    description: str = ""
    kind: str
    source: str
    version: str
    is_builtin: bool
    case_count: int
    created_at: datetime | None = None
    updated_at: datetime | None = None
    latest_run: EvaluationRunSummaryOut | None = None


class EvaluationDatasetDetailOut(EvaluationDatasetOut):
    cases: list[EvaluationCaseOut] = Field(default_factory=list)


# --------------------------------------------------------------- live analytics
class AgentPerformanceOut(BaseModel):
    name: str
    responsibility: str = ""
    status: str = "idle"
    total_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    skipped_tasks: int = 0
    total_duration_ms: int = 0
    avg_duration_ms: float | None = None
    max_duration_ms: int = 0
    last_action: str = ""
    last_activity_at: datetime | None = None


class AgentPerformanceSummary(BaseModel):
    agents: list[AgentPerformanceOut] = Field(default_factory=list)
    total_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    skipped_tasks: int = 0
    avg_duration_ms: float | None = None


class DocumentAnalyticsOut(BaseModel):
    documents_total: int = 0
    documents_processed: int = 0
    documents_pending: int = 0
    documents_processing: int = 0
    documents_error: int = 0
    documents_by_status: dict[str, int] = Field(default_factory=dict)
    documents_with_timing: int = 0
    avg_processing_ms: float | None = None
    max_processing_ms: int | None = None
    total_processing_ms: int = 0
    claims_extracted: int = 0
    documents_with_claims: int = 0
    conflicts_detected: int = 0
    conflicts_resolved: int = 0
    hypotheses_total: int = 0
    evidence_total: int = 0
    investigations_total: int = 0
    investigations_by_status: dict[str, int] = Field(default_factory=dict)
    investigations_with_timing: int = 0
    avg_investigation_ms: float | None = None
    total_iterations: int = 0
    documents_by_day: list[dict[str, Any]] = Field(default_factory=list)


class EvaluationDashboardOut(BaseModel):
    generated_at: datetime
    disclaimer: str
    validation_note: str
    datasets: list[EvaluationDatasetOut] = Field(default_factory=list)
    conflict_detection: EvaluationRunOut | None = None
    evidence_verification: EvaluationRunOut | None = None
    agents: AgentPerformanceSummary = Field(default_factory=AgentPerformanceSummary)
    documents: DocumentAnalyticsOut = Field(default_factory=DocumentAnalyticsOut)
