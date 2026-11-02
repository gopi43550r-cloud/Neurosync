"""Audit-trail schemas."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from pydantic import field_validator

from .common import ORMModel


class AuditEventOut(ORMModel):
    id: int
    investigation_id: int | None = None
    conflict_id: int | None = None
    entity_type: str
    entity_id: int | None = None
    action: str
    actor: str = "system"
    summary: str = ""
    detail: dict[str, Any] = {}
    created_at: datetime | None = None

    @field_validator("detail", mode="before")
    @classmethod
    def _parse(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v or "{}")
            except json.JSONDecodeError:
                return {}
        return v or {}
