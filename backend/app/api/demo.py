"""Demonstration endpoints: load and reset the labelled sample scenario."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..demo import scenario
from ..schemas.common import MessageResponse

router = APIRouter(prefix="/demo", tags=["demo"])


@router.post("/load")
def load_demo(auto_start: bool = False, db: Session = Depends(get_db)) -> dict:
    documents, investigation_id = scenario.load_demo(db, auto_start=auto_start)
    return {
        "ok": True,
        "message": "Demonstration scenario loaded. All data is clearly labelled as demonstration data.",
        "is_demo": True,
        "documents": [{"id": d.id, "filename": d.filename} for d in documents],
        "investigation_id": investigation_id,
    }


@router.post("/reset")
def reset_demo(db: Session = Depends(get_db)) -> MessageResponse:
    removed = scenario.reset_demo(db)
    return MessageResponse(message=f"Removed {removed} demonstration record(s).")
