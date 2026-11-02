"""Demonstration scenario (Machine M-17) and human-review escalation tests.

These tests exercise the full blackboard pipeline on the shipped demo scenario:
two reports disagree about machine M-17's temperature at the same time (92C vs
76C) and a later maintenance log records a sensor recalibration. The pipeline
must surface the disagreement, propose multiple competing explanations including
a sensor/calibration one, treat the recalibration as contextual (not conclusive)
evidence, and escalate the unresolved conflict for human review.
"""
from __future__ import annotations

import time

from app.agents import EvidenceCollector
from app.agents.base_agent import AgentContext
from app.blackboard.blackboard_service import Blackboard
from app.blackboard.controller import InvestigationControl, InvestigationController
from app.demo import scenario
from app.models import Claim, Conclusion, Conflict, Evidence, Hypothesis, Investigation
from app.services.report_service import build_report


def _run_full(db):
    docs, inv_id = scenario.load_demo(db, auto_start=False)
    InvestigationController(db).run(inv_id, InvestigationControl())
    db.expire_all()
    return docs, inv_id


def _collect_claims(db, docs, inv_id):
    bb = Blackboard(db)
    ctx = AgentContext(document_ids=[d.id for d in docs], investigation_id=inv_id, min_evidence=1)
    agent = EvidenceCollector()
    actions = agent.candidates(bb, ctx)
    assert actions
    agent.safe_run(bb, ctx, actions[0])


def test_demo_loads_m17_measurements_at_same_time(db):
    docs, inv_id = scenario.load_demo(db, auto_start=False)
    _collect_claims(db, docs, inv_id)
    measurements = db.query(Claim).filter(Claim.claim_type == "measurement").all()
    values = {m.numeric_value for m in measurements}
    assert 92.0 in values and 76.0 in values
    # Both readings are timestamped 10:00 -> contemporaneous disagreement.
    for m in measurements:
        assert m.timestamp_value is not None
        assert m.timestamp_value.hour == 10 and m.timestamp_value.minute == 0


def test_full_run_produces_single_numerical_conflict(db):
    _, inv_id = _run_full(db)
    conflicts = db.query(Conflict).all()
    assert len(conflicts) == 1
    assert conflicts[0].conflict_type == "numerical_disagreement"
    assert conflicts[0].severity == "medium"


def test_conflict_is_linked_to_its_investigation(db):
    _, inv_id = _run_full(db)
    inv = db.get(Investigation, inv_id)
    conflict = db.query(Conflict).first()
    # Regression: agent-discovered conflicts must be associated with the
    # investigation so reports/stats/detail views include them.
    assert conflict.id in {c.id for c in inv.conflicts}


def test_multiple_competing_hypotheses_including_sensor(db):
    _, inv_id = _run_full(db)
    hyps = db.query(Hypothesis).all()
    assert len(hyps) >= 3
    titles = " | ".join(h.title.lower() for h in hyps)
    assert "sensor" in titles or "calibration" in titles or "measurement-source" in titles


def test_conflicting_claims_recorded_without_attributing_a_cause(db):
    _, inv_id = _run_full(db)
    seeded = [
        e
        for e in db.query(Evidence).all()
        if "Claim A states" in e.description or "Claim B states" in e.description
    ]
    assert seeded, "the raw conflicting claims should be recorded with provenance"
    assert all(e.supports_hypothesis_id is None for e in seeded)


def test_recalibration_is_contextual_not_conclusive_evidence(db):
    _, inv_id = _run_full(db)
    calibration = db.query(Evidence).filter(Evidence.evidence_type == "calibration_record").all()
    assert calibration, "the recalibration must be discovered from the maintenance log"
    assert all(e.document_id for e in calibration)
    # A single-source calibration record must not independently confirm the
    # sensor explanation; it is contextual and needs review.
    sensor = next(h for h in db.query(Hypothesis).all() if "sensor" in h.title.lower())
    assert sensor.status == "review_required"


def test_equal_timestamps_do_not_create_false_difference_evidence(db):
    _, inv_id = _run_full(db)
    ts_evidence = db.query(Evidence).filter(Evidence.evidence_type == "timestamp").all()
    assert ts_evidence == []


def test_decision_escalates_unresolved_conflict_to_human_review(db):
    _, inv_id = _run_full(db)
    conclusions = db.query(Conclusion).all()
    assert conclusions
    assert conclusions[0].decision_type == "human_review_required"
    assert db.query(Conflict).first().status == "human_review"


def test_report_routes_conflict_to_human_review(db):
    _, inv_id = _run_full(db)
    inv = db.get(Investigation, inv_id)
    report = build_report(db, inv)
    sections = {s["heading"]: s for s in report["sections"]}
    assert sections["Conflicting Claims"]["body"].startswith("1 ")
    assert any("human review" in item.lower() for item in sections["Human Review Notes"]["items"])
    assert any("human reviewer" in item.lower() for item in sections["Recommended Next Steps"]["items"])


def test_api_reports_conflict_and_human_review(client):
    load = client.post("/api/demo/load").json()
    inv_id = load["investigation_id"]
    client.post(f"/api/investigations/{inv_id}/start")

    deadline = time.time() + 30
    detail = client.get(f"/api/investigations/{inv_id}").json()
    while time.time() < deadline and detail["status"] not in ("completed", "cancelled", "error"):
        time.sleep(0.3)
        detail = client.get(f"/api/investigations/{inv_id}").json()

    assert detail["status"] == "completed"
    assert detail["conflict_count"] == 1
    assert detail["conclusion_count"] >= 1

    snapshot = client.get("/api/blackboard/snapshot").json()
    assert snapshot["counts"]["human_review_requests"] >= 1

    report = client.get(f"/api/investigations/{inv_id}/report").json()
    headings = {s["heading"] for s in report["sections"]}
    assert "Human Review Notes" in headings
