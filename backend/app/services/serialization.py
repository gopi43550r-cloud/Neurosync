"""Serialization helpers converting ORM objects into API schemas.

The single-object helpers are used by detail endpoints. The ``*_to_out`` batch
helpers (plural) assemble a whole page of results with a constant number of
queries, which removes the N+1 pattern that made list endpoints issue one query
per row.
"""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    AgentActivity,
    Claim,
    Conclusion,
    Conflict,
    Document,
    DocumentContent,
    Evidence,
    Hypothesis,
    Investigation,
)
from ..models.investigation import investigation_conflicts, investigation_documents
from ..schemas.claim import ClaimOut
from ..schemas.conflict import ConflictOut
from ..schemas.document import DocumentDetail, DocumentOut
from ..schemas.evidence import EvidenceOut
from ..schemas.hypothesis import HypothesisOut
from ..schemas.investigation import ActivityOut, InvestigationOut
from .document_service import document_stats, document_stats_map
from .assessment_service import assess_many

_OPEN_CONFLICT_STATUSES = ("open", "investigating", "human_review")


# ------------------------------------------------------------------- documents
def _document_to_out(doc: Document, stats: dict[str, int]) -> DocumentOut:
    return DocumentOut(
        id=doc.id,
        filename=doc.filename,
        file_type=doc.file_type,
        content_type=doc.content_type,
        file_size=doc.file_size,
        status=doc.status,
        error_message=doc.error_message,
        is_demo=bool(doc.is_demo),
        uploaded_at=doc.uploaded_at,
        processed_at=doc.processed_at,
        source_metadata=doc.source_metadata,
        **stats,
    )


def document_to_out(db: Session, doc: Document) -> DocumentOut:
    return _document_to_out(doc, document_stats(db, doc.id))


def documents_to_out(db: Session, docs: list[Document]) -> list[DocumentOut]:
    stats_map = document_stats_map(db, [d.id for d in docs])
    empty = {"claim_count": 0, "observation_count": 0, "conflict_count": 0}
    return [_document_to_out(d, stats_map.get(d.id, empty)) for d in docs]


def document_to_detail(db: Session, doc: Document) -> DocumentDetail:
    base = document_to_out(db, doc)
    content = db.query(DocumentContent).filter(DocumentContent.document_id == doc.id).first()
    text = content.text if content else ""
    return DocumentDetail(
        **base.model_dump(),
        text_preview=text[:2000],
        char_count=content.char_count if content else 0,
    )


# ---------------------------------------------------------------------- claims
def _claim_to_out(claim: Claim, filename: str | None) -> ClaimOut:
    out = ClaimOut.model_validate(claim)
    out.document_filename = filename
    return out


def claim_to_out(db: Session, claim: Claim) -> ClaimOut:
    doc = db.get(Document, claim.document_id)
    return _claim_to_out(claim, doc.filename if doc else None)


def claims_to_out(db: Session, claims: list[Claim]) -> list[ClaimOut]:
    doc_ids = {c.document_id for c in claims if c.document_id}
    filenames: dict[int, str] = {}
    if doc_ids:
        filenames = dict(
            db.execute(select(Document.id, Document.filename).where(Document.id.in_(doc_ids))).all()
        )
    return [_claim_to_out(c, filenames.get(c.document_id)) for c in claims]


# ------------------------------------------------------------------- conflicts
def _conflict_to_out(
    conflict: Conflict,
    *,
    doc_a: str | None,
    doc_b: str | None,
    evidence_count: int,
    hypothesis_count: int,
) -> ConflictOut:
    return ConflictOut.model_validate(conflict).model_copy(
        update={
            "document_a": doc_a,
            "document_b": doc_b,
            "evidence_count": evidence_count,
            "hypothesis_count": hypothesis_count,
        }
    )


def conflicts_to_out(db: Session, conflicts: list[Conflict]) -> list[ConflictOut]:
    if not conflicts:
        return []
    conflict_ids = [c.id for c in conflicts]

    evidence_counts = dict(
        db.execute(
            select(Evidence.conflict_id, func.count())
            .where(Evidence.conflict_id.in_(conflict_ids))
            .group_by(Evidence.conflict_id)
        ).all()
    )
    hypothesis_counts = dict(
        db.execute(
            select(Hypothesis.conflict_id, func.count())
            .where(Hypothesis.conflict_id.in_(conflict_ids))
            .group_by(Hypothesis.conflict_id)
        ).all()
    )

    claim_ids = set()
    for c in conflicts:
        claim_ids.add(c.claim_a_id)
        claim_ids.add(c.claim_b_id)
    claim_doc = dict(
        db.execute(select(Claim.id, Claim.document_id).where(Claim.id.in_(claim_ids))).all()
    )
    doc_ids = set(claim_doc.values())
    filenames = dict(
        db.execute(select(Document.id, Document.filename).where(Document.id.in_(doc_ids))).all()
    )

    results: list[ConflictOut] = []
    for c in conflicts:
        doc_a = filenames.get(claim_doc.get(c.claim_a_id))
        doc_b = filenames.get(claim_doc.get(c.claim_b_id))
        results.append(
            _conflict_to_out(
                c,
                doc_a=doc_a,
                doc_b=doc_b,
                evidence_count=int(evidence_counts.get(c.id, 0)),
                hypothesis_count=int(hypothesis_counts.get(c.id, 0)),
            )
        )
    return results


def conflict_to_out(db: Session, conflict: Conflict) -> ConflictOut:
    return conflicts_to_out(db, [conflict])[0]


# -------------------------------------------------------------------- evidence
def _evidence_to_out(ev: Evidence, filename: str | None, assessment: dict | None) -> EvidenceOut:
    return EvidenceOut.model_validate(ev).model_copy(
        update={"document_filename": filename, "assessment": assessment}
    )


def evidence_to_out(db: Session, ev: Evidence) -> EvidenceOut:
    doc = db.get(Document, ev.document_id) if ev.document_id else None
    assessment = assess_many(db, [ev]).get(ev.id)
    return _evidence_to_out(ev, doc.filename if doc else None, assessment)


def evidence_list_to_out(db: Session, evidence_list: list[Evidence]) -> list[EvidenceOut]:
    if not evidence_list:
        return []
    doc_ids = {e.document_id for e in evidence_list if e.document_id}
    filenames = (
        dict(db.execute(select(Document.id, Document.filename).where(Document.id.in_(doc_ids))).all())
        if doc_ids
        else {}
    )
    assessments = assess_many(db, evidence_list)
    return [
        _evidence_to_out(e, filenames.get(e.document_id), assessments.get(e.id))
        for e in evidence_list
    ]


# ----------------------------------------------------------------- hypotheses
def hypothesis_to_out(hyp: Hypothesis) -> HypothesisOut:
    return HypothesisOut.model_validate(hyp)


# ------------------------------------------------------------------ activities
def activity_to_out(activity: AgentActivity) -> ActivityOut:
    return ActivityOut.model_validate(activity)


# -------------------------------------------------------------- investigations
def _investigation_stats_map(
    db: Session, investigations: list[Investigation]
) -> dict[int, dict[str, int]]:
    ids = [inv.id for inv in investigations]
    stats: dict[int, dict[str, int]] = {
        i: {
            "document_count": 0,
            "conflict_count": 0,
            "open_conflict_count": 0,
            "evidence_count": 0,
            "conclusion_count": 0,
        }
        for i in ids
    }
    if not ids:
        return stats

    doc_counts = dict(
        db.execute(
            select(investigation_documents.c.investigation_id, func.count())
            .where(investigation_documents.c.investigation_id.in_(ids))
            .group_by(investigation_documents.c.investigation_id)
        ).all()
    )

    conflict_rows = db.execute(
        select(investigation_conflicts.c.investigation_id, Conflict.id, Conflict.status)
        .join(Conflict, Conflict.id == investigation_conflicts.c.conflict_id)
        .where(investigation_conflicts.c.investigation_id.in_(ids))
    ).all()
    conflict_to_invs: dict[int, list[int]] = defaultdict(list)
    for inv_id, conflict_id, status in conflict_rows:
        stats[inv_id]["conflict_count"] += 1
        if status in _OPEN_CONFLICT_STATUSES:
            stats[inv_id]["open_conflict_count"] += 1
        conflict_to_invs[conflict_id].append(inv_id)

    all_conflict_ids = list(conflict_to_invs)
    if all_conflict_ids:
        ev_counts = dict(
            db.execute(
                select(Evidence.conflict_id, func.count())
                .where(Evidence.conflict_id.in_(all_conflict_ids))
                .group_by(Evidence.conflict_id)
            ).all()
        )
        for conflict_id, inv_ids in conflict_to_invs.items():
            count = int(ev_counts.get(conflict_id, 0))
            for inv_id in inv_ids:
                stats[inv_id]["evidence_count"] += count

    conclusion_counts = dict(
        db.execute(
            select(Conclusion.investigation_id, func.count())
            .where(Conclusion.investigation_id.in_(ids))
            .group_by(Conclusion.investigation_id)
        ).all()
    )

    for inv_id in ids:
        stats[inv_id]["document_count"] = int(doc_counts.get(inv_id, 0))
        stats[inv_id]["conclusion_count"] = int(conclusion_counts.get(inv_id, 0))
    return stats


def investigations_to_out(
    db: Session, investigations: list[Investigation]
) -> list[InvestigationOut]:
    stats_map = _investigation_stats_map(db, investigations)
    return [
        InvestigationOut.model_validate(inv).model_copy(update=stats_map[inv.id])
        for inv in investigations
    ]


def investigation_to_out(db: Session, inv: Investigation) -> InvestigationOut:
    return investigations_to_out(db, [inv])[0]
