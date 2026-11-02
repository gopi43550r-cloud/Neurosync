"""Knowledge graph response schemas."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class KGNode(BaseModel):
    id: str
    node_type: str
    label: str
    data: dict[str, Any] = {}


class KGEdge(BaseModel):
    id: str
    source: str
    target: str
    edge_type: str
    label: str = ""
    # True when backed by a direct persisted foreign key / association / ledger
    # row; False when derived from a JSON id list or a membership join.
    verified: bool = True
    agent_name: str = ""
    reason: str = ""


class KnowledgeGraph(BaseModel):
    nodes: list[KGNode] = []
    edges: list[KGEdge] = []
    node_type_counts: dict[str, int] = {}
    relation_type_counts: dict[str, int] = {}
    available_node_types: list[str] = []
    required_relation_types: list[str] = []
    available_relation_types: list[str] = []
    totals: dict[str, int] = {}
    truncated: bool = False
    investigation_id: int | None = None
