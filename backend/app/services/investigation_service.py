"""Investigation lifecycle service: create, start, pause, resume, cancel."""
from __future__ import annotations

import threading

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..blackboard.controller import InvestigationController, registry
from ..database import SessionLocal
from ..models import (
    AgentActivity,
    Claim,
    Conclusion,
    Conflict,
    Document,
    Evidence,
    Investigation,
    enums,
)
from ..schemas.investigation import InvestigationCreate, InvestigationUpdate


class InvestigationError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def create_investigation(db: Session, payload: InvestigationCreate, is_demo: bool = False) -> Investigation:
    documents = []
    if payload.document_ids:
        documents = list(db.execute(select(Document).where(Document.id.in_(payload.document_ids))).scalars())
        if len(documents) != len(set(payload.document_ids)):
            raise InvestigationError("One or more selected documents were not found.", 404)

    conflicts = []
    if payload.conflict_ids:
        conflicts = list(db.execute(select(Conflict).where(Conflict.id.in_(payload.conflict_ids))).scalars())
        if len(conflicts) != len(set(payload.conflict_ids)):
            raise InvestigationError("One or more selected conflicts were not found.", 404)

    if not documents and not conflicts:
        raise InvestigationError("Select at least one document or conflict to investigate.", 422)

    investigation = Investigation(
        name=payload.name,
        research_question=payload.research_question,
        iteration_limit=payload.iteration_limit,
        min_evidence_threshold=payload.min_evidence_threshold,
        enable_llm=payload.enable_llm,
        status=enums.InvestigationStatus.CREATED.value,
        is_demo=1 if is_demo else 0,
    )
    investigation.documents = documents
    investigation.conflicts = conflicts
    db.add(investigation)
    db.commit()
    db.refresh(investigation)
    return investigation


def update_investigation(db: Session, investigation: Investigation, payload: InvestigationUpdate) -> Investigation:
    if investigation.status == enums.InvestigationStatus.RUNNING.value and (
        payload.iteration_limit is not None or payload.min_evidence_threshold is not None
    ):
        raise InvestigationError("Cannot change limits while an investigation is running.", 409)
    data = payload.model_dump(exclude_none=True)
    for key, value in data.items():
        setattr(investigation, key, value)
    db.commit()
    db.refresh(investigation)
    return investigation


def _run_thread(investigation_id: int) -> None:
    db = SessionLocal()
    try:
        control = registry.get(investigation_id)
        InvestigationController(db).run(investigation_id, control)
    except Exception:  # pragma: no cover - logged in controller
        pass
    finally:
        db.close()
        registry.release(investigation_id)


def start_investigation(db: Session, investigation: Investigation) -> Investigation:
    if investigation.status == enums.InvestigationStatus.RUNNING.value or registry.is_running(investigation.id):
        raise InvestigationError("This investigation is already running.", 409)
    if investigation.status in (enums.InvestigationStatus.COMPLETED.value,):
        # Allow restart by resetting counter, but keep history.
        investigation.iteration_count = 0

    # Prevent duplicate simultaneous investigations for the same documents/conflicts.
    for other in db.execute(
        select(Investigation).where(Investigation.id != investigation.id)
    ).scalars():
        if registry.is_running(other.id):
            other_docs = {d.id for d in other.documents}
            this_docs = {d.id for d in investigation.documents}
            other_conf = {c.id for c in other.conflicts}
            this_conf = {c.id for c in investigation.conflicts}
            if (other_docs & this_docs) or (other_conf & this_conf):
                raise InvestigationError(
                    "Another investigation covering the same documents/conflicts is already running.", 409
                )

    control = registry.register(investigation.id)
    if control is None:
        raise InvestigationError("This investigation is already running.", 409)

    investigation.status = enums.InvestigationStatus.RUNNING.value
    investigation.stop_reason = ""
    investigation.error_message = ""
    db.commit()

    thread = threading.Thread(target=_run_thread, args=(investigation.id,), daemon=True)
    thread.start()
    return investigation


def pause_investigation(db: Session, investigation: Investigation) -> Investigation:
    control = registry.get(investigation.id)
    if control is None:
        raise InvestigationError("Investigation is not currently running.", 409)
    control.pause()
    return investigation


def resume_investigation(db: Session, investigation: Investigation) -> Investigation:
    control = registry.get(investigation.id)
    if control is None:
        raise InvestigationError("Investigation is not currently running.", 409)
    control.resume()
    return investigation


def cancel_investigation(db: Session, investigation: Investigation) -> Investigation:
    control = registry.get(investigation.id)
    if control is None:
        raise InvestigationError("Investigation is not currently running.", 409)
    control.cancel()
    return investigation


def activity_for(db: Session, investigation_id: int) -> list[AgentActivity]:
    return list(
        db.execute(
            select(AgentActivity)
            .where(AgentActivity.investigation_id == investigation_id)
            .order_by(AgentActivity.created_at, AgentActivity.id)
        ).scalars()
    )


def investigation_stats(db: Session, investigation: Investigation) -> dict[str, int]:
    doc_ids = [d.id for d in investigation.documents]
    conflict_ids = [c.id for c in investigation.conflicts]
    evidence_count = 0
    if conflict_ids:
        evidence_count = int(
            db.execute(
                select(func.count()).select_from(Evidence).where(Evidence.conflict_id.in_(conflict_ids))
            ).scalar()
            or 0
        )
    conclusion_count = int(
        db.execute(
            select(func.count()).select_from(Conclusion).where(Conclusion.investigation_id == investigation.id)
        ).scalar()
        or 0
    )
    open_conflicts = 0
    for c in investigation.conflicts:
        if c.status in ("open", "investigating", "human_review"):
            open_conflicts += 1
    return {
        "document_count": len(doc_ids),
        "conflict_count": len(conflict_ids),
        "open_conflict_count": open_conflicts,
        "evidence_count": evidence_count,
        "conclusion_count": conclusion_count,
    }
