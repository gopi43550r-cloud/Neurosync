"""Tests for the transparent multi-factor evidence assessment (spec §4)."""
from __future__ import annotations

import time

from app.blackboard.controller import InvestigationControl, InvestigationController
from app.models import Conflict, Evidence
from app.services.assessment_service import build_context, assess


def _run_sync(db) -> int:
    from app.demo import scenario

    docs, inv_id = scenario.load_demo(db, auto_start=False)
    InvestigationController(db).run(inv_id, InvestigationControl())
    db.expire_all()
    return inv_id


def _run_via_api(client) -> int:
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


def test_evidence_list_exposes_inspectable_assessment(client):
    _run_via_api(client)
    resp = client.get("/api/evidence")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert items, "expected evidence from the demo investigation"

    assessment = items[0]["assessment"]
    assert assessment is not None
    assert set(assessment["factors"]) >= {
        "relevance",
        "provenance",
        "recency",
        "completeness",
        "corroboration",
        "contradictory_evidence",
    }
    for factor in assessment["factors"].values():
        assert {"value", "label", "explanation"} <= set(factor)
    assert 0.0 <= assessment["overall_score"] <= 1.0
    assert assessment["overall_label"] in {"low", "medium", "high"}
    assert assessment["formula"]
    assert assessment["caveat"]
    assert assessment["source_reliability"]["label"] == "unknown"
    assert isinstance(assessment["missing_information"], list)


def test_conflict_detail_evidence_carries_assessment(client):
    _run_via_api(client)
    conflict_id = client.get("/api/conflicts").json()["items"][0]["id"]
    detail = client.get(f"/api/conflicts/{conflict_id}").json()
    assert detail["evidence"]
    assert detail["evidence"][0]["assessment"] is not None


def test_assessment_labels_unknown_fields_instead_of_inventing(db):
    _run_sync(db)
    conflict = db.query(Conflict).first()
    ev = Evidence(
        conflict_id=conflict.id,
        evidence_type="contextual",
        origin="document",
        description="short",
    )
    db.add(ev)
    db.commit()
    db.refresh(ev)

    ctx = build_context(db, [ev])
    assessment = assess(ev, ctx)

    assert assessment["factors"]["provenance"]["value"] == 0.30
    assert assessment["factors"]["recency"]["label"] == "unknown"
    assert any("timestamp" in m.lower() for m in assessment["missing_information"])
    assert any("source document" in m.lower() for m in assessment["missing_information"])
    assert assessment["source_reliability"]["label"] == "unknown"


def test_assessment_discounts_score_when_contradicted(db):
    from app.models import Hypothesis

    _run_sync(db)
    conflict = db.query(Conflict).first()
    hyp = Hypothesis(conflict_id=conflict.id, title="H", explanation="e")
    db.add(hyp)
    db.flush()

    supporting = Evidence(
        conflict_id=conflict.id,
        evidence_type="measurement",
        origin="document",
        description="A detailed supporting measurement for the hypothesis.",
        supports_hypothesis_id=hyp.id,
        relevance_score=0.9,
        reliability_score=0.9,
        directness=0.9,
    )
    contradicting = Evidence(
        conflict_id=conflict.id,
        evidence_type="measurement",
        origin="document",
        description="A contradicting measurement for the same hypothesis.",
        contradicts_hypothesis_id=hyp.id,
    )
    db.add_all([supporting, contradicting])
    db.commit()
    db.refresh(supporting)

    ctx = build_context(db, [supporting])
    assessment = assess(supporting, ctx)
    assert assessment["factors"]["contradictory_evidence"]["label"] == "present"
    assert assessment["overall_score"] <= 0.85  # discounted for the contradiction
