"""Blackboard snapshot schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class BlackboardCounts(BaseModel):
    documents: int = 0
    observations: int = 0
    claims: int = 0
    conflicts: int = 0
    unresolved_conflicts: int = 0
    evidence: int = 0
    hypotheses: int = 0
    investigations: int = 0
    active_investigations: int = 0
    conclusions: int = 0
    human_review_requests: int = 0
    human_reviews: int = 0
    audit_events: int = 0
    pending_verification: int = 0
    evidence_gaps: int = 0


class GraphNode(BaseModel):
    id: str
    node_type: str
    label: str
    data: dict[str, Any] = {}


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    edge_type: str
    label: str = ""


class BlackboardGraph(BaseModel):
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []


class BlackboardEvent(BaseModel):
    id: int
    investigation_id: int | None = None
    event_type: str
    agent_name: str | None = None
    entity_type: str | None = None
    entity_id: int | None = None
    related: list[dict[str, Any]] = []
    payload: dict[str, Any] = {}
    created_at: datetime
    processed: bool = False


class BlackboardSnapshot(BaseModel):
    generated_at: datetime
    counts: BlackboardCounts
    graph: BlackboardGraph
    recent_activity: list[dict[str, Any]] = []
    severity_distribution: list[dict[str, Any]] = []
    activity_timeline: list[dict[str, Any]] = []
    recent_events: list[BlackboardEvent] = []
    relation_counts: dict[str, int] = {}
    window_days: int = 14
    conflict_type_distribution: list[dict[str, Any]] = []
    conflict_status_distribution: list[dict[str, Any]] = []
    investigation_status_distribution: list[dict[str, Any]] = []
    evidence_verification_distribution: list[dict[str, Any]] = []


class BlackboardRelationOut(BaseModel):
    id: int
    investigation_id: int | None = None
    source_type: str
    source_id: int
    target_type: str
    target_id: int
    relation_type: str
    agent_name: str = ""
    reason: str = ""
    created_at: datetime | None = None


class ConnectedRecord(BaseModel):
    relation_id: int
    relation_type: str
    direction: str
    label: str
    other: dict[str, Any]
    agent_name: str = ""
    reason: str = ""


class TraceRecord(BaseModel):
    type: str
    id: int
    exists: bool
    label: str


class TraceResponse(BaseModel):
    record: TraceRecord
    relations: list[ConnectedRecord] = []
    events: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []
    influenced_by: list[dict[str, Any]] = []
    why: list[str] = []


class ReevaluationSummary(BaseModel):
    tasks: int = 0
    genuine: int = 0
    reopened: int = 0
    hypotheses_rescored: int = 0
    conclusions_revised: int = 0
    skipped: int = 0
