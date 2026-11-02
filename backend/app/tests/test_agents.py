"""Agent behaviour and failure-handling tests."""
from __future__ import annotations

from app.agents import (
    ConflictDetector,
    DecisionAgent,
    EvidenceCollector,
    HypothesisGenerator,
    Investigator,
    VerificationAgent,
)
from app.agents.base_agent import Action, AgentContext, AgentResult, BaseAgent
from app.blackboard.blackboard_service import Blackboard
from app.demo import scenario
from app.models import Claim, Conflict, Evidence, Hypothesis


def _load(db):
    docs, inv_id = scenario.load_demo(db, auto_start=False)
    ctx = AgentContext(document_ids=[d.id for d in docs], min_evidence=1)
    return docs, ctx


def test_evidence_collector_extracts_claims(db):
    docs, ctx = _load(db)
    bb = Blackboard(db)
    agent = EvidenceCollector()
    actions = agent.candidates(bb, ctx)
    assert actions, "collector should have work to do"
    result = agent.safe_run(bb, ctx, actions[0])
    assert result.status == "success"
    claims = db.query(Claim).all()
    assert len(claims) > 0
    # Provenance preserved.
    assert all(c.source_reference for c in claims)
    assert all(c.document_id for c in claims)


def test_conflict_detector_finds_meaningful_conflicts(db):
    docs, ctx = _load(db)
    bb = Blackboard(db)
    EvidenceCollector().safe_run(bb, ctx, EvidenceCollector().candidates(bb, ctx)[0])
    det = ConflictDetector()
    result = det.safe_run(bb, ctx, det.candidates(bb, ctx)[0])
    assert result.status == "success"
    conflicts = db.query(Conflict).all()
    types = {c.conflict_type for c in conflicts}
    assert "temporal_inconsistency" in types or "numerical_disagreement" in types
    # Running again must not duplicate.
    det.safe_run(bb, ctx, det.candidates(bb, ctx)[0])
    assert db.query(Conflict).count() == len(conflicts)


def test_hypothesis_generator_creates_multiple(db):
    docs, ctx = _load(db)
    bb = Blackboard(db)
    EvidenceCollector().safe_run(bb, ctx, EvidenceCollector().candidates(bb, ctx)[0])
    ConflictDetector().safe_run(bb, ctx, ConflictDetector().candidates(bb, ctx)[0])
    gen = HypothesisGenerator()
    actions = gen.candidates(bb, ctx)
    assert actions
    gen.safe_run(bb, ctx, actions[0])
    conflict_id = actions[0].conflict_id
    hyps = db.query(Hypothesis).filter(Hypothesis.conflict_id == conflict_id).all()
    assert len(hyps) >= 3


def test_investigator_finds_calibration_evidence(db):
    docs, ctx = _load(db)
    bb = Blackboard(db)
    EvidenceCollector().safe_run(bb, ctx, EvidenceCollector().candidates(bb, ctx)[0])
    ConflictDetector().safe_run(bb, ctx, ConflictDetector().candidates(bb, ctx)[0])
    for action in HypothesisGenerator().candidates(bb, ctx):
        HypothesisGenerator().safe_run(bb, ctx, action)
    inv = Investigator()
    actions = inv.candidates(bb, ctx)
    assert actions
    for action in actions:
        inv.safe_run(bb, ctx, action)
    calibration = db.query(Evidence).filter(Evidence.evidence_type == "calibration_record").all()
    assert calibration, "calibration record should be discovered from Report C"
    # Provenance must reference an actual document.
    assert all(e.document_id for e in calibration)


def test_verification_and_decision(db):
    docs, ctx = _load(db)
    bb = Blackboard(db)
    EvidenceCollector().safe_run(bb, ctx, EvidenceCollector().candidates(bb, ctx)[0])
    ConflictDetector().safe_run(bb, ctx, ConflictDetector().candidates(bb, ctx)[0])
    for a in HypothesisGenerator().candidates(bb, ctx):
        HypothesisGenerator().safe_run(bb, ctx, a)
    for a in Investigator().candidates(bb, ctx):
        Investigator().safe_run(bb, ctx, a)

    ver = VerificationAgent()
    for a in ver.candidates(bb, ctx):
        ver.safe_run(bb, ctx, a)
    hyps = db.query(Hypothesis).all()
    assert hyps
    assert all(h.status != "proposed" for h in hyps)

    dec = DecisionAgent()
    for a in dec.candidates(bb, ctx):
        dec.safe_run(bb, ctx, a)
    from app.models import Conclusion

    conclusions = db.query(Conclusion).all()
    assert conclusions
    assert conclusions[0].decision_type  # a decision type was recorded


class _ExplodingAgent(BaseAgent):
    name = "Exploding"
    responsibility = "always fails"

    def candidates(self, bb, ctx):
        return [Action(agent_name=self.name, objective="boom")]

    def run(self, bb, ctx, action):
        raise RuntimeError("boom")


def test_agent_failure_is_isolated(db):
    bb = Blackboard(db)
    result = _ExplodingAgent().safe_run(bb, AgentContext(), Action(agent_name="Exploding", objective="boom"))
    assert isinstance(result, AgentResult)
    assert result.status == "failed"
    assert "boom" in (result.error or "").lower() or result.error
