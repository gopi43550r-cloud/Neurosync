"""Knowledge graph service.

Builds an interactive, typed knowledge graph from records that are **actually
persisted**. Nothing here is invented: every node is a stored row (or a real,
registered agent) and every edge is backed by a persisted foreign key, an
association table, a JSON id list on a record, or an agent execution-ledger /
event-log row.

The graph complements the Blackboard rather than replacing it. The Blackboard
stays the shared workspace the agents reason over; this service is a read-only,
queryable projection of that workspace plus the agents and investigations that
produced it.

Node types: ``document``, ``claim``, ``evidence``, ``conflict``,
``hypothesis``, ``conclusion``, ``agent``, ``investigation``.

Edges each carry a ``verified`` flag so the UI can distinguish:

* **verified** - the relationship is a direct persisted foreign key, an
  association row, or a ledger/event row (e.g. a claim's ``document_id``, a
  conflict's two claims, an agent's recorded output).
* **inferred** - the relationship is derived from a persisted JSON id list or a
  membership join (e.g. a hypothesis' ``supporting_evidence_ids``, or
  "hypothesis belongs to a conflict investigated by X").
"""
from __future__ import annotations

import json
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..agents import default_agents
from ..models import (
    AgentActivity,
    Claim,
    Conclusion,
    Conflict,
    Document,
    EventLog,
    Evidence,
    Hypothesis,
    Investigation,
)
from ..models.investigation import investigation_conflicts, investigation_documents
from ..models.investigation import investigation_conflicts

# Canonical node types, in layout order.
RECORD_NODE_TYPES = ("document", "claim", "conflict", "evidence", "hypothesis", "conclusion")
NODE_TYPES = RECORD_NODE_TYPES + ("agent", "investigation")

# Required relationships from the feature specification.
REQUIRED_RELATION_TYPES = (
    "contains",         # document  -> claim
    "supported_by",     # claim     -> evidence
    "contradicts",      # claim     -> claim
    "supports",         # evidence  -> hypothesis
    "challenges",       # evidence  -> hypothesis
    "investigated_in",  # hypothesis-> investigation
    "created",          # agent     -> record
    "derived_from",     # conclusion-> evidence
)

# Additional persisted structural edges that connect Conflict / Investigation
# nodes (a conflict owns its two claims, is explained by hypotheses, gathers
# evidence and is decided by a conclusion; an investigation investigates its
# conflicts). These are real foreign keys / association rows, not inventions.
STRUCTURAL_RELATION_TYPES = (
    "concerns",     # conflict     -> claim
    "explains",     # hypothesis   -> conflict
    "gathered_for", # evidence     -> conflict
    "investigates", # investigation-> conflict
    "concludes",    # conflict     -> conclusion
)

RELATION_TYPES = REQUIRED_RELATION_TYPES + STRUCTURAL_RELATION_TYPES

# event_type -> the record type it creates.
_EVENT_PRODUCES = {
    "claim_extracted": "claim",
    "conflict_detected": "conflict",
    "hypothesis_generated": "hypothesis",
    "evidence_added": "evidence",
    "conclusion_reached": "conclusion",
}

# payload key holding the produced record id, per type.
_PRODUCED_ID_KEY = {
    "claim": "claim_id",
    "conflict": "conflict_id",
    "hypothesis": "hypothesis_id",
    "evidence": "evidence_id",
    "conclusion": "conclusion_id",
}

# An agent's declared output type, used to type the (untyped) ids recorded on its
# execution-ledger rows against the real records.
_AGENT_OUTPUT_TYPE = {
    "Evidence Collector": "claim",
    "Conflict Detector": "conflict",
    "Hypothesis Generator": "hypothesis",
    "Investigator": "evidence",
    "Verification Agent": "hypothesis",
    "Decision Agent": "conclusion",
}


# ---------------------------------------------------------------- id helpers
def _nid(record_type: str, record_id: int) -> str:
    return f"{record_type}:{record_id}"


def _agent_nid(name: str) -> str:
    return "agent:" + name.strip().lower().replace(" ", "-")


def _short(text: str, limit: int = 90) -> str:
    text = (text or "").strip().replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _loads_list(value: str | None) -> list[int]:
    try:
        parsed = json.loads(value or "[]")
    except (TypeError, json.JSONDecodeError):
        return []
    return [v for v in parsed if isinstance(v, int)] if isinstance(parsed, list) else []


# -------------------------------------------------------------------- scoping
def _scope(db: Session, investigation_id: int | None) -> dict[str, Any] | None:
    """Resolve the records in scope. Returns ``None`` for a missing investigation.

    The scoped branch filters in SQL so a graph for one investigation never
    loads the whole database.
    """
    if investigation_id is None:
        documents = list(db.execute(select(Document)).scalars())
        claims = list(db.execute(select(Claim)).scalars())
        conflicts = list(db.execute(select(Conflict)).scalars())
        hypotheses = list(db.execute(select(Hypothesis)).scalars())
        evidence = list(db.execute(select(Evidence)).scalars())
        conclusions = list(db.execute(select(Conclusion)).scalars())
        investigations = list(db.execute(select(Investigation)).scalars())
        scope_inv_ids = {i.id for i in investigations}
        conflict_to_investigations: dict[int, list[int]] = {}
        for row in db.execute(select(investigation_conflicts)).all():
            inv_id, conflict_id = row[0], row[1]
            if inv_id in scope_inv_ids:
                conflict_to_investigations.setdefault(conflict_id, []).append(inv_id)
    else:
        inv = db.get(Investigation, investigation_id)
        if inv is None:
            return None
        conflicts = list(
            db.execute(
                select(Conflict)
                .join(investigation_conflicts, Conflict.id == investigation_conflicts.c.conflict_id)
                .where(investigation_conflicts.c.investigation_id == investigation_id)
            ).scalars()
        )
        conflict_ids = [c.id for c in conflicts]
        if conflict_ids:
            hypotheses = list(
                db.execute(select(Hypothesis).where(Hypothesis.conflict_id.in_(conflict_ids))).scalars()
            )
            evidence = list(
                db.execute(select(Evidence).where(Evidence.conflict_id.in_(conflict_ids))).scalars()
            )
            conclusions = list(
                db.execute(
                    select(Conclusion).where(
                        (Conclusion.investigation_id == inv.id)
                        | (Conclusion.conflict_id.in_(conflict_ids))
                    )
                ).scalars()
            )
        else:
            hypotheses, evidence, conclusions = [], [], []
        # Claims: those from the investigation's documents, plus any claim a
        # scoped conflict references (so a conflict is never drawn half-missing).
        claim_ids = set()
        for c in conflicts:
            claim_ids.add(c.claim_a_id)
            claim_ids.add(c.claim_b_id)
        doc_ids = {
            row[0]
            for row in db.execute(
                select(investigation_documents.c.document_id).where(
                    investigation_documents.c.investigation_id == investigation_id
                )
            ).all()
        }
        claim_stmt = select(Claim)
        if doc_ids and claim_ids:
            claim_stmt = claim_stmt.where(Claim.document_id.in_(doc_ids) | Claim.id.in_(claim_ids))
        elif doc_ids:
            claim_stmt = claim_stmt.where(Claim.document_id.in_(doc_ids))
        elif claim_ids:
            claim_stmt = claim_stmt.where(Claim.id.in_(claim_ids))
        else:
            claim_stmt = claim_stmt.where(False)
        claims = list(db.execute(claim_stmt).scalars())
        doc_ids |= {c.document_id for c in claims}
        documents = (
            list(db.execute(select(Document).where(Document.id.in_(doc_ids))).scalars())
            if doc_ids
            else []
        )
        investigations = [inv]
        conflict_to_investigations = {cid: [inv.id] for cid in conflict_ids}

    if investigation_id is None:
        event_stmt = select(EventLog)
        activity_stmt = select(AgentActivity)
    else:
        event_stmt = select(EventLog).where(EventLog.investigation_id == investigation_id)
        activity_stmt = select(AgentActivity).where(AgentActivity.investigation_id == investigation_id)

    # Only load the events that actually establish a "who created what" edge.
    events = list(
        db.execute(event_stmt.where(EventLog.event_type.in_(list(_EVENT_PRODUCES)))).scalars()
    )
    activities = list(db.execute(activity_stmt).scalars())

    return {
        "documents": documents,
        "claims": claims,
        "conflicts": conflicts,
        "hypotheses": hypotheses,
        "evidence": evidence,
        "conclusions": conclusions,
        "investigations": investigations,
        "events": events,
        "activities": activities,
        "conflict_to_investigations": conflict_to_investigations,
    }


# ------------------------------------------------------------------ building
def build_knowledge_graph(
    db: Session,
    *,
    investigation_id: int | None = None,
    record_types: Iterable[str] | None = None,
    relation_types: Iterable[str] | None = None,
    max_nodes: int = 800,
    max_edges: int = 2500,
) -> dict[str, Any]:
    scope = _scope(db, investigation_id)
    if scope is None:
        return _empty(investigation_id)

    nodes: dict[str, dict[str, Any]] = {}
    records_by_type: dict[str, set[int]] = {t: set() for t in NODE_TYPES}

    def add_node(nid: str, ntype: str, label: str, data: dict[str, Any]) -> None:
        if nid not in nodes:
            nodes[nid] = {"id": nid, "node_type": ntype, "label": label, "data": data}

    # --- records ---------------------------------------------------------
    for d in scope["documents"]:
        add_node(
            _nid("document", d.id), "document", _short(d.filename),
            {"filename": d.filename, "status": d.status, "is_demo": bool(d.is_demo)},
        )
        records_by_type["document"].add(d.id)

    for c in scope["claims"]:
        add_node(
            _nid("claim", c.id), "claim", _short(c.claim_text, 70),
            {
                "document_id": c.document_id, "subject": c.subject, "predicate": c.predicate,
                "object_value": c.object_value, "numeric_value": c.numeric_value, "unit": c.unit,
                "claim_type": c.claim_type, "confidence": c.confidence, "polarity": c.polarity,
            },
        )
        records_by_type["claim"].add(c.id)

    for con in scope["conflicts"]:
        add_node(
            _nid("conflict", con.id), "conflict",
            f"C{con.id}: {_short(con.conflict_type, 36)}",
            {
                "conflict_type": con.conflict_type, "severity": con.severity,
                "status": con.status, "confidence": con.confidence,
                "description": _short(con.description, 160),
                "claim_a_id": con.claim_a_id, "claim_b_id": con.claim_b_id,
            },
        )
        records_by_type["conflict"].add(con.id)

    for ev in scope["evidence"]:
        add_node(
            _nid("evidence", ev.id), "evidence", _short(ev.description, 60),
            {
                "conflict_id": ev.conflict_id, "claim_id": ev.claim_id, "document_id": ev.document_id,
                "evidence_type": ev.evidence_type, "origin": ev.origin,
                "verification_status": ev.verification_status,
                "relevance_score": ev.relevance_score, "reliability_score": ev.reliability_score,
                "directness": ev.directness,
                "supports_hypothesis_id": ev.supports_hypothesis_id,
                "contradicts_hypothesis_id": ev.contradicts_hypothesis_id,
            },
        )
        records_by_type["evidence"].add(ev.id)

    for h in scope["hypotheses"]:
        add_node(
            _nid("hypothesis", h.id), "hypothesis", _short(h.title, 60),
            {
                "conflict_id": h.conflict_id, "status": h.status,
                "support_score": h.support_score, "confidence": h.confidence,
                "origin": h.origin,
            },
        )
        records_by_type["hypothesis"].add(h.id)

    for cc in scope["conclusions"]:
        add_node(
            _nid("conclusion", cc.id), "conclusion", _short(cc.decision_type, 40),
            {
                "conflict_id": cc.conflict_id, "investigation_id": cc.investigation_id,
                "decision_type": cc.decision_type, "confidence": cc.confidence,
                "superseded": cc.superseded_at is not None,
            },
        )
        records_by_type["conclusion"].add(cc.id)

    for inv in scope["investigations"]:
        add_node(
            _nid("investigation", inv.id), "investigation", _short(inv.name, 50),
            {
                "status": inv.status, "iteration_count": inv.iteration_count,
                "stop_reason": inv.stop_reason, "research_question": _short(inv.research_question, 160),
            },
        )
        records_by_type["investigation"].add(inv.id)

    agent_meta = {a.name: a for a in default_agents()}
    agent_nid_to_name = {_agent_nid(a.name): a.name for a in agent_meta.values()}

    def ensure_agent_node(agent_name: str) -> str:
        nid = _agent_nid(agent_name)
        meta = agent_meta.get(agent_name)
        add_node(
            nid, "agent", agent_name,
            {"responsibility": meta.responsibility if meta else "", "created_count": 0},
        )
        return nid

    # --- edges -----------------------------------------------------------
    edges: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    def add_edge(
        source: str,
        target: str,
        edge_type: str,
        label: str,
        verified: bool,
        *,
        reason: str = "",
        agent_name: str = "",
    ) -> None:
        key = (source, edge_type, target)
        if key in seen:
            return
        seen.add(key)
        edges.append(
            {
                "id": f"{source}|{edge_type}|{target}",
                "source": source,
                "target": target,
                "edge_type": edge_type,
                "label": label,
                "verified": verified,
                "agent_name": agent_name,
                "reason": reason,
            }
        )

    # Verified edges first so that, when the same pair appears from a weaker,
    # inferred source too, the verified flag wins.
    for c in scope["claims"]:
        add_edge(
            _nid("document", c.document_id), _nid("claim", c.id), "contains", "contains", True,
            reason="Claim was extracted from this document.",
        )

    for con in scope["conflicts"]:
        for claim_id in (con.claim_a_id, con.claim_b_id):
            add_edge(
                _nid("conflict", con.id), _nid("claim", claim_id), "concerns", "concerns", True,
                reason=f"Conflict about this claim ({con.conflict_type}).",
            )
        add_edge(
            _nid("claim", con.claim_a_id), _nid("claim", con.claim_b_id), "contradicts",
            "contradicts", True,
            reason=f"Claims contradict each other (C{con.id}, {con.conflict_type}).",
        )

    for ev in scope["evidence"]:
        if ev.claim_id is not None:
            add_edge(
                _nid("claim", ev.claim_id), _nid("evidence", ev.id), "supported_by",
                "supported by", True, reason="Evidence attached to this claim.",
            )
        add_edge(
            _nid("evidence", ev.id), _nid("conflict", ev.conflict_id), "gathered_for",
            "gathered for", True, reason="Evidence was gathered for this conflict.",
        )
        if ev.supports_hypothesis_id is not None:
            add_edge(
                _nid("evidence", ev.id), _nid("hypothesis", ev.supports_hypothesis_id),
                "supports", "supports", True, reason="Evidence supports this hypothesis.",
            )
        if ev.contradicts_hypothesis_id is not None:
            add_edge(
                _nid("evidence", ev.id), _nid("hypothesis", ev.contradicts_hypothesis_id),
                "challenges", "challenges", True, reason="Evidence contradicts this hypothesis.",
            )

    for h in scope["hypotheses"]:
        add_edge(
            _nid("hypothesis", h.id), _nid("conflict", h.conflict_id), "explains", "explains",
            True, reason="Hypothesis was proposed to explain this conflict.",
        )

    for inv in scope["investigations"]:
        for conflict_id in scope["conflict_to_investigations"]:
            if inv.id in scope["conflict_to_investigations"][conflict_id]:
                add_edge(
                    _nid("investigation", inv.id), _nid("conflict", conflict_id), "investigates",
                    "investigates", True, reason="Investigation investigates this conflict.",
                )

    for cc in scope["conclusions"]:
        if cc.conflict_id is not None:
            add_edge(
                _nid("conflict", cc.conflict_id), _nid("conclusion", cc.id), "concludes",
                "concludes", True, reason="Conclusion was synthesised for this conflict.",
            )

    # Agent CREATED record - from the event log (authoritative, typed).
    for event in scope["events"]:
        produced = _EVENT_PRODUCES.get(event.event_type)
        agent_name = event.agent_name
        if not produced or not agent_name:
            continue
        try:
            payload = json.loads(event.payload or "{}")
        except json.JSONDecodeError:
            payload = {}
        pid = payload.get(_PRODUCED_ID_KEY[produced])
        if not isinstance(pid, int) and event.entity_type == produced:
            pid = event.entity_id
        if not isinstance(pid, int):
            continue
        add_edge(
            ensure_agent_node(agent_name), _nid(produced, pid), "created", "created", True,
            reason=f"{agent_name} produced this record (event '{event.event_type}').",
            agent_name=agent_name,
        )

    # Agent CREATED record - from the execution ledger (covers outputs that have
    # no dedicated creation event, e.g. investigator-produced evidence). The
    # recorded id is typed against real records using the agent's contract.
    for activity in scope["activities"]:
        if not activity.agent_name:
            continue
        preferred = _AGENT_OUTPUT_TYPE.get(activity.agent_name)
        for oid in _loads_list(activity.output_record_ids):
            rtype = _resolve_output_type(oid, preferred, records_by_type)
            if rtype is None:
                continue
            add_edge(
                ensure_agent_node(activity.agent_name), _nid(rtype, oid), "created", "created", True,
                reason="Recorded in the agent execution ledger.",
                agent_name=activity.agent_name,
            )

    # Inferred edges from persisted JSON id lists (added after verified edges).
    for h in scope["hypotheses"]:
        for eid in _loads_list(h.supporting_evidence_ids):
            add_edge(
                _nid("evidence", eid), _nid("hypothesis", h.id), "supports", "supports", False,
                reason="Listed as supporting evidence on the hypothesis.",
            )
        for eid in _loads_list(h.contradicting_evidence_ids):
            add_edge(
                _nid("evidence", eid), _nid("hypothesis", h.id), "challenges", "challenges",
                False, reason="Listed as challenging evidence on the hypothesis.",
            )
    for cc in scope["conclusions"]:
        for eid in _loads_list(cc.supporting_evidence_ids):
            add_edge(
                _nid("conclusion", cc.id), _nid("evidence", eid), "derived_from",
                "derived from", False, reason="Evidence cited by this conclusion.",
            )

    # Hypothesis INVESTIGATED_IN investigation (membership join through conflict).
    for h in scope["hypotheses"]:
        for inv_id in scope["conflict_to_investigations"].get(h.conflict_id, []):
            add_edge(
                _nid("hypothesis", h.id), _nid("investigation", inv_id), "investigated_in",
                "investigated in", False,
                reason="Hypothesis belongs to a conflict investigated here.",
            )

    # ------------------------------------------------------------- filtering
    active_nodes = dict(nodes)
    # Drop agent nodes that never end up connected (keeps the empty state honest).
    connected_agents = {
        e["source"] for e in edges if e["source"].startswith("agent:")
    } | {e["target"] for e in edges if e["target"].startswith("agent:")}
    for nid in list(active_nodes):
        if nid.startswith("agent:") and nid not in connected_agents:
            del active_nodes[nid]

    requested_types = _normalize(record_types)
    if requested_types:
        active_nodes = {
            nid: n for nid, n in active_nodes.items() if n["node_type"] in requested_types
        }

    def endpoints_ok(edge: dict[str, Any]) -> bool:
        return edge["source"] in active_nodes and edge["target"] in active_nodes

    wanted_relations = _normalize(relation_types)
    kept_edges = [
        e for e in edges if endpoints_ok(e) and (not wanted_relations or e["edge_type"] in wanted_relations)
    ]

    # When the user restricts the relationships, hide now-isolated nodes so the
    # filtered graph only shows what is actually connected.
    if wanted_relations:
        touched = {e["source"] for e in kept_edges} | {e["target"] for e in kept_edges}
        active_nodes = {nid: n for nid, n in active_nodes.items() if nid in touched}

    node_type_counts = _count_by(active_nodes.values(), "node_type")
    relation_type_counts = _count_by(kept_edges, "edge_type")

    # -------------------------------------------------------------- capping
    ordered_nodes = sorted(
        active_nodes.values(), key=lambda n: (_node_rank(n["node_type"], agent_meta), n["id"])
    )
    total_nodes = len(ordered_nodes)
    truncated = total_nodes > max_nodes
    capped_nodes = ordered_nodes[:max_nodes]
    allowed = {n["id"] for n in capped_nodes}

    capped_edges = [e for e in kept_edges if e["source"] in allowed and e["target"] in allowed]
    total_edges = len(capped_edges)
    if total_edges > max_edges:
        truncated = True
        capped_edges = capped_edges[:max_edges]

    # Fill agent node metadata (responsibility / connection count) now that edges
    # are finalised.
    for node in capped_nodes:
        if node["node_type"] == "agent":
            name = _agent_name_from_nid(node["id"], agent_nid_to_name)
            meta = agent_meta.get(name)
            node["data"] = {
                "responsibility": meta.responsibility if meta else "",
                "created_count": sum(1 for e in capped_edges if e["source"] == node["id"]),
            }

    return {
        "nodes": capped_nodes,
        "edges": capped_edges,
        "node_type_counts": node_type_counts,
        "relation_type_counts": relation_type_counts,
        "available_node_types": list(NODE_TYPES),
        "required_relation_types": list(REQUIRED_RELATION_TYPES),
        "available_relation_types": list(RELATION_TYPES),
        "totals": {"nodes": total_nodes, "edges": total_edges},
        "truncated": truncated,
        "investigation_id": investigation_id,
    }


def _resolve_output_type(
    record_id: int, preferred: str | None, records_by_type: dict[str, set[int]]
) -> str | None:
    if preferred and record_id in records_by_type.get(preferred, set()):
        return preferred
    matches = [t for t in RECORD_NODE_TYPES if record_id in records_by_type.get(t, set())]
    return matches[0] if len(matches) == 1 else None


def _agent_name_from_nid(nid: str, agent_nid_to_name: dict[str, str] | None = None) -> str:
    if agent_nid_to_name and nid in agent_nid_to_name:
        return agent_nid_to_name[nid]
    for agent in default_agents():
        if _agent_nid(agent.name) == nid:
            return agent.name
    slug = nid.split(":", 1)[1]
    return slug.replace("-", " ").title()


def _node_rank(ntype: str, agent_meta: dict[str, Any]) -> int:
    if ntype in RECORD_NODE_TYPES:
        return RECORD_NODE_TYPES.index(ntype)
    if ntype == "investigation":
        return len(RECORD_NODE_TYPES)
    return len(RECORD_NODE_TYPES) + 1


def _count_by(items: Iterable[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        counts[item[key]] = counts.get(item[key], 0) + 1
    return counts


def _normalize(value: Iterable[str] | None) -> set[str]:
    if not value:
        return set()
    result: set[str] = set()
    for item in value:
        for part in str(item).split(","):
            part = part.strip()
            if part:
                result.add(part)
    return result


def _empty(investigation_id: int | None) -> dict[str, Any]:
    return {
        "nodes": [],
        "edges": [],
        "node_type_counts": {},
        "relation_type_counts": {},
        "available_node_types": list(NODE_TYPES),
        "required_relation_types": list(REQUIRED_RELATION_TYPES),
        "available_relation_types": list(RELATION_TYPES),
        "totals": {"nodes": 0, "edges": 0},
        "truncated": False,
        "investigation_id": investigation_id,
    }
