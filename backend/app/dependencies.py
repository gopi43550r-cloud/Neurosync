"""Shared FastAPI dependencies."""
from __future__ import annotations

from fastapi import Depends
from sqlalchemy.orm import Session

from .blackboard.blackboard_service import Blackboard
from .database import get_db


def get_blackboard(db: Session = Depends(get_db)) -> Blackboard:
    return Blackboard(db)
