"""Reasoning-mode settings endpoint tests (no provider configured)."""
from __future__ import annotations


def test_reasoning_defaults_to_deterministic(client):
    resp = client.get("/api/settings/reasoning")
    assert resp.status_code == 200
    body = resp.json()
    assert body["reasoning_mode"] == "deterministic"
    assert body["effective_mode"] == "deterministic"
    assert body["llm_configured"] is False
    assert set(body["available_modes"]) == {"deterministic", "ai_assisted"}


def test_selecting_ai_without_provider_degrades_with_note(client):
    resp = client.put("/api/settings/reasoning", json={"mode": "ai_assisted"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["reasoning_mode"] == "ai_assisted"  # preference is remembered
    assert body["effective_mode"] == "deterministic"  # but degrades
    assert "no provider" in body["note"].lower() or "not configured" in body["note"].lower()

    # It is persisted.
    again = client.get("/api/settings/reasoning").json()
    assert again["reasoning_mode"] == "ai_assisted"


def test_invalid_mode_rejected(client):
    resp = client.put("/api/settings/reasoning", json={"mode": "telepathy"})
    assert resp.status_code == 422


def test_health_reports_reasoning_mode(client):
    body = client.get("/api/health").json()
    assert body["mode"] == "demonstration"
    assert body["effective_mode"] == "deterministic"
    assert body["ai_configured"] is False
