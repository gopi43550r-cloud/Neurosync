"""Knowledge graph endpoint.

A single read-only endpoint. It builds the typed knowledge graph from persisted
records and supports the filters the UI needs (investigation, node/record type,
relationship) plus hard caps that keep large graphs responsive. Node details are
served by the existing Blackboard trace endpoints, so no extra detail routes are
added.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas.knowledge_graph import KnowledgeGraph
from ..services import knowledge_graph_service

router = APIRouter(prefix="/knowledge-graph", tags=["knowledge graph"])


@router.get("", response_model=KnowledgeGraph)
def get_knowledge_graph(
    investigation_id: int | None = Query(default=None),
    record_type: list[str] | None = Query(default=None, description="Repeatable node-type filter."),
    relation_type: list[str] | None = Query(default=None, description="Repeatable edge-type filter."),
    max_nodes: int = Query(default=800, ge=1, le=5000),
    max_edges: int = Query(default=2500, ge=1, le=10000),
    db: Session = Depends(get_db),
) -> KnowledgeGraph:
    data = knowledge_graph_service.build_knowledge_graph(
        db,
        investigation_id=investigation_id,
        record_types=record_type,
        relation_types=relation_type,
        max_nodes=max_nodes,
        max_edges=max_edges,
    )
    return KnowledgeGraph(**data)
