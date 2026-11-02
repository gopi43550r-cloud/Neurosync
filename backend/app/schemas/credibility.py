"""Schemas for the source-credibility analyzer.

Every field is produced by :mod:`app.services.source_credibility_service` from
records already stored in NeuroSync. Factor scores are optional: ``None`` means
the necessary information is not stored and must never be rendered as a zero.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class CredibilityFactorOut(BaseModel):
    key: str
    label: str
    status: str  # recorded | partial | unknown | not_applicable | inconsistent
    score: float | None = None
    summary: str = ""
    explanation: str = ""
    inputs: list[str] = []
    missing: list[str] = []


class CredibilityEvidenceOut(BaseModel):
    """One real cross-source comparison behind the consistency factor."""

    relation: str  # supporting | contradicting
    claim_id: int | None = None
    claim_text: str = ""
    other_document_id: int | None = None
    other_document_filename: str | None = None
    text: str = ""
    reason: str = ""
    independence: str = ""


class ConsistencyOut(BaseModel):
    status: str  # consistent | mixed | inconsistent | unknown | not_applicable
    score: float | None = None
    claims_checked: int = 0
    supported: int = 0
    contradicted: int = 0
    partially_supported: int = 0
    unverified: int = 0
    explanation: str = ""
    supporting: list[CredibilityEvidenceOut] = []
    contradicting: list[CredibilityEvidenceOut] = []


class SourceMetadataOut(BaseModel):
    """Values actually recorded for the source, plus the untouched metadata."""

    author: str | None = None
    organization: str | None = None
    publication_date: str | None = None
    publication_date_raw: str | None = None
    publication_date_precision: str | None = None
    source_type: str | None = None
    identifiers: list[str] = []
    version: str | None = None
    signature: str | None = None
    fields: dict[str, str] = {}
    raw: dict = {}


class SourceCredibilityOut(BaseModel):
    document_id: int
    filename: str
    file_type: str
    file_size: int = 0
    status: str
    is_demo: bool = False
    uploaded_at: datetime | None = None
    processed_at: datetime | None = None
    checksum: str = ""
    stored_file_present: bool = False
    stored_file_size: int | None = None
    content_available: bool = False
    char_count: int = 0
    claim_count: int = 0
    observation_count: int = 0
    evidence_count: int = 0
    source_metadata: SourceMetadataOut
    overall_label: str
    overall_label_display: str
    overall_score: float | None = None
    coverage: float = 0.0
    summary: str = ""
    explanation: str = ""
    factors: dict[str, CredibilityFactorOut] = {}
    unknown_factors: list[str] = []
    warnings: list[str] = []
    missing_information: list[str] = []
    consistency: ConsistencyOut
    methodology: str = ""
    caveat: str = ""
    analyzed_at: datetime | None = None


class CredibilityCounts(BaseModel):
    well_documented: int = 0
    partially_documented: int = 0
    limited_documentation: int = 0
    unverifiable: int = 0
    unknown_author: int = 0
    unknown_organization: int = 0
    unknown_publication_date: int = 0
    with_consistency_conflicts: int = 0
    demonstration_sources: int = 0


class SourceCredibilityList(BaseModel):
    items: list[SourceCredibilityOut]
    total: int
    page: int
    page_size: int
    counts: CredibilityCounts
    documents_considered: int = 0
    investigation_id: int | None = None
    investigation_name: str | None = None
    methodology: str = ""
    caveat: str = ""
