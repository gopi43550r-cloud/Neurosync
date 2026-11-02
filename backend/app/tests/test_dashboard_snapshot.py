"""Tests for the dashboard snapshot filters and distributions (spec §9)."""
from __future__ import annotations

import time


def _run_demo_investigation(client) -> None:
    load = client.post("/api/demo/load").json()
    inv_id = load["investigation_id"]
    client.post(f"/api/investigations/{inv_id}/start")
    deadline = time.time() + 30
    detail = client.get(f"/api/investigations/{inv_id}").json()
    while time.time() < deadline and detail["status"] not in ("completed", "cancelled", "error"):
        time.sleep(0.3)
        detail = client.get(f"/api/investigations/{inv_id}").json()
    assert detail["status"] == "completed"


def test_snapshot_includes_status_and_category_distributions(client):
    client.post("/api/demo/load")
    resp = client.get("/api/blackboard/snapshot")
    assert resp.status_code == 200
    snapshot = resp.json()

    for key in (
        "conflict_type_distribution",
        "conflict_status_distribution",
        "investigation_status_distribution",
        "evidence_verification_distribution",
    ):
        assert key in snapshot, f"missing {key}"
        assert isinstance(snapshot[key], list)
        assert all({"value", "count"} <= set(entry) for entry in snapshot[key])

    # All known enum values are returned (zero counts included) so the UI can
    # offer a stable set of filter options.
    conflict_types = {entry["value"] for entry in snapshot["conflict_type_distribution"]}
    assert "numerical_disagreement" in conflict_types
    assert "temporal_inconsistency" in conflict_types
    statuses = {entry["value"] for entry in snapshot["investigation_status_distribution"]}
    assert "completed" in statuses


def test_snapshot_date_range_controls_activity_timeline(client):
    client.post("/api/demo/load")
    short = client.get("/api/blackboard/snapshot?days=7").json()
    long = client.get("/api/blackboard/snapshot?days=30").json()
    assert short["window_days"] == 7
    assert long["window_days"] == 30
    assert len(short["activity_timeline"]) == 7
    assert len(long["activity_timeline"]) == 30


def test_snapshot_window_days_defaults_to_14(client):
    client.post("/api/demo/load")
    snapshot = client.get("/api/blackboard/snapshot").json()
    assert snapshot["window_days"] == 14
    assert len(snapshot["activity_timeline"]) == 14


def test_snapshot_rejects_invalid_date_range(client):
    assert client.get("/api/blackboard/snapshot?days=0").status_code == 422
    assert client.get("/api/blackboard/snapshot?days=9999").status_code == 422


def test_snapshot_counts_are_from_database(client):
    empty = client.get("/api/blackboard/snapshot").json()["counts"]
    assert empty["documents"] == 0 and empty["conflicts"] == 0
    _run_demo_investigation(client)
    loaded = client.get("/api/blackboard/snapshot").json()["counts"]
    assert loaded["documents"] > 0
    assert loaded["conflicts"] > 0
