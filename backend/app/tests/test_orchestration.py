"""Orchestration tests: state-driven scheduling, retries, failure isolation,
cancellation, loop/repeat prevention, execution limits and ledger tracking.

These exercise the controller loop directly with deterministic stub agents so the
behaviour is asserted without relying on the wording or ordering of the real
agents' output.
"""
from __future__ import annotations

from app.agents.base_agent import Action, AgentContext, AgentResult, BaseAgent
from app.blackboard.blackboard_service import Blackboard
from app.blackboard.controller import InvestigationControl, InvestigationController
from app.blackboard.state import assess
from app.config import settings
from app.database import Base, SessionLocal, engine
from app.demo import scenario
from app.models import AgentActivity, Conclusion, Investigation
from app.schemas.investigation import InvestigationCreate
from app.services import document_service, investigation_service


def _make_investigation(db) -> Investigation:
    doc = document_service.create_document_from_text(
        db, "orch.txt", "Machine M-17 reached 92C; another report says 76C.", is_demo=True
    )
    document_service.process_document(db, doc)
    payload = InvestigationCreate(name="orchestration", document_ids=[doc.id], iteration_limit=50)
    return investigation_service.create_investigation(db, payload)


class _FlakyAgent(BaseAgent):
    """Fails the first ``fail_times`` executions, then succeeds once."""

    name = "Flaky"
    responsibility = "test fixture"

    def __init__(self, fail_times: int) -> None:
        self.fail_times = fail_times
        self.calls = 0
        self.done = False

    def candidates(self, bb, ctx):
        if self.done:
            return []
        return [Action(agent_name=self.name, objective="flaky-work")]

    def run(self, bb, ctx, action):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError("boom")
        self.done = True
        return AgentResult(action="flaky-work", output_summary="ok", changes={"did": 1})


class _AlwaysFailingAgent(BaseAgent):
    name = "AlwaysFails"
    responsibility = "test fixture"

    def candidates(self, bb, ctx):
        return [Action(agent_name=self.name, objective="fail")]

    def run(self, bb, ctx, action):
        raise RuntimeError("always")


class _NoChangeAgent(BaseAgent):
    """Always proposes the same action and succeeds without changing the board."""

    name = "NoChange"
    responsibility = "test fixture"

    def candidates(self, bb, ctx):
        return [Action(agent_name=self.name, objective="spin")]

    def run(self, bb, ctx, action):
        return AgentResult(action="spin", output_summary="same", changes={})


class _CancellingAgent(BaseAgent):
    name = "Canceller"
    responsibility = "test fixture"

    def __init__(self, control: InvestigationControl) -> None:
        self.control = control

    def candidates(self, bb, ctx):
        return [Action(agent_name=self.name, objective="cancel-now")]

    def run(self, bb, ctx, action):
        self.control.cancel()
        return AgentResult(action="cancel-now", output_summary="requested cancel", changes={"x": 1})


def test_state_assessment_tracks_blackboard(db):
    docs, inv_id = scenario.load_demo(db, auto_start=False)
    bb = Blackboard(db)
    inv = db.get(Investigation, inv_id)
    ctx = AgentContext(
        investigation_id=inv.id,
        document_ids=[d.id for d in inv.documents],
        conflict_ids=[c.id for c in inv.conflicts],
    )

    before = assess(bb, ctx)
    assert before.documents_total == 3
    assert before.documents_awaiting_extraction == 3
    assert before.conflicts_total == 0

    InvestigationController(db).run(inv_id, InvestigationControl())
    after = assess(bb, ctx)
    assert after.conflicts_total >= 1
    assert after.evidence_total >= 1
    assert "evidence=" in after.summary()


def test_state_attached_to_scheduler_decision(db):
    docs, inv_id = scenario.load_demo(db, auto_start=False)
    from app.agents import default_agents
    from app.blackboard.scheduler import Scheduler

    inv = db.get(Investigation, inv_id)
    ctx = AgentContext(document_ids=[d.id for d in inv.documents])
    decision = Scheduler().select(default_agents(), Blackboard(db), ctx)
    assert decision is not None
    assert decision.state is not None
    assert decision.state.documents_total == 3


def test_activity_ledger_records_sequence_and_record_ids(db):
    docs, inv_id = scenario.load_demo(db, auto_start=False)
    InvestigationController(db).run(inv_id, InvestigationControl())

    activities = (
        db.query(AgentActivity)
        .filter(AgentActivity.investigation_id == inv_id)
        .order_by(AgentActivity.sequence)
        .all()
    )
    assert activities, "expected at least one execution"
    sequences = [a.sequence for a in activities]
    assert sequences == list(range(1, len(activities) + 1))
    assert all(a.attempt >= 1 for a in activities)

    # At least one execution produced blackboard records we can point at.
    produced = [a for a in activities if a.output_record_ids not in ("[]", "", None)]
    assert produced, "expected an execution with output record ids"
    import json

    parsed = json.loads(produced[0].output_record_ids)
    assert isinstance(parsed, list) and parsed


def test_retries_then_succeeds(db):
    inv = _make_investigation(db)
    agent = _FlakyAgent(fail_times=2)
    controller = InvestigationController(db, agents=[agent])
    reason = controller.run(inv.id, InvestigationControl())

    assert reason == "no_useful_actions_remaining"
    activities = (
        db.query(AgentActivity)
        .filter(AgentActivity.investigation_id == inv.id)
        .order_by(AgentActivity.sequence)
        .all()
    )
    assert [a.status for a in activities] == ["failed", "failed", "success"]
    assert [a.attempt for a in activities] == [1, 2, 3]
    assert "RuntimeError" in activities[0].error


def test_exhausted_agent_is_parked_not_crashed(db):
    inv = _make_investigation(db)
    controller = InvestigationController(db, agents=[_AlwaysFailingAgent()])
    reason = controller.run(inv.id, InvestigationControl())

    assert reason == "no_useful_actions_remaining"
    db.refresh(inv)
    assert inv.status == "completed"  # failure isolation: no crash
    activities = db.query(AgentActivity).filter(AgentActivity.investigation_id == inv.id).all()
    # One attempt plus a bounded number of retries, every one recorded.
    assert len(activities) == settings.agent_max_retries + 1
    assert all(a.status == "failed" for a in activities)


def test_repeated_action_without_change_is_stopped(db):
    inv = _make_investigation(db)
    controller = InvestigationController(db, agents=[_NoChangeAgent()])
    reason = controller.run(inv.id, InvestigationControl())

    assert reason == "no_useful_actions_remaining"
    activities = db.query(AgentActivity).filter(AgentActivity.investigation_id == inv.id).all()
    # Guard caps identical, change-free work instead of looping forever.
    assert len(activities) == settings.max_attempts_per_action


def test_execution_limit_bounds_run(db, monkeypatch):
    monkeypatch.setattr(settings, "max_agent_executions", 1)
    inv = _make_investigation(db)
    controller = InvestigationController(db, agents=[_NoChangeAgent()])
    reason = controller.run(inv.id, InvestigationControl())

    assert reason == "execution_limit_reached"
    activities = db.query(AgentActivity).filter(AgentActivity.investigation_id == inv.id).all()
    assert len(activities) == 1


def test_cancellation_before_run(db):
    inv = _make_investigation(db)
    control = InvestigationControl()
    control.cancel()
    reason = InvestigationController(db, agents=[_NoChangeAgent()]).run(inv.id, control)

    assert reason == "cancelled_by_user"
    db.refresh(inv)
    assert inv.status == "cancelled"
    assert db.query(AgentActivity).filter(AgentActivity.investigation_id == inv.id).count() == 0


def test_cancellation_between_steps(db):
    inv = _make_investigation(db)
    control = InvestigationControl()
    reason = InvestigationController(db, agents=[_CancellingAgent(control)]).run(inv.id, control)

    assert reason == "cancelled_by_user"
    db.refresh(inv)
    assert inv.status == "cancelled"


def test_agent_manifests_expose_contracts(db):
    from app.agents import agent_manifests

    manifests = agent_manifests()
    assert len(manifests) == 6
    for m in manifests:
        assert m["name"]
        assert m["required_inputs"]
        assert m["expected_outputs"]
        assert m["run_conditions"]
        assert m["stop_conditions"]


def test_deterministic_execution_sequence():
    """The same investigation over the same data yields the same agent sequence."""

    def _fresh_run() -> list[tuple[str, str, str]]:
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        session = SessionLocal()
        try:
            _, inv_id = scenario.load_demo(session, auto_start=False)
            InvestigationController(session).run(inv_id, InvestigationControl())
            activities = (
                session.query(AgentActivity)
                .filter(AgentActivity.investigation_id == inv_id)
                .order_by(AgentActivity.sequence)
                .all()
            )
            return [(a.agent_name, a.action, a.status) for a in activities]
        finally:
            session.close()

    first = _fresh_run()
    second = _fresh_run()
    assert first == second
    assert first, "expected a non-empty execution sequence"


def test_full_investigation_still_concludes(db):
    docs, inv_id = scenario.load_demo(db, auto_start=False)
    InvestigationController(db).run(inv_id, InvestigationControl())
    assert db.query(Conclusion).count() >= 1
