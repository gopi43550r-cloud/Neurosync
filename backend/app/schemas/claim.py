"""Claim and Observation schemas."""
from __future__ import annotations

from datetime import datetime

from .common import ORMModel


class ObservationOut(ORMModel):
    id: int
    document_id: int
    text: str
    observation_type: str
    source_location: str = ""
    extraction_method: str = ""
    extracted_at: datetime | None = None


class ClaimOut(ORMModel):
    id: int
    document_id: int
    observation_id: int | None = None
    claim_text: str
    subject: str = ""
    predicate: str = ""
    object_value: str = ""
    numeric_value: float | None = None
    unit: str = ""
    polarity: str = "affirmative"
    claim_type: str = "statement"
    timestamp_value: datetime | None = None
    source_reference: str = ""
    source_location: str = ""
    confidence: float = 0.6
    created_at: datetime | None = None
    document_filename: str | None = None
