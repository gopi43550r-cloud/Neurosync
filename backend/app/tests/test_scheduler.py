"""Scheduler and controller tests."""
from __future__ import annotations

from app.agents.base_agent import Action, AgentContext, BaseAgent
from app.blackboard.blackboard_service import Blackboard
from app.blackboard.controller import InvestigationControl, InvestigationController, registry
from app.blackboard.scheduler import Scheduler
from app.demo import scenario
from app.models import Investigation
from app.schemas.investigation import InvestigationCreate
from app.services import investigation_service


class _StubAgent(BaseAgent):
    def __init__(self, name, actions):
        self.name = name
        self.responsibility = "stub"
        self._actions = actions

    def candidates(self, bb, ctx):
        return self._actions

    def run(self, bb, ctx, action):
        from app.agents.base_agent import AgentResult

        return AgentResult(action=action.objective, output_summary="ok")


def test_selects_highest_priority(db):
    bb = Blackboard(db)
    low = Action(agent_name="A", objective="low", severity="low", uncertainty=0.1, evidence_gap=0.1, info_gain=0.1, cost=0.5)
    high = Action(agent_name="B", objective="high", severity="critical", uncertainty=0.9, evidence_gap=0.9, info_gain=0.9, cost=0.0)
    agent_a = _StubAgent("A", [low])
    agent_b = _StubAgent("B", [high])
    decision = Scheduler().select([agent_a, agent_b], bb, AgentContext())
    assert decision is not None
    assert decision.action.agent_name == "B"
    assert 0 <= decision.priority <= 100


def test_respects_iteration_limit(db):
    docs, inv_id = scenario.load_demo(db, auto_start=False)
    inv = db.get(Investigation, inv_id)
    inv.iteration_limit = 1
    db.commit()
    controller = InvestigationController(db)
    reason = controller.run(inv_id, InvestigationControl())
    db.refresh(inv)
    assert inv.iteration_count <= 1
    assert reason in ("iteration_limit_reached", "no_useful_actions_remaining")


def test_stops_when_no_useful_actions(db):
    from app.services.document_service import create_document_from_text, process_document

    doc = create_document_from_text(db, "single.txt", "The machine is operating normally.", is_demo=True)
    process_document(db, doc)
    payload = InvestigationCreate(name="no conflicts", document_ids=[doc.id])
    inv = investigation_service.create_investigation(db, payload)
    controller = InvestigationController(db)
    reason = controller.run(inv.id, InvestigationControl())
    assert reason in ("no_useful_actions_remaining", "no_unresolved_conflicts", "investigation_converged")


def test_duplicate_simultaneous_prevention():
    control = registry.register(999)
    assert control is not None
    assert registry.register(999) is None
    registry.release(999)
    assert registry.register(999) is not None
    registry.release(999)


def test_full_investigation_produces_conclusion(db):
    docs, inv_id = scenario.load_demo(db, auto_start=False)
    controller = InvestigationController(db)
    controller.run(inv_id, InvestigationControl())
    inv = db.get(Investigation, inv_id)
    assert inv.status in ("completed", "cancelled", "error")
    assert inv.iteration_count >= 1
    from app.models import Conclusion

    assert db.query(Conclusion).count() >= 1
