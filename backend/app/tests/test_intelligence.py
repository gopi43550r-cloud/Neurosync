"""Advanced Blackboard Intelligence layer tests.

Covers:
  * the relation model (typed, agent-attributed edges) and its idempotency,
  * event provenance (responsible agent, entity and related records),
  * idempotent event processing,
  * event-driven, *scoped* re-evaluation of the affected conflict only,
  * consistency (duplicate-evidence prevention + structural validation),
  * traceability (why a record exists, what influenced it),
  * the new HTTP endpoints.
"""
from __future__ import annotations

import time

from app.blackboard import event_processor
from app.blackboard.events import event_bus
from app.demo import scenario
from app.models import Conclusion, Conflict, EventLog, Evidence, Hypothesis, Investigation, enums
from app.services import consistency_service, evidence_service, reevaluation_service, relation_service, traceability_service
from app.tests.conftest import run_investigation_sync


def _run_demo(db):
    docs, inv_id = scenario.load_demo(db, auto_start=False)
    run_investigation_sync(db, inv_id)
    db.expire_all()
    return docs, inv_id


# --------------------------------------------------------------------- relations
def test_relations_are_created_and_idempotent(db):
    _, inv_id = _run_demo(db)

    created_again = relation_service.sync_relations(db, inv_id, agent_name="test")
    db.commit()
    assert created_again == 0, "a fully synced blackboard must produce no new relations"

    relations = relation_service.list_relations(db, investigation_id=inv_id)
    assert relations, "the run must have produced typed relations"
    types = {r.relation_type for r in relations}
    assert {"extracted_from", "derived_from", "has_evidence", "explains", "resolved_by", "investigates"} <= types
    assert {"supports", "refutes"} & types
    assert any(r.agent_name for r in relations), "relations should record the responsible agent"


def test_relation_serialization_and_connected(db):
    _, inv_id = _run_demo(db)
    conflict = db.query(Conflict).first()
    connected = relation_service.connected(db, "conflict", conflict.id, inv_id)
    assert connected
    assert all("other" in c and c["other"]["id"] for c in connected)
    assert {c["relation_type"] for c in connected}


# ------------------------------------------------------------------------ events
def test_events_carry_responsible_agent_and_entity(db):
    _, inv_id = _run_demo(db)
    events = db.query(EventLog).filter(EventLog.investigation_id == inv_id).all()
    assert events
    detected = next(e for e in events if e.event_type == enums.EventType.CONFLICT_DETECTED.value)
    assert detected.agent_name == "Conflict Detector"
    assert detected.entity_type == "conflict"
    assert detected.entity_id is not None

    extracted = next(e for e in events if e.event_type == enums.EventType.CLAIM_EXTRACTED.value)
    assert extracted.agent_name == "Evidence Collector"
    assert extracted.entity_type == "claim"
    assert extracted.related and any('"document"' in extracted.related for _ in [0])


def test_event_processing_is_idempotent(db):
    _, inv_id = _run_demo(db)
    first = event_processor.process_pending_events(db, inv_id)
    second = event_processor.process_pending_events(db, inv_id)
    assert second["events_processed"] == 0, "an event must never be processed twice"
    assert first["events_processed"] >= 0


def test_baseline_run_needs_no_reevaluation(db):
    _, inv_id = _run_demo(db)
    before = db.query(Conclusion).count()
    summary = reevaluation_service.drain(db, inv_id)
    assert summary["genuine"] == 0, "a normal run must not trigger re-evaluation"
    assert db.query(Conclusion).count() == before


# -------------------------------------------------------------- reevaluation
def test_evidence_triggers_scoped_reevaluation(db):
    docs, inv_id = _run_demo(db)
    conflict = db.query(Conflict).first()
    sensor = next(h for h in db.query(Hypothesis).all() if "sensor" in h.title.lower() or "calibration" in h.title.lower())
    hypotheses_before = db.query(Hypothesis).count()
    conclusions_before = db.query(Conclusion).filter(Conclusion.conflict_id == conflict.id).all()
    assert len(conclusions_before) == 1

    new_ev = evidence_service.create_evidence(
        db,
        conflict_id=conflict.id,
        description="A second, independent calibration log confirms the sensor was recalibrated (re-evaluation test).",
        evidence_type="calibration_record",
        origin="user",
        document_id=docs[2].id,
        reliability_score=0.85,
        directness=0.9,
        supports_hypothesis_id=sensor.id,
        investigation_id=inv_id,
        actor="user",
    )
    db.commit()

    event_bus.publish(
        db,
        inv_id,
        enums.EventType.EVIDENCE_ADDED.value,
        {"evidence_id": new_ev.id, "conflict_id": conflict.id, "origin": "user"},
        agent_name="Evidence Collector",
        entity_type="evidence",
        entity_id=new_ev.id,
    )
    event_processor.process_pending_events(db, inv_id)

    tasks = event_processor.pending_tasks(db, inv_id)
    assert tasks, "new evidence should schedule scoped re-evaluation"
    assert all(t.conflict_id == conflict.id for t in tasks), "tasks must be scoped to the affected conflict"
    assert {t.kind for t in tasks} >= {"verify"}

    summary = reevaluation_service.drain(db, inv_id)
    assert summary["genuine"] >= 1
    assert summary["reopened"] >= 1
    assert summary["hypotheses_rescored"] >= 1

    db.expire_all()
    conclusions = db.query(Conclusion).filter(Conclusion.conflict_id == conflict.id).order_by(Conclusion.id).all()
    assert len(conclusions) == 2, "a revised conclusion should replace the stale one"
    old = conclusions[0]
    assert old.superseded_at is not None and old.superseded_by_id == conclusions[1].id
    assert db.query(Hypothesis).count() == hypotheses_before, "re-evaluation must not invent hypotheses"
    assert db.query(Conflict).count() == 1, "re-evaluation must not invent conflicts"


def test_reevaluation_is_not_repeated_without_new_information(db):
    _, inv_id = _run_demo(db)
    conflict = db.query(Conflict).first()
    # Nothing new: a second drain is a no-op.
    reevaluation_service.drain(db, inv_id)
    summary = reevaluation_service.drain(db, inv_id)
    assert summary["genuine"] == 0
    assert summary["conclusions_revised"] == 0


# ---------------------------------------------------------------- consistency
def test_duplicate_evidence_is_prevented(db):
    docs, inv_id = scenario.load_demo(db, auto_start=False)
    conflict = Conflict(
        claim_a_id=1, claim_b_id=2, conflict_type="numerical_disagreement",
        description="d", severity="medium", status="open",
    )
    # create two real claims for the FK
    from app.models import Claim, Document

    doc = Document(filename="x.txt", stored_filename="x.txt", file_type="txt", status="processed", checksum="x")
    db.add(doc)
    db.flush()
    ca = Claim(document_id=doc.id, claim_text="a", subject="temperature", claim_type="measurement")
    cb = Claim(document_id=doc.id, claim_text="b", subject="temperature", claim_type="measurement")
    db.add_all([ca, cb])
    db.flush()
    conflict.claim_a_id = ca.id
    conflict.claim_b_id = cb.id
    db.add(conflict)
    db.flush()

    first = evidence_service.create_evidence(db, conflict_id=conflict.id, description="Same finding", evidence_type="contextual")
    second = evidence_service.create_evidence(db, conflict_id=conflict.id, description="  same   FINDING ", evidence_type="contextual")
    db.commit()
    assert first.id == second.id
    assert db.query(Evidence).filter(Evidence.conflict_id == conflict.id).count() == 1


def test_consistency_validation_is_clean_after_run(db):
    _, inv_id = _run_demo(db)
    report = consistency_service.validate_blackboard(db, inv_id)
    assert report["ok"], report["issues"]


# --------------------------------------------------------------- traceability
def test_traceability_explains_a_record(db):
    _, inv_id = _run_demo(db)
    hyp = db.query(Hypothesis).first()
    trace = traceability_service.trace(db, "hypothesis", hyp.id, inv_id)
    assert trace["record"]["exists"]
    assert trace["record"]["label"]
    assert trace["why"], "why must explain the record's provenance"
    assert trace["relations"], "a hypothesis must be connected to its conflict/evidence"
    assert traceability_service.why(db, "hypothesis", hyp.id)


def test_trace_missing_record_reports_not_exists(db):
    data = traceability_service.trace(db, "hypothesis", 999999)
    assert data["record"]["exists"] is False


# ------------------------------------------------------------------------ API
def _load_and_complete(client) -> int:
    load = client.post("/api/demo/load").json()
    inv_id = load["investigation_id"]
    client.post(f"/api/investigations/{inv_id}/start")
    deadline = time.time() + 30
    detail = client.get(f"/api/investigations/{inv_id}").json()
    while time.time() < deadline and detail["status"] not in ("completed", "cancelled", "error"):
        time.sleep(0.3)
        detail = client.get(f"/api/investigations/{inv_id}").json()
    assert detail["status"] == "completed"
    return inv_id


def test_api_events_and_relations(client):
    inv_id = _load_and_complete(client)

    events = client.get(f"/api/blackboard/events?investigation_id={inv_id}").json()
    assert events["total"] > 0
    assert any(e["agent_name"] for e in events["items"])
    assert any(e["entity_type"] for e in events["items"])

    relations = client.get(f"/api/blackboard/relations?investigation_id={inv_id}").json()
    assert relations["total"] > 0
    assert all(r["relation_type"] for r in relations["items"])

    snapshot = client.get("/api/blackboard/snapshot").json()
    assert "recent_events" in snapshot
    assert snapshot["relation_counts"]


def test_api_trace_and_connected(client):
    inv_id = _load_and_complete(client)
    snapshot = client.get("/api/blackboard/snapshot").json()
    doc_node = next(n for n in snapshot["graph"]["nodes"] if n["node_type"] == "document")
    doc_id = int(doc_node["id"].split("-")[1])

    trace = client.get(f"/api/blackboard/trace/document/{doc_id}?investigation_id={inv_id}")
    assert trace.status_code == 200
    assert trace.json()["record"]["exists"]

    connected = client.get(f"/api/blackboard/connected/document/{doc_id}?investigation_id={inv_id}")
    assert connected.status_code == 200
    assert connected.json()


def test_api_reevaluate_endpoint(client):
    inv_id = _load_and_complete(client)
    response = client.post(f"/api/blackboard/reevaluate?investigation_id={inv_id}")
    assert response.status_code == 200
    body = response.json()
    assert "genuine" in body and "tasks" in body
