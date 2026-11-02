"""Tests for in-app OpenAI-compatible API-key management.

The key must never be echoed back, must be validated before it reaches the
dotenv file, and must apply to the running process immediately. Tests redirect
the managed env file to a temporary path so the real ``backend/.env.local`` is
never touched.
"""
from __future__ import annotations

import pytest

from app.config import settings
from app.services import llm_settings_service

VALID_KEY = "sk-test-1234567890abcdef"


@pytest.fixture()
def managed_env(tmp_path, monkeypatch):
    path = tmp_path / ".env.local"
    monkeypatch.setenv("NEUROSYNC_LLM_ENV_FILE", str(path))
    original = (
        settings.openai_api_key,
        settings.openai_model,
        settings.openai_base_url,
        settings.enable_llm,
    )
    try:
        yield path
    finally:
        (
            settings.openai_api_key,
            settings.openai_model,
            settings.openai_base_url,
            settings.enable_llm,
        ) = original


def test_status_without_key(client, managed_env):
    resp = client.get("/api/settings/llm")
    assert resp.status_code == 200
    body = resp.json()
    assert body["configured"] is False
    assert body["active"] is False
    assert body["source"] == "none"
    assert body["key_hint"] is None
    assert body["enable_llm"] is False or body["enable_llm"] is True
    assert "no openai api key" in body["note"].lower()
    assert not managed_env.exists()


def test_save_key_is_masked_and_applied_immediately(client, managed_env):
    resp = client.put(
        "/api/settings/llm",
        json={
            "api_key": VALID_KEY,
            "model": "gpt-4o-mini",
            "base_url": "https://api.example.com/v1",
            "enable_llm": True,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["configured"] is True
    assert body["active"] is True
    assert body["source"] == "saved"
    assert body["key_hint"] == "\u2022\u2022\u2022\u2022cdef"
    assert VALID_KEY not in resp.text
    assert body["model"] == "gpt-4o-mini"
    assert body["base_url"] == "https://api.example.com/v1"
    assert body["enable_llm"] is True

    # Applied to the running process without a restart.
    assert settings.openai_api_key == VALID_KEY
    assert settings.enable_llm is True
    assert settings.llm_configured is True

    # Persisted, with no secret in the response.
    text = managed_env.read_text(encoding="utf-8")
    assert f"OPENAI_API_KEY={VALID_KEY}" in text
    assert "ENABLE_LLM=true" in text

    # Other status endpoints now report a configured provider.
    assert client.get("/api/settings/reasoning").json()["llm_configured"] is True
    assert client.get("/api/health").json()["ai_configured"] is True

    status = client.get("/api/settings/llm").json()
    assert status["configured"] is True
    assert VALID_KEY not in str(status)


def test_update_without_key_keeps_existing_key(client, managed_env):
    client.put("/api/settings/llm", json={"api_key": VALID_KEY})
    resp = client.put("/api/settings/llm", json={"model": "gpt-4.1-mini"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["configured"] is True
    assert body["model"] == "gpt-4.1-mini"
    assert settings.openai_api_key == VALID_KEY
    assert f"OPENAI_API_KEY={VALID_KEY}" in managed_env.read_text(encoding="utf-8")


def test_clear_key_removes_managed_secret(client, managed_env):
    client.put("/api/settings/llm", json={"api_key": VALID_KEY})
    resp = client.delete("/api/settings/llm/key")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["configured"] is False
    assert body["active"] is False
    assert settings.openai_api_key == ""
    assert settings.enable_llm is False
    assert "OPENAI_API_KEY=\n" in managed_env.read_text(encoding="utf-8")
    assert client.get("/api/health").json()["ai_configured"] is False


@pytest.mark.parametrize(
    "bad_key",
    [
        "short",
        "sk-test with spaces 12345678",
        "sk-test\nINJECTED=1",
        "sk-test'quote'12345678",
        "sk-test;rm-12345678",
    ],
)
def test_rejects_invalid_keys(client, managed_env, bad_key):
    resp = client.put("/api/settings/llm", json={"api_key": bad_key})
    assert resp.status_code == 422
    assert settings.openai_api_key == ""
    assert not managed_env.exists()


@pytest.mark.parametrize(
    "bad_url",
    [
        "ftp://example.com/v1",
        "https://user:pass@example.com/v1",
        "https://example.com/v1?token=abc",
        "https://example.com/v1#fragment",
        "not a url",
    ],
)
def test_rejects_invalid_base_urls(client, managed_env, bad_url):
    resp = client.put(
        "/api/settings/llm", json={"api_key": VALID_KEY, "base_url": bad_url}
    )
    assert resp.status_code == 422
    assert not managed_env.exists()


def test_requires_a_key_on_first_configuration(client, managed_env):
    resp = client.put("/api/settings/llm", json={"model": "gpt-4o-mini"})
    assert resp.status_code == 422
    assert not managed_env.exists()


def test_preserves_unrelated_env_lines_and_comments(client, managed_env):
    managed_env.write_text(
        "# operator note\nOTHER_SETTING=1\nOPENAI_API_KEY=old-key-12345678\n",
        encoding="utf-8",
    )
    resp = client.put("/api/settings/llm", json={"api_key": VALID_KEY})
    assert resp.status_code == 200
    text = managed_env.read_text(encoding="utf-8")
    assert "# operator note" in text
    assert "OTHER_SETTING=1" in text
    assert text.count("OPENAI_API_KEY=") == 1
    assert f"OPENAI_API_KEY={VALID_KEY}" in text


def test_key_management_blocked_on_unauthenticated_production(
    client, managed_env, monkeypatch
):
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "api_token", "")

    resp = client.put("/api/settings/llm", json={"api_key": VALID_KEY})
    assert resp.status_code == 403
    assert settings.openai_api_key == ""
    assert not managed_env.exists()

    resp = client.delete("/api/settings/llm/key")
    assert resp.status_code == 403

    # Reads are still allowed and do not reveal a secret.
    resp = client.get("/api/settings/llm")
    assert resp.status_code == 200


def test_authenticated_production_allows_key_management(
    client, managed_env, monkeypatch
):
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "api_token", "test-token")
    # The auth middleware reads the token per request; send it as a bearer.
    resp = client.put(
        "/api/settings/llm",
        json={"api_key": VALID_KEY},
        headers={"Authorization": "Bearer test-token"},
    )
    assert resp.status_code == 200, resp.text
    assert settings.openai_api_key == VALID_KEY


def test_selecting_ai_after_saving_key_activates_provider(client, managed_env):
    client.put("/api/settings/llm", json={"api_key": VALID_KEY})
    resp = client.put("/api/settings/reasoning", json={"mode": "ai_assisted"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["reasoning_mode"] == "ai_assisted"
    assert body["effective_mode"] == "ai_assisted"
    assert body["llm_configured"] is True
    assert client.get("/api/health").json()["mode"] == "ai"


def test_hint_never_contains_the_full_key(client, managed_env):
    client.put("/api/settings/llm", json={"api_key": "sk-abcdefghijklmnop"})
    for path in ("/api/settings/llm", "/api/settings/reasoning", "/api/health", "/api/config"):
        assert "sk-abcdefghijklmnop" not in client.get(path).text
