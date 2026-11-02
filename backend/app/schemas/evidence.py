"""Evidence schemas."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from .common import ORMModel


class EvidenceOut(ORMModel):
    id: int
    conflict_id: int
    claim_id: int | None = None
    document_id: int | None = None
    evidence_type: str
    origin: str = "document"
    description: str = ""
    source_reference: str = ""
    source_location: str = ""
    supports_hypothesis_id: int | None = None
    contradicts_hypothesis_id: int | None = None
    relevance_score: float = 0.5
    reliability_score: float = 0.5
    directness: float = 0.5
    verification_status: str = "unverified"
    created_at: datetime | None = None
    document_filename: str | None = None
    assessment: dict | None = None


class EvidenceCreate(BaseModel):
    description: str = Field(min_length=1)
    evidence_type: str = "user_supplied"
    source_reference: str = ""
    source_location: str = ""
    relevance_score: float = 0.5
    reliability_score: float = 0.5
    supports_hypothesis_id: int | None = None
    contradicts_hypothesis_id: int | None = None
