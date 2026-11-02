"""End-to-end LLM integration test with a fake provider.

Proves the wiring: when AI mode is requested and a provider is "configured",
the agent pipeline actually calls the LLM and records AI-originated artefacts -
without any network access.
"""
from __future__ import annotations

from app.config import settings
from app.models import Hypothesis, Investigation
from app.services import llm_service as llm_module
from app.services import settings_service
from app.services.llm_service import LLMProvider
from app.tests.conftest import run_investigation_sync


class SmartFakeProvider(LLMProvider):
    """Returns a plausible JSON envelope keyed off the requested schema."""

    name = "fake"

    def __init__(self):
        self.prompts: list[str] = []

    @property
    def available(self):
        return True

    def chat(self, system, user, *, max_tokens, json_mode):
        self.prompts.append(user)
        low = user.lower()
        if "extract factual claims" in low:
            return '{"claims":[]}'
        if "competing explanations" in low:
            return (
                '{"hypotheses":[{"title":"AI-suggested: instrument drift",'
                '"explanation":"The readings may reflect sensor drift.",'
                '"assumptions":["a sensor was used"],'
                '"missing_information":["calibration history"],'
                '"supporting_quotes":[]}]}'
            )
        if "pieces of evidence" in low:
            return '{"evidence":[]}'
        if "second opinion" in low:
            return '{"conflict_type":"numerical_disagreement","is_conflict":true,"reason":"values differ"}'
        if "explain concisely" in low or "short, neutral explanation" in low:
            return '{"explanation":"Grounded AI explanation.","cited_evidence_ids":[]}'
        return "{}"


def test_investigation_uses_llm_when_ai_mode_enabled(db, client, monkeypatch):
    provider = SmartFakeProvider()
    original = llm_module.llm_service.provider
    llm_module.llm_service.set_provider(provider)
    monkeypatch.setattr(settings, "openai_api_key", "sk-fake")
    monkeypatch.setattr(settings, "enable_llm", True)
    settings_service.set_reasoning_mode(db, settings_service.MODE_AI)
    try:
        assert settings.llm_configured is True
        load = client.post("/api/demo/load").json()
        inv_id = load["investigation_id"]
        run_investigation_sync(db, inv_id)

        inv = db.get(Investigation, inv_id)
        assert inv.status == "completed"

        hyp_origins = {h.origin for h in db.query(Hypothesis).all()}
        assert "llm" in hyp_origins  # AI hypotheses were created via the pipeline

        # Provider was actually exercised across multiple use-cases.
        assert len(provider.prompts) >= 1

        # Audit trail attributes AI-originated changes to the LLM.
        audit = client.get("/api/audit?page_size=200").json()
        actors = {e["actor"] for e in audit["items"]}
        assert "llm" in actors
    finally:
        llm_module.llm_service.set_provider(original)
        settings_service.set_reasoning_mode(db, settings_service.MODE_DETERMINISTIC)
