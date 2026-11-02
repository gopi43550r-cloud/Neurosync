"""Knowledge graph tests.

Verifies the graph is projected only from persisted records (nothing invented),
that the required relationships and their verified/inferred classification are
correct, that scoping and filters behave, and that large graphs are capped.
"""
from __future__ import annotations

from app.database import Base, SessionLocal, engine
from app.demo import scenario
from app.services import knowledge_graph_service as kg
from app.tests.conftest import run_investigation_sync

REQUIRED = set(kg.REQUIRED_RELATION_TYPES)


def _prepared(db):
    docs, inv_id = scenario.load_demo(db, auto_start=False)
    run_investigation_sync(db, inv_id)
    return docs, inv_id


def test_builds_from_persisted_records_with_all_required_relations(db):
    _prepared(db)
    graph = kg.build_knowledge_graph(db)

    for node_type in ("document", "claim", "conflict", "evidence", "hypothesis", "conclusion"):
        assert graph["node_type_counts"].get(node_type, 0) > 0

    edge_types = {e["edge_type"] for e in graph["edges"]}
    assert REQUIRED <= edge_types


def test_nodes_and_edges_reference_only_real_records(db):
    from app.models import Claim, Conclusion, Conflict, Document, Evidence, Hypothesis, Investigation

    _prepared(db)
    graph = kg.build_knowledge_graph(db)

    ids = {
        "document": {d.id for d in db.query(Document).all()},
        "claim": {c.id for c in db.query(Claim).all()},
        "conflict": {c.id for c in db.query(Conflict).all()},
        "evidence": {e.id for e in db.query(Evidence).all()},
        "hypothesis": {h.id for h in db.query(Hypothesis).all()},
        "conclusion": {c.id for c in db.query(Conclusion).all()},
        "investigation": {i.id for i in db.query(Investigation).all()},
    }

    node_ids = {n["id"] for n in graph["nodes"]}
    for node in graph["nodes"]:
        ntype, raw = node["id"].split(":", 1)
        if ntype == "agent":
            assert raw  # real registered agent slug
        else:
            assert int(raw) in ids[ntype]

    # No edge points at a node that does not exist.
    for edge in graph["edges"]:
        assert edge["source"] in node_ids
        assert edge["target"] in node_ids


def test_verified_flags_distinguish_fk_from_inferred(db):
    _prepared(db)
    graph = kg.build_knowledge_graph(db)
    by_type: dict[str, set[bool]] = {}
    for edge in graph["edges"]:
        by_type.setdefault(edge["edge_type"], set()).add(edge["verified"])

    # Direct persisted foreign keys / ledger rows.
    for edge_type in ("contains", "supported_by", "contradicts", "concerns", "created"):
        assert by_type[edge_type] == {True}

    # Derived from JSON id lists / membership joins.
    assert by_type["derived_from"] == {False}
    assert by_type["investigated_in"] == {False}


def test_document_contains_and_claim_contradicts(db):
    _prepared(db)
    graph = kg.build_knowledge_graph(db)
    edges = {(e["source"], e["edge_type"], e["target"]) for e in graph["edges"]}

    docs = [n["id"] for n in graph["nodes"] if n["node_type"] == "document"]
    claims = [n["id"] for n in graph["nodes"] if n["node_type"] == "claim"]
    assert any((d, "contains", c) in edges for d in docs for c in claims)
    assert any(e["edge_type"] == "contradicts" for e in graph["edges"])


def test_created_edges_link_agents_to_their_outputs(db):
    _prepared(db)
    graph = kg.build_knowledge_graph(db)

    created = {(e["source"], e["target"]) for e in graph["edges"] if e["edge_type"] == "created"}
    assert ("agent:evidence-collector", "claim:1") in created
    assert ("agent:conflict-detector", "conflict:1") in created
    assert ("agent:decision-agent", "conclusion:1") in created
    assert ("agent:verification-agent", "hypothesis:1") in created

    agent_nodes = {n["id"] for n in graph["nodes"] if n["node_type"] == "agent"}
    assert "agent:evidence-collector" in agent_nodes
    assert all(n["data"].get("responsibility") for n in graph["nodes"] if n["node_type"] == "agent")


def test_conclusion_path_to_evidence_exists(db):
    _prepared(db)
    graph = kg.build_knowledge_graph(db)
    adjacency: dict[str, list[str]] = {}
    for edge in graph["edges"]:
        if edge["edge_type"] in {"derived_from", "supports", "challenges", "supported_by"}:
            adjacency.setdefault(edge["source"], []).append(edge["target"])

    conclusions = [n["id"] for n in graph["nodes"] if n["node_type"] == "conclusion"]
    assert conclusions
    reachable = set()
    stack = list(conclusions)
    while stack:
        node = stack.pop()
        for nxt in adjacency.get(node, []):
            if nxt not in reachable:
                reachable.add(nxt)
                stack.append(nxt)
    assert any(nid.startswith("evidence:") for nid in reachable)


def test_investigation_scope_excludes_other_investigations(db):
    docs, inv_id = _prepared(db)
    unscoped = kg.build_knowledge_graph(db)
    scoped = kg.build_knowledge_graph(db, investigation_id=inv_id)

    assert scoped["investigation_id"] == inv_id
    assert len(scoped["nodes"]) <= len(unscoped["nodes"])
    assert {n["id"] for n in scoped["nodes"]} <= {n["id"] for n in unscoped["nodes"]}

    # Missing investigation -> honest empty payload.
    missing = kg.build_knowledge_graph(db, investigation_id=999999)
    assert missing["nodes"] == [] and missing["edges"] == []


def test_record_and_relation_filters(db):
    _prepared(db)

    only_reasoning = kg.build_knowledge_graph(
        db, record_types=["evidence", "hypothesis", "conclusion"]
    )
    assert set(only_reasoning["node_type_counts"]) <= {"evidence", "hypothesis", "conclusion"}
    assert {e["edge_type"] for e in only_reasoning["edges"]} <= {"supports", "challenges", "derived_from"}

    created = kg.build_knowledge_graph(db, relation_types=["created"])
    assert all(e["edge_type"] == "created" for e in created["edges"])
    assert set(created["node_type_counts"]) <= {"agent", "claim", "conflict", "evidence", "hypothesis", "conclusion"}
    # every retained node is actually connected
    endpoint_ids = {e["source"] for e in created["edges"]} | {e["target"] for e in created["edges"]}
    assert {n["id"] for n in created["nodes"]} == endpoint_ids


def test_truncation_caps_nodes_but_reports_totals(db):
    _prepared(db)
    full = kg.build_knowledge_graph(db)
    capped = kg.build_knowledge_graph(db, max_nodes=2)

    assert capped["truncated"] is True
    assert len(capped["nodes"]) == 2
    assert capped["totals"]["nodes"] == full["totals"]["nodes"]
    assert len(capped["edges"]) <= full["totals"]["edges"]


def test_empty_investigation_returns_empty_graph(db):
    graph = kg.build_knowledge_graph(db)
    assert graph["nodes"] == []
    assert graph["edges"] == []
    assert graph["truncated"] is False


def test_endpoint_returns_graph_and_honours_filters(client, db):
    _prepared(db)
    resp = client.get("/api/knowledge-graph")
    assert resp.status_code == 200
    body = resp.json()
    assert body["nodes"] and body["edges"]
    assert set(kg.REQUIRED_RELATION_TYPES) <= set(body["relation_type_counts"])

    filtered = client.get(
        "/api/knowledge-graph",
        params=[("relation_type", "created"), ("record_type", "agent"), ("record_type", "claim")],
    )
    assert filtered.status_code == 200
    fbody = filtered.json()
    assert all(e["edge_type"] == "created" for e in fbody["edges"])
    assert set(fbody["node_type_counts"]) <= {"agent", "claim"}
