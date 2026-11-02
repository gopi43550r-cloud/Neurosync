"""Application-wide settings stored as key/value rows.

A dedicated table keeps the schema migration-free: ``Base.metadata.create_all``
creates any new table, whereas adding a column to an existing table would not be
applied to an already-created SQLite database. The reasoning mode lives here so
it can be changed at runtime and survives restarts.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
