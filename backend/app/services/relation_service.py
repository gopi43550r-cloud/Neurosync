"""Relation service: typed, agent-attributed edges between blackboard records.

The ``BlackboardRelation`` table is a first-class, queryable view of how records
relate (claim extracted from document, evidence supports hypothesis, conflict
resolved by conclusion, ...). It is derived deterministically from the current
blackboard state, so callers do not need to remember to update it: calling
:func:`sync_relations` makes the relation table consistent with the records.

Because the unique constraint on
``(source_type, source_id, target_type, target_id, relation_type)`` makes each
edge unique, syncing is idempotent and can safely run after every agent action.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    BlackboardRelation,
    Claim,
    Conclusion,
    Conflict,
    Document,
    Evidence,
    Hypothesis,
    Investigation,
)
from ..models import enums
from ..models.investigation import investigation_conflicts, investigation_documents


def _key(source_type, source_id, target_type, target_id, relation_type):
    return (source_type, int(source_id), target_type, int(target_id), relation_type)


def create_relation(
    db: Session,
    *,
    source_type: str,
    source_id: int,
    target_type: str,
    target_id: int,
    relation_type: str,
    agent_name: str = "",
    reason: str = "",
    investigation_id: int | None = None,
) -> BlackboardRelation | None:
    """Create a relation if an identical edge does not already exist."""
    existing = db.execute(
        select(BlackboardRelation.id).where(
            BlackboardRelation.source_type == source_type,
            BlackboardRelation.source_id == source_id,
            BlackboardRelation.target_type == target_type,
            BlackboardRelation.target_id == target_id,
            BlackboardRelation.relation_type == relation_type,
        )
    ).first()
    if existing is not None:
        return None
    relation = BlackboardRelation(
        investigation_id=investigation_id,
        source_type=source_type,
        source_id=source_id,
        target_type=target_type,
        target_id=target_id,
        relation_type=relation_type,
        agent_name=agent_name,
        reason=reason,
    )
    db.add(relation)
    db.flush()
    return relation


def _scope(db: Session, investigation_id: int | None) -> dict[str, Any]:
    """Resolve the records that belong to an investigation scope.

    The scoped branch filters in SQL (via the association tables and the
    conflict foreign keys) so the work is proportional to the investigation
    rather than the whole database.
    """
    if investigation_id is None:
        docs = list(db.execute(select(Document)).scalars())
        claims = list(db.execute(select(Claim)).scalars())
        conflicts = list(db.execute(select(Conflict)).scalars())
        hyps = list(db.execute(select(Hypothesis)).scalars())
        evidence = list(db.execute(select(Evidence)).scalars())
        conclusions = list(db.execute(select(Conclusion)).scalars())
        investigations = list(db.execute(select(Investigation)).scalars())
    else:
        inv = db.get(Investigation, investigation_id)
        if inv is None:
            return {"empty": True}
        conflicts = list(
            db.execute(
                select(Conflict)
                .join(investigation_conflicts, Conflict.id == investigation_conflicts.c.conflict_id)
                .where(investigation_conflicts.c.investigation_id == investigation_id)
            ).scalars()
        )
        conflict_ids = [c.id for c in conflicts]
        if conflict_ids:
            hyps = list(
                db.execute(select(Hypothesis).where(Hypothesis.conflict_id.in_(conflict_ids))).scalars()
            )
            evidence = list(
                db.execute(select(Evidence).where(Evidence.conflict_id.in_(conflict_ids))).scalars()
            )
            conclusions = list(
                db.execute(select(Conclusion).where(Conclusion.conflict_id.in_(conflict_ids))).scalars()
            )
        else:
            hyps, evidence, conclusions = [], [], []
        doc_ids = {
            row[0]
            for row in db.execute(
                select(investigation_documents.c.document_id).where(
                    investigation_documents.c.investigation_id == investigation_id
                )
            ).all()
        }
        claim_ids = set()
        for c in conflicts:
            claim_ids.add(c.claim_a_id)
            claim_ids.add(c.claim_b_id)
        claim_stmt = select(Claim)
        if doc_ids and conflict_ids:
            claim_stmt = claim_stmt.where(Claim.document_id.in_(doc_ids) | Claim.id.in_(conflict_ids[0:0] or claim_ids))
        elif doc_ids:
            claim_stmt = claim_stmt.where(Claim.document_id.in_(doc_ids))
        elif claim_ids:
            claim_stmt = claim_stmt.where(Claim.id.in_(claim_ids))
        claims = list(db.execute(claim_stmt).scalars())
        all_doc_ids = doc_ids | {c.document_id for c in claims}
        docs = (
            list(db.execute(select(Document).where(Document.id.in_(all_doc_ids))).scalars())
            if all_doc_ids
            else []
        )
        investigations = [inv]
    return {
        "documents": docs,
        "claims": claims,
        "conflicts": conflicts,
        "hypotheses": hyps,
        "evidence": evidence,
        "conclusions": conclusions,
        "investigations": investigations,
        "empty": False,
    }


def sync_relations(
    db: Session,
    investigation_id: int | None = None,
    agent_name: str = "",
) -> int:
    """Make the relation table consistent with the blackboard. Returns #created."""
    scope = _scope(db, investigation_id)
    if scope.get("empty"):
        return 0

    # Load just the uniqueness keys (not full ORM rows) — the constraint is
    # global, so this stays correct while using far less memory.
    existing = {
        (st, si, tt, ti, rt)
        for st, si, tt, ti, rt in db.execute(
            select(
                BlackboardRelation.source_type,
                BlackboardRelation.source_id,
                BlackboardRelation.target_type,
                BlackboardRelation.target_id,
                BlackboardRelation.relation_type,
            )
        ).all()
    }

    def ensure(source_type, source_id, target_type, target_id, relation_type, reason):
        marker = _key(source_type, source_id, target_type, target_id, relation_type)
        if marker in existing:
            return 0
        db.add(
            BlackboardRelation(
                investigation_id=investigation_id,
                source_type=source_type,
                source_id=source_id,
                target_type=target_type,
                target_id=target_id,
                relation_type=relation_type,
                agent_name=agent_name,
                reason=reason,
            )
        )
        existing.add(marker)
        return 1

    created = 0
    for claim in scope["claims"]:
        created += ensure(
            "claim", claim.id, "document", claim.document_id, "extracted_from",
            "Claim was extracted from this document.",
        )
    for conflict in scope["conflicts"]:
        for claim_id in (conflict.claim_a_id, conflict.claim_b_id):
            created += ensure(
                "conflict", conflict.id, "claim", claim_id, "derived_from",
                f"Conflict derived from this claim ({conflict.conflict_type}).",
            )
    for ev in scope["evidence"]:
        created += ensure(
            "conflict", ev.conflict_id, "evidence", ev.id, "has_evidence",
            "Evidence gathered for this conflict.",
        )
        if ev.supports_hypothesis_id:
            created += ensure(
                "evidence", ev.id, "hypothesis", ev.supports_hypothesis_id, "supports",
                "Evidence supports this hypothesis.",
            )
        if ev.contradicts_hypothesis_id:
            created += ensure(
                "evidence", ev.id, "hypothesis", ev.contradicts_hypothesis_id, "refutes",
                "Evidence contradicts this hypothesis.",
            )
    for hyp in scope["hypotheses"]:
        created += ensure(
            "hypothesis", hyp.id, "conflict", hyp.conflict_id, "explains",
            "Hypothesis was proposed to explain this conflict.",
        )
    for conclusion in scope["conclusions"]:
        if conclusion.conflict_id:
            created += ensure(
                "conflict", conclusion.conflict_id, "conclusion", conclusion.id, "resolved_by",
                "Conclusion was synthesised for this conflict.",
            )
    for inv in scope["investigations"]:
        for conflict in scope["conflicts"]:
            created += ensure(
                "investigation", inv.id, "conflict", conflict.id, "investigates",
                "Investigation investigates this conflict.",
            )
    if created:
        db.flush()
    return created


def relations_query(
    *,
    investigation_id: int | None = None,
    record_type: str | None = None,
    record_id: int | None = None,
    relation_type: str | None = None,
):
    """Build the (unpaginated) statement for listing relations."""
    stmt = select(BlackboardRelation).order_by(BlackboardRelation.id.desc())
    if investigation_id is not None:
        stmt = stmt.where(BlackboardRelation.investigation_id == investigation_id)
    if relation_type:
        stmt = stmt.where(BlackboardRelation.relation_type == relation_type)
    if record_type and record_id is not None:
        from sqlalchemy import and_, or_

        stmt = stmt.where(
            or_(
                and_(
                    BlackboardRelation.source_type == record_type,
                    BlackboardRelation.source_id == record_id,
                ),
                and_(
                    BlackboardRelation.target_type == record_type,
                    BlackboardRelation.target_id == record_id,
                ),
            )
        )
    return stmt


def list_relations(
    db: Session,
    *,
    investigation_id: int | None = None,
    record_type: str | None = None,
    record_id: int | None = None,
    relation_type: str | None = None,
    limit: int | None = None,
) -> list[BlackboardRelation]:
    stmt = relations_query(
        investigation_id=investigation_id,
        record_type=record_type,
        record_id=record_id,
        relation_type=relation_type,
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(db.execute(stmt).scalars())


def relation_to_dict(relation: BlackboardRelation) -> dict[str, Any]:
    return {
        "id": relation.id,
        "investigation_id": relation.investigation_id,
        "source_type": relation.source_type,
        "source_id": relation.source_id,
        "target_type": relation.target_type,
        "target_id": relation.target_id,
        "relation_type": relation.relation_type,
        "agent_name": relation.agent_name,
        "reason": relation.reason,
        "created_at": (
            relation.created_at.replace(tzinfo=timezone.utc).isoformat()
            if relation.created_at and relation.created_at.tzinfo is None
            else relation.created_at.isoformat() if relation.created_at else None
        ),
    }


def connected(
    db: Session,
    record_type: str,
    record_id: int,
    investigation_id: int | None = None,
) -> list[dict[str, Any]]:
    """Return the records connected to ``(record_type, record_id)``."""
    relations = list_relations(
        db,
        investigation_id=investigation_id,
        record_type=record_type,
        record_id=record_id,
    )
    result: list[dict[str, Any]] = []
    for r in relations:
        if r.source_type == record_type and r.source_id == record_id:
            direction = "outgoing"
            other_type, other_id = r.target_type, r.target_id
        else:
            direction = "incoming"
            other_type, other_id = r.source_type, r.source_id
        result.append(
            {
                "relation_id": r.id,
                "relation_type": r.relation_type,
                "direction": direction,
                "label": _label(r.relation_type, direction),
                "other": {"type": other_type, "id": other_id},
                "agent_name": r.agent_name,
                "reason": r.reason,
            }
        )
    return result


_LABELS = {
    "extracted_from": "extracted from",
    "derived_from": "derived from",
    "contradicts": "contradicts",
    "has_evidence": "has evidence",
    "supports": "supports",
    "refutes": "refutes",
    "explains": "explains",
    "resolved_by": "resolved by",
    "investigates": "investigates",
}


def _label(relation_type: str, direction: str) -> str:
    base = _LABELS.get(relation_type, relation_type.replace("_", " "))
    if direction == "incoming":
        inverse = {
            "extracted_from": "extracted this",
            "derived_from": "used by",
            "has_evidence": "evidence for",
            "explains": "explained by",
            "resolved_by": "resolves",
            "supports": "supported by",
            "refutes": "refuted by",
            "investigates": "investigated by",
        }
        return inverse.get(relation_type, base)
    return base
