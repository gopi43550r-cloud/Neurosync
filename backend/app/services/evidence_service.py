"""Evidence service helpers: creation and provenance-aware listing."""
from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Document, Evidence
from . import audit_service
from .scoring_service import EVIDENCE_TYPE_RELIABILITY, ORIGIN_RELIABILITY


def create_evidence(
    db: Session,
    conflict_id: int,
    description: str,
    evidence_type: str = "contextual",
    origin: str = "document",
    document_id: int | None = None,
    claim_id: int | None = None,
    source_reference: str = "",
    source_location: str = "",
    relevance_score: float | None = None,
    reliability_score: float | None = None,
    directness: float = 0.5,
    supports_hypothesis_id: int | None = None,
    contradicts_hypothesis_id: int | None = None,
    verification_status: str = "unverified",
    meta: dict | None = None,
    investigation_id: int | None = None,
    actor: str = "system",
    dedupe: bool = True,
) -> Evidence:
    # Consistency guarantee: the same evidence (same conflict, same normalised
    # description, same type) is never added twice. Callers that intentionally
    # create structurally near-identical evidential items (e.g. the evaluation
    # harness) can opt out with ``dedupe=False``.
    if dedupe:
        from .consistency_service import find_duplicate_evidence

        duplicate = find_duplicate_evidence(
            db,
            conflict_id=conflict_id,
            description=description,
            evidence_type=evidence_type,
        )
        if duplicate is not None:
            return duplicate

    rel = reliability_score
    if rel is None:
        rel = EVIDENCE_TYPE_RELIABILITY.get(evidence_type, ORIGIN_RELIABILITY.get(origin, 0.5))
    relevance = relevance_score if relevance_score is not None else 0.5
    ev = Evidence(
        conflict_id=conflict_id,
        claim_id=claim_id,
        document_id=document_id,
        evidence_type=evidence_type,
        origin=origin,
        description=description,
        source_reference=source_reference,
        source_location=source_location,
        supports_hypothesis_id=supports_hypothesis_id,
        contradicts_hypothesis_id=contradicts_hypothesis_id,
        relevance_score=relevance,
        reliability_score=rel,
        directness=directness,
        verification_status=verification_status,
        meta=json.dumps(meta or {}),
    )
    db.add(ev)
    db.flush()
    audit_service.record(
        db,
        entity_type="evidence",
        entity_id=ev.id,
        action="created",
        actor=actor,
        investigation_id=investigation_id,
        conflict_id=conflict_id,
        summary=f"[{evidence_type}] {description[:200]}",
        detail={
            "origin": origin,
            "document_id": document_id,
            "supports_hypothesis_id": supports_hypothesis_id,
            "contradicts_hypothesis_id": contradicts_hypothesis_id,
            "relevance_score": relevance,
            "reliability_score": rel,
            "directness": directness,
        },
    )
    return ev


def list_evidence(db: Session, conflict_id: int | None = None) -> list[Evidence]:
    stmt = select(Evidence).order_by(Evidence.id)
    if conflict_id is not None:
        stmt = stmt.where(Evidence.conflict_id == conflict_id)
    return list(db.execute(stmt).scalars())


def evidence_document_name(db: Session, evidence: Evidence) -> str | None:
    if not evidence.document_id:
        return None
    doc = db.get(Document, evidence.document_id)
    return doc.filename if doc else None
