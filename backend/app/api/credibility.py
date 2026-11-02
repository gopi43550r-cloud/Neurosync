"""Source-credibility endpoints.

Every response is computed on demand from stored documents, metadata, claims and
evidence. No credibility rating is stored, so a result can never go stale and
no synthetic score can be introduced by a migration or seed.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Document, Investigation
from ..schemas.credibility import (
    CredibilityCounts,
    SourceCredibilityList,
    SourceCredibilityOut,
)
from ..services.source_credibility_service import (
    CAVEAT,
    LEVEL_LABELS,
    METHODOLOGY,
    assess_many,
    assess_source,
    build_context,
    credibility_counts,
    documents_for_investigation,
)

router = APIRouter(tags=["source-credibility"])

_LEVELS = set(LEVEL_LABELS)


def _counts(items: list[dict]) -> CredibilityCounts:
    return CredibilityCounts(**credibility_counts(items))


def _filter_items(
    items: list[dict],
    *,
    level: str | None,
    unknown_only: bool,
) -> list[dict]:
    if level:
        if level not in _LEVELS:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Unknown credibility level '{level}'. Expected one of: "
                    f"{', '.join(sorted(_LEVELS))}."
                ),
            )
        items = [item for item in items if item["overall_label"] == level]
    if unknown_only:
        # "Unknown source" means the source's *identity* cannot be established,
        # or the source is too thinly documented to assess at all. A source with
        # a recorded author/organization is identified even when its publication
        # date is missing; that gap is reported separately in the factor detail.
        items = [
            item
            for item in items
            if item["overall_label"] == "unverifiable"
            or (
                not item["source_metadata"].get("author")
                and not item["source_metadata"].get("organization")
            )
        ]
    return items


@router.get("/documents/{document_id}/credibility", response_model=SourceCredibilityOut)
def get_document_credibility(
    document_id: int,
    db: Session = Depends(get_db),
) -> SourceCredibilityOut:
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return assess_source(db, document)


@router.get("/source-credibility", response_model=SourceCredibilityList)
def list_source_credibility(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    q: str | None = Query(default=None, description="Search filename and recorded metadata"),
    level: str | None = Query(
        default=None,
        description="well_documented | partially_documented | limited_documentation | unverifiable",
    ),
    unknown_only: bool = Query(
        default=False,
        description=(
            "Only sources whose identity is unknown (no author and no "
            "organization) or which are unverifiable"
        ),
    ),
    document_id: int | None = None,
    db: Session = Depends(get_db),
) -> SourceCredibilityList:
    stmt = select(Document).order_by(Document.id)
    if document_id is not None:
        stmt = stmt.where(Document.id == document_id)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                Document.filename.ilike(like),
                Document.source_metadata.ilike(like),
            )
        )
    documents = list(db.execute(stmt).scalars())
    context = build_context(db, documents)
    items = assess_many(db, documents, context=context)
    counts = _counts(items)

    filtered = _filter_items(items, level=level, unknown_only=unknown_only)
    total = len(filtered)
    start = (page - 1) * page_size
    return SourceCredibilityList(
        items=filtered[start : start + page_size],
        total=total,
        page=page,
        page_size=page_size,
        counts=counts,
        documents_considered=len(documents),
        methodology=METHODOLOGY,
        caveat=CAVEAT,
    )


@router.get(
    "/investigations/{investigation_id}/source-credibility",
    response_model=SourceCredibilityList,
)
def investigation_source_credibility(
    investigation_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    level: str | None = Query(
        default=None,
        description="well_documented | partially_documented | limited_documentation | unverifiable",
    ),
    unknown_only: bool = Query(
        default=False,
        description=(
            "Only sources whose identity is unknown (no author and no "
            "organization) or which are unverifiable"
        ),
    ),
    db: Session = Depends(get_db),
) -> SourceCredibilityList:
    investigation = db.get(Investigation, investigation_id)
    if investigation is None:
        raise HTTPException(status_code=404, detail="Investigation not found.")

    documents = documents_for_investigation(investigation)
    context = build_context(db, documents)
    items = assess_many(db, documents, context=context)
    counts = _counts(items)

    filtered = _filter_items(items, level=level, unknown_only=unknown_only)
    total = len(filtered)
    start = (page - 1) * page_size
    return SourceCredibilityList(
        items=filtered[start : start + page_size],
        total=total,
        page=page,
        page_size=page_size,
        counts=counts,
        documents_considered=len(documents),
        investigation_id=investigation.id,
        investigation_name=investigation.name,
        methodology=METHODOLOGY,
        caveat=CAVEAT,
    )
