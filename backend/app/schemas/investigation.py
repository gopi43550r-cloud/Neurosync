"""Investigation, activity and report schemas."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from .common import ORMModel


class InvestigationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    research_question: str = ""
    document_ids: list[int] = []
    conflict_ids: list[int] = []
    iteration_limit: int = Field(default=25, ge=1, le=200)
    min_evidence_threshold: int = Field(default=1, ge=0, le=50)
    enable_llm: bool = True


class InvestigationUpdate(BaseModel):
    name: str | None = None
    research_question: str | None = None
    iteration_limit: int | None = Field(default=None, ge=1, le=200)
    min_evidence_threshold: int | None = Field(default=None, ge=0, le=50)
    enable_llm: bool | None = None


class InvestigationOut(ORMModel):
    id: int
    name: str
    research_question: str = ""
    status: str
    iteration_limit: int
    min_evidence_threshold: int
    enable_llm: bool = False
    iteration_count: int = 0
    current_objective: str = ""
    current_agent: str = ""
    current_priority: float = 0.0
    current_info_gain: float = 0.0
    stop_reason: str = ""
    is_demo: bool = False
    error_message: str = ""
    created_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    updated_at: datetime | None = None
    document_count: int = 0
    conflict_count: int = 0
    open_conflict_count: int = 0
    evidence_count: int = 0
    conclusion_count: int = 0


class InvestigationListOut(InvestigationOut):
    pass


class ActivityOut(ORMModel):
    id: int
    investigation_id: int | None = None
    conflict_id: int | None = None
    agent_name: str
    action: str = ""
    input_summary: str = ""
    output_summary: str = ""
    reason: str = ""
    blackboard_changes: dict[str, Any] = {}
    status: str = "success"
    duration_ms: int = 0
    sequence: int = 0
    attempt: int = 1
    input_record_ids: list[int] = []
    output_record_ids: list[int] = []
    error: str = ""
    state_summary: str = ""
    created_at: datetime | None = None

    @field_validator("blackboard_changes", mode="before")
    @classmethod
    def _parse(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v or "{}")
            except json.JSONDecodeError:
                return {}
        return v or {}

    @field_validator("input_record_ids", "output_record_ids", mode="before")
    @classmethod
    def _parse_ids(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            try:
                parsed = json.loads(v or "[]")
            except json.JSONDecodeError:
                return []
            return parsed if isinstance(parsed, list) else []
        return v


class AgentStatusOut(BaseModel):
    name: str
    responsibility: str
    status: str
    last_action: str = ""
    tasks_completed: int = 0
    last_duration_ms: int = 0
    recent_result: str = ""
    required_inputs: list[str] = []
    expected_outputs: list[str] = []
    run_conditions: list[str] = []
    stop_conditions: list[str] = []


class ReportSection(BaseModel):
    heading: str
    body: str = ""
    items: list[str] = []


class ReportOut(BaseModel):
    investigation_id: int
    title: str
    objective: str
    generated_at: datetime
    sections: list[ReportSection]
    markdown: str
    json_data: dict[str, Any]
    stopping_reason: str
    confidence: float
    confidence_explanation: str
    warnings: list[str] = []
    schema_version: int = 2
