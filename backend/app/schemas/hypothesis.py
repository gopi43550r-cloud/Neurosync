"""Hypothesis schemas."""
from __future__ import annotations

import json
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from .common import ORMModel


def _json_list(v):
    if isinstance(v, str):
        try:
            return json.loads(v or "[]")
        except json.JSONDecodeError:
            return []
    return v or []


class HypothesisOut(ORMModel):
    id: int
    conflict_id: int
    title: str
    explanation: str = ""
    supporting_evidence_ids: list[int] = []
    contradicting_evidence_ids: list[int] = []
    assumptions: list[str] = []
    missing_information: list[str] = []
    confidence: float = 0.3
    support_score: float = 0.0
    status: str
    origin: str = "agent"
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator(
        "supporting_evidence_ids",
        "contradicting_evidence_ids",
        "assumptions",
        "missing_information",
        mode="before",
    )
    @classmethod
    def _parse_lists(cls, v):
        return _json_list(v)


class HypothesisCreate(BaseModel):
    title: str = Field(min_length=1)
    explanation: str = ""
    assumptions: list[str] = []
    missing_information: list[str] = []


class RankingEvidence(BaseModel):
    id: int
    evidence_type: str
    origin: str
    description: str
    source_reference: str = ""
    document_filename: str | None = None
    verification_status: str
    weight: float


class RankingCriteria(BaseModel):
    supporting_evidence_weight: float
    contradicting_evidence_weight: float
    distinct_supporting_sources: int
    has_direct_supporting_evidence: bool
    supporting_evidence_count: int
    contradicting_evidence_count: int


class HypothesisRanking(BaseModel):
    hypothesis_id: int
    conflict_id: int
    rank: int
    title: str
    explanation: str = ""
    status: str
    support_score: float
    confidence: float
    confidence_caveat: str = ""
    criteria: RankingCriteria
    assumptions: list[str] = []
    missing_information: list[str] = []
    supporting_evidence: list[RankingEvidence] = []
    contradicting_evidence: list[RankingEvidence] = []
    ranking_explanation: str = ""
    margin_to_next: float | None = None
