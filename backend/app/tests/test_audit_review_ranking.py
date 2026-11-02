"""Tests for the audit trail, human review and explainable hypothesis ranking."""
from __future__ import annotations

from app.blackboard.controller import InvestigationControl, InvestigationController
from app.demo import scenario
from app.models import AuditEvent, Conflict, EventLog, HumanReview, Investigation
from app.services.report_service import build_report


def _run_full(db):
    docs, inv_id = scenario.load_demo(db, auto_start=False)
    InvestigationController(db).run(inv_id, InvestigationControl())
    db.expire_all()
    return docs, inv_id


def _run_via_api(client) -> int:
    load = client.post("/api/demo/load").json()
    inv_id = load["investigation_id"]
    client.post(f"/api/investigations/{inv_id}/start")
    import time

    deadline = time.time() + 30
    detail = client.get(f"/api/investigations/{inv_id}").json()
    while time.time() < deadline and detail["status"] not in ("completed", "cancelled", "error"):
        time.sleep(0.3)
        detail = client.get(f"/api/investigations/{inv_id}").json()
    assert detail["status"] == "completed"
    return inv_id


# ------------------------------------------------------------------------- audit
def test_audit_trail_records_the_full_pipeline(db):
    _run_full(db)
    events = db.query(AuditEvent).all()
    assert events, "expected audit entries to be recorded"

    pairs = {(e.entity_type, e.action) for e in events}
    assert ("claim", "extracted") in pairs
    assert ("conflict", "created") in pairs
    assert ("hypothesis", "created") in pairs
    assert ("hypothesis", "verified") in pairs
    assert ("evidence", "created") in pairs
    assert ("conclusion", "created") in pairs

    # Agent-driven changes are attributed to the agent, not a human.
    agent_events = [e for e in events if e.entity_type in {"claim", "conflict", "conclusion"}]
    assert agent_events
    assert all(e.actor == "agent" for e in agent_events)
    # Every entry carries a timestamp.
    assert all(e.created_at is not None for e in events)


def test_audit_api_filters_by_entity_type(client):
    _run_via_api(client)
    resp = client.get("/api/audit?entity_type=conclusion")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1
    assert all(item["entity_type"] == "conclusion" for item in body["items"])
    assert body["items"][0]["detail"]["decision_type"]


# ---------------------------------------------------------------------- ranking
def test_ranking_orders_hypotheses_with_transparent_criteria(db):
    _run_full(db)
    conflict = db.query(Conflict).first()

    from app.services import ranking_service

    ranked = ranking_service.rank_hypotheses(db, conflict.id)
    assert len(ranked) >= 2
    assert [r["rank"] for r in ranked] == list(range(1, len(ranked) + 1))
    scores = [r["support_score"] for r in ranked]
    assert scores == sorted(scores, reverse=True)
    top = ranked[0]
    assert set(top["criteria"]) >= {
        "supporting_evidence_weight",
        "contradicting_evidence_weight",
        "distinct_supporting_sources",
        "has_direct_supporting_evidence",
    }
    assert "not" in top["confidence_caveat"].lower()
    assert top["supporting_evidence"], "top hypothesis should cite supporting evidence"
    ev = top["supporting_evidence"][0]
    assert {"id", "description", "weight", "document_filename"} <= set(ev)


def test_ranking_endpoint_returns_ranked_list(client):
    _run_via_api(client)
    conflict_id = client.get("/api/conflicts").json()["items"][0]["id"]
    resp = client.get(f"/api/conflicts/{conflict_id}/hypotheses/ranking")
    assert resp.status_code == 200
    ranked = resp.json()
    assert ranked
    assert ranked[0]["rank"] == 1
    assert ranked[0]["confidence_caveat"]


def test_evidence_gaps_endpoint_lists_missing_information(client):
    _run_via_api(client)
    conflict_id = client.get("/api/conflicts").json()["items"][0]["id"]
    resp = client.get(f"/api/conflicts/{conflict_id}/evidence-gaps")
    assert resp.status_code == 200
    gaps = resp.json()
    assert isinstance(gaps, list)


# ----------------------------------------------------------------------- review
def _conclusion_id(client, conflict_id: int) -> int:
    detail = client.get(f"/api/conflicts/{conflict_id}").json()
    assert detail["conclusion"] is not None
    return detail["conclusion"]["id"]


def test_review_approval_resolves_conflict_and_is_audited(client, db):
    inv_id = _run_via_api(client)
    conflict_id = client.get("/api/conflicts").json()["items"][0]["id"]
    cid = _conclusion_id(client, conflict_id)

    resp = client.post(
        f"/api/conclusions/{cid}/review",
        json={"decision": "approved", "reviewer": "Dr. Rao", "note": "Evidence is consistent."},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["conflict_status"] == "resolved"

    db.expire_all()
    conflict = db.get(Conflict, conflict_id)
    assert conflict.status == "resolved"

    review = db.query(HumanReview).filter(HumanReview.conclusion_id == cid).one()
    assert review.decision == "approved"
    assert review.reviewer == "Dr. Rao"

    audit = (
        db.query(AuditEvent)
        .filter(AuditEvent.entity_type == "human_review", AuditEvent.action == "submitted")
        .all()
    )
    assert audit and audit[-1].actor == "Dr. Rao"

    events = db.query(EventLog).filter(EventLog.event_type == "human_review_recorded").all()
    assert any(e.investigation_id == inv_id for e in events)


def test_review_rejection_reopens_conflict(client, db):
    _run_via_api(client)
    conflict_id = client.get("/api/conflicts").json()["items"][0]["id"]
    cid = _conclusion_id(client, conflict_id)

    resp = client.post(
        f"/api/conclusions/{cid}/review",
        json={"decision": "rejected", "reviewer": "Auditor", "note": "Insufficient evidence."},
    )
    assert resp.status_code == 201
    assert resp.json()["conflict_status"] == "open"
    db.expire_all()
    assert db.get(Conflict, conflict_id).status == "open"


def test_review_request_more_investigation(client, db):
    _run_via_api(client)
    conflict_id = client.get("/api/conflicts").json()["items"][0]["id"]
    cid = _conclusion_id(client, conflict_id)

    resp = client.post(
        f"/api/conclusions/{cid}/review",
        json={"decision": "request_more_investigation", "reviewer": "Auditor"},
    )
    assert resp.status_code == 201
    assert resp.json()["conflict_status"] == "human_review"


def test_review_inconclusive_sets_inconclusive_status(client, db):
    _run_via_api(client)
    conflict_id = client.get("/api/conflicts").json()["items"][0]["id"]
    cid = _conclusion_id(client, conflict_id)

    resp = client.post(
        f"/api/conclusions/{cid}/review",
        json={"decision": "inconclusive", "reviewer": "Auditor", "note": "Evidence contradictory."},
    )
    assert resp.status_code == 201
    assert resp.json()["conflict_status"] == "inconclusive"
    db.expire_all()
    assert db.get(Conflict, conflict_id).status == "inconclusive"
    review = db.query(HumanReview).filter(HumanReview.conclusion_id == cid).one()
    assert review.decision == "inconclusive"


def test_review_reopen_reopens_a_previously_reviewed_finding(client, db):
    _run_via_api(client)
    conflict_id = client.get("/api/conflicts").json()["items"][0]["id"]
    cid = _conclusion_id(client, conflict_id)

    approved = client.post(
        f"/api/conclusions/{cid}/review", json={"decision": "approved", "reviewer": "A"}
    )
    assert approved.status_code == 201
    assert approved.json()["conflict_status"] == "resolved"

    reopened = client.post(
        f"/api/conclusions/{cid}/review", json={"decision": "reopen", "reviewer": "B"}
    )
    assert reopened.status_code == 201
    assert reopened.json()["conflict_status"] == "open"

    db.expire_all()
    assert db.get(Conflict, conflict_id).status == "open"
    # History is kept: both decisions are recorded, newest carries the prior one.
    history = (
        db.query(HumanReview)
        .filter(HumanReview.conclusion_id == cid)
        .order_by(HumanReview.id)
        .all()
    )
    assert [r.decision for r in history] == ["approved", "reopen"]
    # Both reviews captured the conclusion's pre-review decision type.
    assert history[-1].previous_decision_type == history[0].previous_decision_type


def test_review_output_marks_local_manual_review(client):
    _run_via_api(client)
    conflict_id = client.get("/api/conflicts").json()["items"][0]["id"]
    cid = _conclusion_id(client, conflict_id)
    body = client.post(
        f"/api/conclusions/{cid}/review", json={"decision": "inconclusive"}
    ).json()
    assert body["review"]["review_kind"] == "local_manual_review"
    assert body["review"]["reviewer"]  # never an invented identity, defaults to a label


def test_review_rejects_invalid_decision(client):
    _run_via_api(client)
    conflict_id = client.get("/api/conflicts").json()["items"][0]["id"]
    cid = _conclusion_id(client, conflict_id)

    resp = client.post(f"/api/conclusions/{cid}/review", json={"decision": "maybe"})
    assert resp.status_code == 422


def test_reviews_are_listed_for_conclusion_and_conflict(client):
    _run_via_api(client)
    conflict_id = client.get("/api/conflicts").json()["items"][0]["id"]
    cid = _conclusion_id(client, conflict_id)
    client.post(f"/api/conclusions/{cid}/review", json={"decision": "approved", "reviewer": "R"})

    by_conclusion = client.get(f"/api/conclusions/{cid}/reviews").json()
    assert len(by_conclusion) == 1
    by_conflict = client.get(f"/api/conflicts/{conflict_id}/reviews").json()
    assert len(by_conflict) == 1


# ----------------------------------------------------------------------- report
def test_report_includes_ranking_gaps_and_review_sections(db):
    _run_full(db)
    investigation = db.query(Investigation).first()
    report = build_report(db, investigation)
    headings = {s["heading"] for s in report["sections"]}
    assert "Hypothesis Ranking" in headings
    assert "Evidence Gaps and Uncertainty" in headings
    assert "Human Review Decisions" in headings
    assert report["markdown"].count("#") > 0


def test_report_reflects_recorded_review(client):
    inv_id = _run_via_api(client)
    conflict_id = client.get("/api/conflicts").json()["items"][0]["id"]
    cid = _conclusion_id(client, conflict_id)
    client.post(
        f"/api/conclusions/{cid}/review",
        json={"decision": "approved", "reviewer": "Dr. Rao", "note": "Looks good."},
    )
    report = client.get(f"/api/investigations/{inv_id}/report").json()
    sections = {s["heading"]: s for s in report["sections"]}
    items = sections["Human Review Decisions"]["items"]
    assert any("Dr. Rao" in item and "approved" in item for item in items)
