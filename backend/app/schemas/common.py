"""Shared schema helpers: pagination, errors and generic response envelopes."""
from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int

    @property
    def pages(self) -> int:
        return (self.total + self.page_size - 1) // self.page_size if self.page_size else 0


class ErrorResponse(BaseModel):
    detail: str
    code: str = "error"


class MessageResponse(BaseModel):
    message: str
    ok: bool = True
