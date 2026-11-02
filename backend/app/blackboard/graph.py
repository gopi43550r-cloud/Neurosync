"""Build a graph representation of blackboard relationships.

Nodes: documents -> claims -> conflicts -> evidence -> hypotheses -> conclusions.
Edges reflect: extracted_from, contradicts, supports, refutes, derived_from,
resolved_by. Only actual persisted relationships are drawn.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Claim, Conclusion, Conflict, Document, Evidence, Hypothesis


def _cfg(filename: str, limit: int = 120) -> str:
    return filename if len(filename) <= limit else filename[: limit - 1] + "…"


def build_graph(db: Session, document_ids: list[int] | None = None) -> dict[str, list[dict[str, Any]]]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    # When scoped, every table is filtered in SQL so the query cost tracks the
    # scope rather than the whole database.
    if document_ids:
        docs = list(db.execute(select(Document).where(Document.id.in_(document_ids))).scalars())
        doc_ids = {d.id for d in docs}
        claims = (
            list(db.execute(select(Claim).where(Claim.document_id.in_(doc_ids))).scalars())
            if doc_ids
            else []
        )
        claim_ids = {c.id for c in claims}
        conflicts = (
            list(
                db.execute(
                    select(Conflict).where(
                        (Conflict.claim_a_id.in_(claim_ids)) | (Conflict.claim_b_id.in_(claim_ids))
                    )
                ).scalars()
            )
            if claim_ids
            else []
        )
        conflict_ids = {c.id for c in conflicts}
        hypotheses = (
            list(db.execute(select(Hypothesis).where(Hypothesis.conflict_id.in_(conflict_ids))).scalars())
            if conflict_ids
            else []
        )
        evidence = (
            list(
                db.execute(
                    select(Evidence).where(
                        (Evidence.document_id.is_(None)) | (Evidence.document_id.in_(doc_ids))
                    )
                ).scalars()
            )
            if doc_ids
            else []
        )
    else:
        docs = list(db.execute(select(Document)).scalars())
        doc_ids = {d.id for d in docs}
        claims = list(db.execute(select(Claim)).scalars())
        claim_ids = {c.id for c in claims}
        conflicts = list(db.execute(select(Conflict)).scalars())
        conflict_ids = {c.id for c in conflicts}
        hypotheses = list(db.execute(select(Hypothesis)).scalars())
        evidence = list(db.execute(select(Evidence)).scalars())
    hyp_ids = {h.id for h in hypotheses}

    for d in docs:
        nodes.append({
            "id": f"doc-{d.id}",
            "node_type": "document",
            "label": _cfg(d.filename),
            "data": {"document_id": d.id, "status": d.status, "is_demo": bool(d.is_demo)},
        })

    for c in claims:
        nodes.append({
            "id": f"claim-{c.id}",
            "node_type": "claim",
            "label": _cfg(c.claim_text, 60),
            "data": {"claim_id": c.id, "document_id": c.document_id, "confidence": c.confidence},
        })
        edges.append({
            "id": f"e-extract-{c.document_id}-{c.id}",
            "source": f"doc-{c.document_id}",
            "target": f"claim-{c.id}",
            "edge_type": "extracted_from",
            "label": "extracted from",
        })

    for con in conflicts:
        nodes.append({
            "id": f"conflict-{con.id}",
            "node_type": "conflict",
            "label": f"C{con.id}: {_cfg(con.conflict_type, 40)}",
            "data": {
                "conflict_id": con.id,
                "severity": con.severity,
                "status": con.status,
                "confidence": con.confidence,
            },
        })
        for cid in (con.claim_a_id, con.claim_b_id):
            if cid in claim_ids:
                edges.append({
                    "id": f"e-con-{con.id}-{cid}",
                    "source": f"claim-{cid}",
                    "target": f"conflict-{con.id}",
                    "edge_type": "contradicts",
                    "label": "contradicts",
                })

    for ev in evidence:
        nodes.append({
            "id": f"ev-{ev.id}",
            "node_type": "evidence",
            "label": _cfg(ev.description, 50),
            "data": {
                "evidence_id": ev.id,
                "origin": ev.origin,
                "verification_status": ev.verification_status,
                "relevance": ev.relevance_score,
            },
        })
        edges.append({
            "id": f"e-ev-{ev.id}",
            "source": f"conflict-{ev.conflict_id}",
            "target": f"ev-{ev.id}",
            "edge_type": "derived_from",
            "label": "has evidence",
        })
        if ev.supports_hypothesis_id and ev.supports_hypothesis_id in hyp_ids:
            edges.append({
                "id": f"e-support-{ev.id}",
                "source": f"ev-{ev.id}",
                "target": f"hyp-{ev.supports_hypothesis_id}",
                "edge_type": "supports",
                "label": "supports",
            })
        if ev.contradicts_hypothesis_id and ev.contradicts_hypothesis_id in hyp_ids:
            edges.append({
                "id": f"e-refute-{ev.id}",
                "source": f"ev-{ev.id}",
                "target": f"hyp-{ev.contradicts_hypothesis_id}",
                "edge_type": "refutes",
                "label": "refutes",
            })

    for h in hypotheses:
        nodes.append({
            "id": f"hyp-{h.id}",
            "node_type": "hypothesis",
            "label": _cfg(h.title, 50),
            "data": {"hypothesis_id": h.id, "status": h.status, "support_score": h.support_score},
        })
        edges.append({
            "id": f"e-hyp-{h.id}",
            "source": f"conflict-{h.conflict_id}",
            "target": f"hyp-{h.id}",
            "edge_type": "derived_from",
            "label": "explains",
        })

    if document_ids:
        conclusions = list(
            db.execute(
                select(Conclusion).where(
                    (Conclusion.conflict_id.is_(None)) | (Conclusion.conflict_id.in_(conflict_ids))
                )
            ).scalars()
        )
    else:
        conclusions = list(db.execute(select(Conclusion)).scalars())
    for cc in conclusions:
        if cc.conflict_id and cc.conflict_id not in conflict_ids:
            continue
        nodes.append({
            "id": f"concl-{cc.id}",
            "node_type": "conclusion",
            "label": _cfg(cc.decision_type, 40),
            "data": {"conclusion_id": cc.id, "confidence": cc.confidence},
        })
        if cc.conflict_id:
            edges.append({
                "id": f"e-concl-{cc.id}",
                "source": f"conflict-{cc.conflict_id}",
                "target": f"concl-{cc.id}",
                "edge_type": "resolved_by",
                "label": "resolved by",
            })

    return {"nodes": nodes, "edges": edges}