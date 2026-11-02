"""Schemas for claim-level fact verification.

Every field mirrors a value computed by
:mod:`app.services.fact_verification_service`. Evidence items are deliberately
modeled rather than free-form dictionaries so the frontend contract is explicit
and the API documentation shows exactly what a citation contains.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class SourceLocation(BaseModel):
    """Where a piece of evidence was found.

    ``page`` is ``None`` for non-paginated formats (TXT/DOCX); ``char_start`` and
    ``char_end`` then identify the exact character range inside the stored text.
    """

    document_id: int | None = None
    document_filename: str | None = None
    page: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    text_location: str = ""
    snippet: str = ""
    link: str | None = None


class VerificationEvidenceItem(BaseModel):
    kind: str  # claim | evidence | document
    record_id: int | None = None
    relation: str  # supports | contradicts | neutral
    reason: str = ""
    text: str = ""
    independence: str = ""  # independent | same_source | user_supplied | inferred
    source: SourceLocation
    timestamp_value: datetime | None = None


class FactVerificationOut(BaseModel):
    claim_id: int | None = None
    claim_text: str
    subject: str = ""
    predicate: str = ""
    object_value: str = ""
    numeric_value: float | None = None
    unit: str = ""
    polarity: str = "affirmative"
    claim_type: str = "statement"
    timestamp_value: datetime | None = None
    claim_confidence: float = 0.0
    document_id: int | None = None
    document_filename: str | None = None
    source: SourceLocation
    verdict: str
    verdict_label: str
    confidence: float = 0.0
    summary: str = ""
    explanation: str = ""
    supporting_evidence: list[VerificationEvidenceItem] = []
    contradicting_evidence: list[VerificationEvidenceItem] = []
    neutral_evidence: list[VerificationEvidenceItem] = []
    missing_information: list[str] = []
    documents_considered: int = 0
    claims_compared: int = 0
    stored_evidence_considered: int = 0
    method: str = "deterministic"
    methodology: str = ""
    caveat: str = ""
    analysis_notes: list[str] = []
    analyzed_at: datetime | None = None


class VerdictBreakdown(BaseModel):
    supported: int = 0
    contradicted: int = 0
    partially_supported: int = 0
    unverified: int = 0


class FactVerificationList(BaseModel):
    items: list[FactVerificationOut]
    total: int
    page: int
    page_size: int
    counts: VerdictBreakdown
    documents_considered: int = 0
    investigation_id: int | None = None
    investigation_name: str | None = None
    methodology: str = ""
    caveat: str = ""


class FactVerificationSummary(BaseModel):
    total_claims: int
    counts: VerdictBreakdown
    documents_considered: int = 0
    claims_with_contradictions: int = 0
    claims_missing_context: int = 0
    methodology: str = ""
    caveat: str = ""
