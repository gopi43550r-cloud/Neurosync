"""Blackboard endpoints: current state, dashboard snapshot and intelligence layer."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..blackboard.graph import build_graph
from ..database import get_db
from ..models import (
    AgentActivity,
    AuditEvent,
    BlackboardRelation,
    Claim,
    Conclusion,
    Conflict,
    Document,
    EventLog,
    Evidence,
    HumanReview,
    Hypothesis,
    Investigation,
    Observation,
)
from ..models import enums
from ..schemas.blackboard import (
    BlackboardCounts,
    BlackboardEvent,
    BlackboardRelationOut,
    BlackboardSnapshot,
    ConnectedRecord,
    ReevaluationSummary,
    TraceResponse,
)
from ..schemas.common import Page
from ..services import reevaluation_service, relation_service, traceability_service
from ..services.event_redaction import redact_payload
from .pagination import paginate

router = APIRouter(prefix="/blackboard", tags=["blackboard"])


def _count(db: Session, model, *where) -> int:
    stmt = select(func.count()).select_from(model)
    for w in where:
        stmt = stmt.where(w)
    return int(db.execute(stmt).scalar() or 0)


def _counts(db: Session) -> BlackboardCounts:
    return BlackboardCounts(
        documents=_count(db, Document),
        observations=_count(db, Observation),
        claims=_count(db, Claim),
        conflicts=_count(db, Conflict),
        unresolved_conflicts=_count(db, Conflict, Conflict.status.in_(["open", "investigating", "human_review"])),
        evidence=_count(db, Evidence),
        hypotheses=_count(db, Hypothesis),
        investigations=_count(db, Investigation),
        active_investigations=_count(db, Investigation, Investigation.status.in_(["created", "running", "paused"])),
        conclusions=_count(db, Conclusion),
        human_review_requests=_count(db, Conflict, Conflict.status == "human_review"),
        human_reviews=_count(db, HumanReview),
        audit_events=_count(db, AuditEvent),
        pending_verification=_count(db, Evidence, Evidence.verification_status == "unverified"),
        evidence_gaps=_count(db, Hypothesis, Hypothesis.status == "inconclusive"),
    )


def _severity_distribution(db: Session) -> list[dict]:
    rows = db.execute(select(Conflict.severity, func.count()).group_by(Conflict.severity)).all()
    counts = {sev: n for sev, n in rows}
    return [{"severity": s, "count": counts.get(s, 0)} for s in ("critical", "high", "medium", "low")]


def _distribution(db: Session, column, order: list[str]) -> list[dict]:
    """Count rows by ``column``, always returning every known value (0 included)."""
    rows = db.execute(select(column, func.count()).group_by(column)).all()
    counts = {str(value): n for value, n in rows if value is not None}
    return [{"value": v, "count": counts.get(v, 0)} for v in order]


def _activity_timeline(db: Session, days: int = 14) -> list[dict]:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).replace(tzinfo=None)
    rows = db.execute(select(EventLog.created_at).where(EventLog.created_at >= since)).all()
    buckets: dict[str, int] = {}
    for (created,) in rows:
        key = created.strftime("%Y-%m-%d")
        buckets[key] = buckets.get(key, 0) + 1
    timeline = []
    for i in range(days - 1, -1, -1):
        day = (datetime.now(timezone.utc) - timedelta(days=i)).strftime("%Y-%m-%d")
        timeline.append({"date": day, "count": buckets.get(day, 0)})
    return timeline


@router.get("")
def current_state(db: Session = Depends(get_db)) -> dict:
    return {"counts": _counts(db).model_dump(), "graph": build_graph(db)}


def _event_to_out(event: EventLog) -> BlackboardEvent:
    try:
        payload = json.loads(event.payload or "{}")
    except json.JSONDecodeError:
        payload = {}
    try:
        related = json.loads(event.related) if event.related else []
    except (TypeError, json.JSONDecodeError):
        related = []
    return BlackboardEvent(
        id=event.id,
        investigation_id=event.investigation_id,
        event_type=event.event_type,
        agent_name=event.agent_name,
        entity_type=event.entity_type,
        entity_id=event.entity_id,
        related=related,
        payload=redact_payload(payload),
        created_at=event.created_at.replace(tzinfo=timezone.utc),
        processed=event.processed_at is not None,
    )


def _relation_counts(db: Session) -> dict[str, int]:
    rows = db.execute(
        select(BlackboardRelation.relation_type, func.count()).group_by(BlackboardRelation.relation_type)
    ).all()
    return {relation_type: n for relation_type, n in rows}


@router.get("/snapshot", response_model=BlackboardSnapshot)
def snapshot(
    days: int = Query(default=14, ge=1, le=365, description="Activity window in days."),
    db: Session = Depends(get_db),
) -> BlackboardSnapshot:
    recent = list(
        db.execute(select(AgentActivity).order_by(AgentActivity.created_at.desc()).limit(15)).scalars()
    )
    recent_activity = [
        {
            "id": a.id,
            "agent": a.agent_name,
            "action": a.action,
            "output_summary": a.output_summary,
            "status": a.status,
            "created_at": a.created_at.replace(tzinfo=timezone.utc).isoformat(),
        }
        for a in recent
    ]
    recent_events = list(
        db.execute(select(EventLog).order_by(EventLog.created_at.desc(), EventLog.id.desc()).limit(25)).scalars()
    )
    return BlackboardSnapshot(
        generated_at=datetime.now(timezone.utc),
        counts=_counts(db),
        graph=build_graph(db),
        recent_activity=recent_activity,
        severity_distribution=_severity_distribution(db),
        activity_timeline=_activity_timeline(db, days),
        window_days=days,
        recent_events=[_event_to_out(e) for e in recent_events],
        relation_counts=_relation_counts(db),
        conflict_type_distribution=_distribution(
            db, Conflict.conflict_type, [t.value for t in enums.ConflictType]
        ),
        conflict_status_distribution=_distribution(
            db, Conflict.status, [s.value for s in enums.ConflictStatus]
        ),
        investigation_status_distribution=_distribution(
            db, Investigation.status, [s.value for s in enums.InvestigationStatus]
        ),
        evidence_verification_distribution=_distribution(
            db, Evidence.verification_status, [v.value for v in enums.VerificationStatus]
        ),
    )


@router.get("/events", response_model=Page[BlackboardEvent])
def list_events(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    investigation_id: int | None = None,
    event_type: str | None = None,
    agent_name: str | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
    db: Session = Depends(get_db),
) -> Page[BlackboardEvent]:
    stmt = select(EventLog).order_by(EventLog.id.desc())
    if investigation_id is not None:
        stmt = stmt.where(EventLog.investigation_id == investigation_id)
    if event_type:
        stmt = stmt.where(EventLog.event_type == event_type)
    if agent_name:
        stmt = stmt.where(EventLog.agent_name == agent_name)
    if entity_type:
        stmt = stmt.where(EventLog.entity_type == entity_type)
    if entity_id is not None:
        stmt = stmt.where(EventLog.entity_id == entity_id)
    events, total = paginate(db, stmt, page, page_size)
    return Page(
        items=[_event_to_out(e) for e in events],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/relations", response_model=Page[BlackboardRelationOut])
def list_relations(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    investigation_id: int | None = None,
    record_type: str | None = None,
    record_id: int | None = None,
    relation_type: str | None = None,
    db: Session = Depends(get_db),
) -> Page[BlackboardRelationOut]:
    stmt = relation_service.relations_query(
        investigation_id=investigation_id,
        record_type=record_type,
        record_id=record_id,
        relation_type=relation_type,
    )
    rows, total = paginate(db, stmt, page, page_size)
    return Page(
        items=[BlackboardRelationOut(**relation_service.relation_to_dict(r)) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/connected/{record_type}/{record_id}", response_model=list[ConnectedRecord])
def connected(
    record_type: str,
    record_id: int,
    investigation_id: int | None = None,
    db: Session = Depends(get_db),
) -> list[ConnectedRecord]:
    return [
        ConnectedRecord(**item)
        for item in relation_service.connected(db, record_type, record_id, investigation_id)
    ]


@router.get("/trace/{record_type}/{record_id}", response_model=TraceResponse)
def trace(
    record_type: str,
    record_id: int,
    investigation_id: int | None = None,
    db: Session = Depends(get_db),
) -> TraceResponse:
    data = traceability_service.trace(db, record_type, record_id, investigation_id)
    if not data["record"]["exists"]:
        raise HTTPException(status_code=404, detail=f"{record_type} {record_id} not found.")
    return TraceResponse(**data)


@router.post("/reevaluate", response_model=ReevaluationSummary)
def reevaluate(
    investigation_id: int | None = None,
    db: Session = Depends(get_db),
) -> ReevaluationSummary:
    """Drain pending re-evaluation tasks (scoped, event-driven reasoning)."""
    return ReevaluationSummary(**reevaluation_service.drain(db, investigation_id))
