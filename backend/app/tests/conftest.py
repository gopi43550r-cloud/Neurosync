"""Pytest configuration and shared fixtures.

Uses a temporary SQLite database and temporary uploads so the suite never
touches real data and never requires an API key.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_neurosync.db")
os.environ.setdefault("ENABLE_LLM", "false")
os.environ.setdefault("OPENAI_API_KEY", "")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.blackboard.blackboard_service import Blackboard  # noqa: E402
from app.blackboard.controller import InvestigationControl, InvestigationController  # noqa: E402
from app.database import Base, SessionLocal, engine, init_db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="function")
def db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(scope="function")
def client(db):
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def blackboard(db):
    return Blackboard(db)


def run_investigation_sync(db, investigation_id: int) -> str:
    """Run an investigation to completion synchronously for deterministic tests."""
    controller = InvestigationController(db)
    return controller.run(investigation_id, InvestigationControl())
