"""Blackboard service: the shared workspace every agent reads from and writes to.

The blackboard wraps a SQLAlchemy session and exposes typed helpers for each
knowledge category (documents, observations, claims, conflicts, evidence,
hypotheses, investigations, conclusions) plus a snapshot/graph builder used by
the dashboard. It is the single source of truth for an investigation.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    AgentActivity,
    AuditEvent,
    Claim,
    Conclusion,
    Conflict,
    Document,
    Evidence,
    HumanReview,
    Hypothesis,
    Investigation,
    Observation,
)


class Blackboard:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------ reads
    def documents(self, ids: list[int] | None = None) -> list[Document]:
        stmt = select(Document)
        if ids:
            stmt = stmt.where(Document.id.in_(ids))
        return list(self.db.execute(stmt).scalars())

    def observations(self, document_ids: list[int] | None = None) -> list[Observation]:
        stmt = select(Observation)
        if document_ids:
            stmt = stmt.where(Observation.document_id.in_(document_ids))
        return list(self.db.execute(stmt).scalars())

    def claims(self, document_ids: list[int] | None = None) -> list[Claim]:
        stmt = select(Claim).order_by(Claim.id)
        if document_ids:
            stmt = stmt.where(Claim.document_id.in_(document_ids))
        return list(self.db.execute(stmt).scalars())

    def conflicts(self, ids: list[int] | None = None, statuses: list[str] | None = None) -> list[Conflict]:
        stmt = select(Conflict).order_by(Conflict.id)
        if ids:
            stmt = stmt.where(Conflict.id.in_(ids))
        if statuses:
            stmt = stmt.where(Conflict.status.in_(statuses))
        return list(self.db.execute(stmt).scalars())

    def evidence(self, conflict_id: int | None = None) -> list[Evidence]:
        stmt = select(Evidence).order_by(Evidence.id)
        if conflict_id is not None:
            stmt = stmt.where(Evidence.conflict_id == conflict_id)
        return list(self.db.execute(stmt).scalars())

    def hypotheses(self, conflict_id: int | None = None) -> list[Hypothesis]:
        stmt = select(Hypothesis).order_by(Hypothesis.id)
        if conflict_id is not None:
            stmt = stmt.where(Hypothesis.conflict_id == conflict_id)
        return list(self.db.execute(stmt).scalars())

    def hypotheses_for(self, conflict_ids: list[int]) -> list[Hypothesis]:
        if not conflict_ids:
            return []
        return list(
            self.db.execute(
                select(Hypothesis)
                .where(Hypothesis.conflict_id.in_(conflict_ids))
                .order_by(Hypothesis.id)
            ).scalars()
        )

    def evidence_for(self, conflict_ids: list[int]) -> list[Evidence]:
        if not conflict_ids:
            return []
        return list(
            self.db.execute(
                select(Evidence)
                .where(Evidence.conflict_id.in_(conflict_ids))
                .order_by(Evidence.id)
            ).scalars()
        )

    def conclusions(self, investigation_id: int | None = None) -> list[Conclusion]:
        stmt = select(Conclusion).order_by(Conclusion.id)
        if investigation_id is not None:
            stmt = stmt.where(Conclusion.investigation_id == investigation_id)
        return list(self.db.execute(stmt).scalars())

    # ----------------------------------------------------------------- counts
    def counts(self) -> dict[str, int]:
        def c(model, *where):
            stmt = select(func.count()).select_from(model)
            for w in where:
                stmt = stmt.where(w)
            return int(self.db.execute(stmt).scalar() or 0)

        return {
            "documents": c(Document),
            "observations": c(Observation),
            "claims": c(Claim),
            "conflicts": c(Conflict),
            "unresolved_conflicts": c(Conflict, Conflict.status.in_(["open", "investigating", "human_review"])),
            "evidence": c(Evidence),
            "hypotheses": c(Hypothesis),
            "investigations": c(Investigation),
            "active_investigations": c(Investigation, Investigation.status.in_(["created", "running", "paused"])),
            "conclusions": c(Conclusion),
            "human_review_requests": c(Conflict, Conflict.status == "human_review"),
            "human_reviews": c(HumanReview),
            "audit_events": c(AuditEvent),
            "pending_verification": c(Evidence, Evidence.verification_status == "unverified"),
            "evidence_gaps": c(Hypothesis, Hypothesis.status == "inconclusive"),
        }

    # ------------------------------------------------------------------ writes
    def add_observation(self, **kwargs: Any) -> Observation:
        obs = Observation(**kwargs)
        self.db.add(obs)
        self.db.flush()
        return obs

    def add_claim(self, **kwargs: Any) -> Claim:
        claim = Claim(**kwargs)
        self.db.add(claim)
        self.db.flush()
        return claim

    def add_conflict(self, **kwargs: Any) -> Conflict:
        conflict = Conflict(**kwargs)
        self.db.add(conflict)
        self.db.flush()
        return conflict

    def add_evidence(self, **kwargs: Any) -> Evidence:
        ev = Evidence(**kwargs)
        self.db.add(ev)
        self.db.flush()
        return ev

    def add_hypothesis(self, **kwargs: Any) -> Hypothesis:
        hyp = Hypothesis(**kwargs)
        self.db.add(hyp)
        self.db.flush()
        return hyp

    def add_activity(self, **kwargs: Any) -> AgentActivity:
        activity = AgentActivity(**kwargs)
        if isinstance(activity.blackboard_changes, dict):
            activity.blackboard_changes = json.dumps(activity.blackboard_changes)
        self.db.add(activity)
        self.db.flush()
        return activity

    def commit(self) -> None:
        self.db.commit()

    def rollback(self) -> None:
        self.db.rollback()

    # ----------------------------------------------------------------- graph
    def snapshot(self) -> dict[str, Any]:
        """Structured snapshot for the dashboard (counts + graph)."""
        from .graph import build_graph

        return {
            "generated_at": datetime.now(timezone.utc),
            "counts": self.counts(),
            "graph": build_graph(self.db),
        }
