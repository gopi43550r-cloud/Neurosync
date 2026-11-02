"""Conflict schemas."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, field_validator

from .claim import ClaimOut
from .common import ORMModel


class ConflictBase(ORMModel):
    id: int
    claim_a_id: int
    claim_b_id: int
    conflict_type: str
    description: str = ""
    severity: str
    detection_method: str = ""
    confidence: float = 0.5
    status: str
    resolution_summary: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ConflictOut(ConflictBase):
    document_a: str | None = None
    document_b: str | None = None
    evidence_count: int = 0
    hypothesis_count: int = 0


class ConflictDetail(ConflictOut):
    claim_a: ClaimOut | None = None
    claim_b: ClaimOut | None = None
    evidence: list[dict[str, Any]] = []
    hypotheses: list[dict[str, Any]] = []
    investigations: list[dict[str, Any]] = []
    conclusion: dict[str, Any] | None = None
    why_flagged: str = ""


class ConflictUpdate(BaseModel):
    status: str | None = None
    severity: str | None = None
    resolution_summary: str | None = None


class ConflictSeverityBucket(BaseModel):
    severity: str
    count: int
