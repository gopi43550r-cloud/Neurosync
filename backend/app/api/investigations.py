"""Investigation endpoints: lifecycle, activity, real-time events and reports."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..blackboard.controller import registry
from ..database import SessionLocal, get_db
from ..models import AgentActivity, EventLog, Investigation
from ..models import enums
from ..schemas.common import Page
from ..schemas.investigation import (
    ActivityOut,
    InvestigationCreate,
    InvestigationOut,
    InvestigationUpdate,
    ReportOut,
)
from ..services import investigation_service, report_pdf, report_service
from ..services.event_redaction import redact_payload
from ..services.investigation_service import InvestigationError
from ..services.serialization import (
    activity_to_out,
    investigation_to_out,
    investigations_to_out,
)
from .pagination import paginate

router = APIRouter(prefix="/investigations", tags=["investigations"])

TERMINAL = {"completed", "cancelled", "error"}
# Upper bound on events emitted per SSE poll so a very large history cannot
# spike memory; the client resumes from the last emitted id.
SSE_EVENT_BATCH = 500


def _iso(value: datetime | None) -> str | None:
    return value.replace(tzinfo=timezone.utc).isoformat() if value else None


def _loads(raw: str | None) -> dict:
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _sse(event: str, data: dict, event_id: int | None = None) -> str:
    """Format a single Server-Sent Event frame."""
    lines = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.extend([f"event: {event}", f"data: {json.dumps(data, default=str)}"])
    return "\n".join(lines) + "\n\n"


def progress_snapshot(db: Session, investigation_id: int) -> dict | None:
    """Current, DB-derived progress for an investigation.

    Everything here is read from persisted rows, so the client's progress view
    always reflects actual backend state - never a simulated percentage.
    """
    inv = db.get(Investigation, investigation_id)
    if inv is None:
        return None
    running = inv.status == enums.InvestigationStatus.RUNNING.value
    rows = db.execute(
        select(AgentActivity.status, func.count())
        .where(AgentActivity.investigation_id == investigation_id)
        .group_by(AgentActivity.status)
    ).all()
    by_status = {status: count for status, count in rows}
    completed = by_status.get("success", 0)
    failed = by_status.get("failed", 0)
    skipped = by_status.get("skipped", 0)
    conflicts_open = sum(
        1 for c in inv.conflicts if c.status in ("open", "investigating", "human_review")
    )
    return {
        "investigation_id": inv.id,
        "status": inv.status,
        "current_agent": inv.current_agent if running else "",
        "current_objective": inv.current_objective if running else "",
        "iteration_count": inv.iteration_count,
        "iteration_limit": inv.iteration_limit,
        "stop_reason": inv.stop_reason,
        "updated_at": _iso(inv.updated_at),
        "executions": completed + failed + skipped,
        "completed": completed,
        "failed": failed,
        "skipped": skipped,
        "conflicts_total": len(inv.conflicts),
        "conflicts_open": conflicts_open,
    }


@router.post("", response_model=InvestigationOut, status_code=201)
def create_investigation(payload: InvestigationCreate, db: Session = Depends(get_db)) -> InvestigationOut:
    try:
        inv = investigation_service.create_investigation(db, payload)
    except InvestigationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return investigation_to_out(db, inv)


@router.get("", response_model=Page[InvestigationOut])
def list_investigations(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    status: str | None = None,
    db: Session = Depends(get_db),
) -> Page[InvestigationOut]:
    stmt = select(Investigation).order_by(Investigation.updated_at.desc())
    if status:
        stmt = stmt.where(Investigation.status == status)
    items, total = paginate(db, stmt, page, page_size)
    return Page(
        items=investigations_to_out(db, items),
        total=total,
        page=page,
        page_size=page_size,
    )


def _get_or_404(db: Session, investigation_id: int) -> Investigation:
    inv = db.get(Investigation, investigation_id)
    if inv is None:
        raise HTTPException(status_code=404, detail="Investigation not found.")
    return inv


@router.get("/{investigation_id}", response_model=InvestigationOut)
def get_investigation(investigation_id: int, db: Session = Depends(get_db)) -> InvestigationOut:
    return investigation_to_out(db, _get_or_404(db, investigation_id))


@router.patch("/{investigation_id}", response_model=InvestigationOut)
def update_investigation(
    investigation_id: int, payload: InvestigationUpdate, db: Session = Depends(get_db)
) -> InvestigationOut:
    inv = _get_or_404(db, investigation_id)
    try:
        inv = investigation_service.update_investigation(db, inv, payload)
    except InvestigationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return investigation_to_out(db, inv)


def _lifecycle(action: str):
    def handler(investigation_id: int, db: Session = Depends(get_db)) -> InvestigationOut:
        inv = _get_or_404(db, investigation_id)
        try:
            if action == "start":
                inv = investigation_service.start_investigation(db, inv)
            elif action == "pause":
                inv = investigation_service.pause_investigation(db, inv)
            elif action == "resume":
                inv = investigation_service.resume_investigation(db, inv)
            else:
                inv = investigation_service.cancel_investigation(db, inv)
        except InvestigationError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
        return investigation_to_out(db, inv)

    return handler


router.add_api_route("/{investigation_id}/start", _lifecycle("start"), methods=["POST"], response_model=InvestigationOut)
router.add_api_route("/{investigation_id}/pause", _lifecycle("pause"), methods=["POST"], response_model=InvestigationOut)
router.add_api_route("/{investigation_id}/resume", _lifecycle("resume"), methods=["POST"], response_model=InvestigationOut)
router.add_api_route("/{investigation_id}/cancel", _lifecycle("cancel"), methods=["POST"], response_model=InvestigationOut)


@router.get("/{investigation_id}/activity", response_model=list[ActivityOut])
def get_activity(investigation_id: int, db: Session = Depends(get_db)) -> list[ActivityOut]:
    _get_or_404(db, investigation_id)
    return [activity_to_out(a) for a in investigation_service.activity_for(db, investigation_id)]


@router.get("/{investigation_id}/report", response_model=ReportOut)
def get_report(investigation_id: int, db: Session = Depends(get_db)) -> ReportOut:
    inv = _get_or_404(db, investigation_id)
    return ReportOut(**report_service.build_report(db, inv))


@router.get("/{investigation_id}/report/export")
def export_report(investigation_id: int, format: str = "markdown", db: Session = Depends(get_db)):
    inv = _get_or_404(db, investigation_id)
    report = report_service.build_report(db, inv)
    if format == "json":
        return JSONResponse(content=report["json_data"])
    if format == "markdown":
        return PlainTextResponse(
            content=report["markdown"],
            media_type="text/markdown",
            headers={
                "Content-Disposition": f'attachment; filename="report-{investigation_id}.md"'
            },
        )
    if format == "pdf":
        pdf_bytes = report_pdf.render_report_pdf(report)
        filename = report_pdf.report_filename(report.get("title", f"investigation-{investigation_id}"))
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    raise HTTPException(status_code=422, detail="format must be 'markdown', 'json' or 'pdf'.")


@router.get("/{investigation_id}/events")
async def stream_events(investigation_id: int, request: Request) -> StreamingResponse:
    """Live progress stream for an investigation (Server-Sent Events).

    Reliability model:

    * **Event log, not screen-scraping.** Each persisted event is emitted with its
      database ``id`` as the SSE id, so the browser's automatic reconnection
      resumes precisely where it left off via the ``Last-Event-ID`` header.
    * **Authoritative progress frames.** A ``progress`` frame (real status,
      current agent, iteration counts and completed/failed tallies read from the
      database) is emitted on connect and whenever the state changes, so the UI
      never has to guess.
    * **Redaction.** Event payloads are redacted on the way out; raw document and
      claim text never leaves the server (the stored log keeps it for audit).
    * **Deterministic close.** Once the investigation is terminal the stream
      drains, emits ``stream_end`` and closes, so clients stop reconnecting.
    """
    last_event_id = request.headers.get("last-event-id")

    async def event_generator():
        last_id = int(last_event_id) if last_event_id and last_event_id.isdigit() else 0
        idle = 0
        completed_cycles = 0
        last_progress: dict | None = None

        # Confirm existence before opening the stream.
        db = SessionLocal()
        try:
            if db.get(Investigation, investigation_id) is None:
                yield _sse("stream_error", {"detail": "Investigation not found"})
                return
        finally:
            db.close()

        while True:
            if await request.is_disconnected():
                break

            db = SessionLocal()
            try:
                rows = list(
                    db.execute(
                        select(EventLog)
                        .where(EventLog.investigation_id == investigation_id, EventLog.id > last_id)
                        .order_by(EventLog.id)
                        .limit(SSE_EVENT_BATCH)
                    ).scalars()
                )
                progress = progress_snapshot(db, investigation_id)
            finally:
                db.close()

            status = progress["status"] if progress else "unknown"
            progress_changed = progress is not None and progress != last_progress

            if rows:
                idle = 0
                for row in rows:
                    last_id = row.id
                    envelope = {
                        "id": row.id,
                        "investigation_id": row.investigation_id,
                        "event_type": row.event_type,
                        "agent_name": row.agent_name,
                        "entity_type": row.entity_type,
                        "entity_id": row.entity_id,
                        "related": _loads_rows(row.related),
                        "payload": redact_payload(_loads(row.payload)),
                        "created_at": _iso(row.created_at),
                    }
                    yield _sse(row.event_type, envelope, event_id=row.id)

            if progress_changed:
                last_progress = progress
                yield _sse("progress", progress)

            if not rows and not progress_changed:
                idle += 1
                yield ": keepalive\n\n"

            if status in TERMINAL and idle >= 2:
                completed_cycles += 1
                if completed_cycles >= 2:
                    yield _sse("stream_end", {"status": status})
                    break

            await asyncio.sleep(0.4)

    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"}
    return StreamingResponse(event_generator(), media_type="text/event-stream", headers=headers)


def _loads_rows(raw: str | None) -> list:
    try:
        parsed = json.loads(raw) if raw else []
    except (TypeError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []
