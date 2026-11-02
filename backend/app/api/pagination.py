"""Shared SQL-level pagination helpers.

List endpoints used to load every row and slice in Python, which made memory use
and latency grow with the whole table (not the requested page). These helpers
push ``LIMIT``/``OFFSET`` down to the database and compute the total with a
``COUNT`` over the same filter, so the response time and memory are bounded by
``page_size`` while ``total`` stays exact.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select


def count_for(db: Session, stmt: Select) -> int:
    """Exact number of rows the (unpaginated) ``stmt`` would return."""
    count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
    return int(db.execute(count_stmt).scalar() or 0)


def paginate(db: Session, stmt: Select, page: int, page_size: int) -> tuple[list[Any], int]:
    """Return ``(rows_for_page, total)`` for an entity ``stmt``."""
    total = count_for(db, stmt)
    rows = list(
        db.execute(stmt.offset((page - 1) * page_size).limit(page_size)).scalars()
    )
    return rows, total
