"""Document schemas."""
from __future__ import annotations

import json
from datetime import datetime

from pydantic import field_validator

from .common import ORMModel


class DocumentBase(ORMModel):
    id: int
    filename: str
    file_type: str
    content_type: str = ""
    file_size: int = 0
    status: str
    error_message: str = ""
    is_demo: bool = False
    uploaded_at: datetime | None = None
    processed_at: datetime | None = None


class DocumentOut(DocumentBase):
    claim_count: int = 0
    conflict_count: int = 0
    observation_count: int = 0
    source_metadata: dict = {}

    @field_validator("source_metadata", mode="before")
    @classmethod
    def _parse_meta(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v or "{}")
            except json.JSONDecodeError:
                return {}
        return v or {}

    @field_validator("is_demo", mode="before")
    @classmethod
    def _bool_demo(cls, v):
        return bool(v)


class DocumentDetail(DocumentOut):
    text_preview: str = ""
    char_count: int = 0


class DocumentUploadResponse(ORMModel):
    id: int
    filename: str
    status: str
    message: str = ""
    claim_count: int = 0
    conflict_count: int = 0
    duplicate: bool = False
