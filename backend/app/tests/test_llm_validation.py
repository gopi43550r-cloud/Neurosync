"""LLM validation tests: the deterministic pipeline must never trust model
output blindly. Ungrounded quotes and fabricated citations are discarded.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agents.hypothesis_generator import HypothesisGenerator
from app.models import Claim, Document, DocumentContent
from app.services import document_service, llm_service as llm_module
from app.services.llm_service import LLMProvider


class FakeProvider(LLMProvider):
    name = "fake"

    def __init__(self, responses):
        self.responses = list(responses)

    @property
    def available(self):
        return True

    def chat(self, system, user, *, max_tokens, json_mode):
        return self.responses.pop(0) if self.responses else None


@pytest.fixture()
def use_fake_llm():
    original = llm_module.llm_service.provider

    def _install(*responses):
        llm_module.llm_service.set_provider(FakeProvider(list(responses)))

    yield _install
    llm_module.llm_service.set_provider(original)


def _make_doc(db, text: str) -> Document:
    doc = document_service.create_document_from_text(db, "Report_A.txt", text, is_demo=True)
    document_service.process_document(db, doc, extract=False)
    return doc


# --------------------------------------------------------- claim extraction grounding
def test_llm_claim_kept_when_grounded(db, use_fake_llm):
    doc = _make_doc(db, "Machine M-17 reached a temperature of 92 degrees at 10:00 AM.")
    use_fake_llm(
        '{"claims":[{"claim_text":"Machine M-17 reached 92 degrees",'
        '"subject":"temperature","predicate":"measured_value","claim_type":"measurement",'
        '"evidence_quote":"reached a temperature of 92 degrees"}]}'
    )
    added = document_service.augment_document_with_llm(db, doc)
    assert added == 1
    claim = db.query(Claim).filter(Claim.document_id == doc.id).first()
    assert "llm" in (claim.meta or "")


def test_llm_claim_dropped_when_ungrounded(db, use_fake_llm):
    doc = _make_doc(db, "Machine M-17 reached a temperature of 92 degrees at 10:00 AM.")
    use_fake_llm(
        '{"claims":[{"claim_text":"The machine exploded",'
        '"subject":"machine","evidence_quote":"the machine exploded catastrophically"}]}'
    )
    added = document_service.augment_document_with_llm(db, doc)
    assert added == 0
    assert db.query(Claim).filter(Claim.document_id == doc.id).count() == 0


def test_llm_claim_deduplicated(db, use_fake_llm):
    doc = _make_doc(db, "Machine M-17 reached a temperature of 92 degrees at 10:00 AM.")
    payload = (
        '{"claims":[{"claim_text":"Machine M-17 reached a temperature of 92 degrees",'
        '"subject":"temperature","evidence_quote":"reached a temperature of 92 degrees"}]}'
    )
    use_fake_llm(payload, payload)
    assert document_service.augment_document_with_llm(db, doc) == 1
    assert document_service.augment_document_with_llm(db, doc) == 0


# --------------------------------------------------------- hypothesis grounding filter
def test_hypotheses_drop_fabricated_quotes(use_fake_llm):
    use_fake_llm(
        '{"hypotheses":[{"title":"Sensor drift","explanation":"Drift explains it.",'
        '"assumptions":["a"],"missing_information":["m"],'
        '"supporting_quotes":["92\\u00b0C at 10:00 AM","the reactor melted down"]}]}'
    )
    ctx = SimpleNamespace(enable_llm=True)
    conflict = SimpleNamespace(conflict_type="numerical_disagreement")
    claim_a = SimpleNamespace(claim_text="Machine reached 92°C at 10:00 AM")
    claim_b = SimpleNamespace(claim_text="Machine reached 76°C at 10:00 AM")

    seeds, used_llm = HypothesisGenerator()._propose(None, ctx, conflict, claim_a, claim_b)
    assert used_llm is True
    assert len(seeds) == 1
    assert seeds[0]["origin"] == "llm"
    # The fabricated quote is removed; the grounded one survives.
    assert seeds[0]["grounded_quotes"] == ["92°C at 10:00 AM"]


def test_hypotheses_fall_back_when_llm_invalid(use_fake_llm):
    use_fake_llm("not json")
    ctx = SimpleNamespace(enable_llm=True)
    conflict = SimpleNamespace(conflict_type="numerical_disagreement")
    claim_a = SimpleNamespace(claim_text="A")
    claim_b = SimpleNamespace(claim_text="B")

    seeds, used_llm = HypothesisGenerator()._propose(None, ctx, conflict, claim_a, claim_b)
    assert used_llm is False
    assert len(seeds) >= 1
    assert all(s["origin"] == "agent" for s in seeds)


def test_hypotheses_generator_is_deterministic_when_disabled(use_fake_llm):
    # Provider returns an empty-list payload, but enable_llm is False so it is unused.
    use_fake_llm('{"hypotheses":[]}')
    ctx = SimpleNamespace(enable_llm=False)
    conflict = SimpleNamespace(conflict_type="temporal_inconsistency")
    claim_a = SimpleNamespace(claim_text="A")
    claim_b = SimpleNamespace(claim_text="B")
    seeds, used_llm = HypothesisGenerator()._propose(None, ctx, conflict, claim_a, claim_b)
    assert used_llm is False
    assert len(seeds) >= 1
