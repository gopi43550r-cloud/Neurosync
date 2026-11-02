"""Evaluation and performance dashboard endpoints.

The API is a thin wrapper around :mod:`app.services.evaluation_service`. It
never computes a metric itself: runs are executed against the production
pipeline and every number in a response is derived from persisted per-case
results or real audit rows.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas.common import MessageResponse
from ..schemas.evaluation import (
    AgentPerformanceSummary,
    DocumentAnalyticsOut,
    EvaluationDashboardOut,
    EvaluationDatasetDetailOut,
    EvaluationDatasetIn,
    EvaluationDatasetOut,
    EvaluationRunOut,
    EvaluationRunSummaryOut,
)
from ..services import evaluation_service
from ..services.evaluation_service import EvaluationValidationError

router = APIRouter(prefix="/evaluation", tags=["evaluation"])

MAX_UPLOAD_BYTES = 5 * 1024 * 1024


def _get_dataset_or_404(db: Session, dataset_id: int):
    dataset = evaluation_service.get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail="Dataset not found.")
    return dataset


def _get_run_or_404(db: Session, run_id: int):
    run = evaluation_service.get_run(db, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Evaluation run not found.")
    return run


# ------------------------------------------------------------------- datasets
@router.get("/datasets", response_model=list[EvaluationDatasetOut])
def list_datasets(db: Session = Depends(get_db)) -> list[EvaluationDatasetOut]:
    evaluation_service.ensure_builtin_datasets(db)
    return evaluation_service.list_datasets(db)


@router.post("/datasets", response_model=EvaluationDatasetDetailOut, status_code=201)
def create_dataset(
    payload: EvaluationDatasetIn, db: Session = Depends(get_db)
) -> EvaluationDatasetDetailOut:
    try:
        dataset = evaluation_service.create_dataset(db, payload)
    except EvaluationValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    detail = evaluation_service.dataset_detail(db, dataset.id)
    assert detail is not None  # just created
    return detail


@router.post("/datasets/upload", response_model=EvaluationDatasetDetailOut, status_code=201)
async def upload_dataset(
    file: UploadFile = File(...), db: Session = Depends(get_db)
) -> EvaluationDatasetDetailOut:
    """Accept a JSON dataset document (same shape as ``POST /datasets``)."""
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=422, detail="Uploaded file is empty.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Dataset upload exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.",
        )
    try:
        dataset = evaluation_service.create_dataset_from_json(db, raw)
    except EvaluationValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    detail = evaluation_service.dataset_detail(db, dataset.id)
    assert detail is not None
    return detail


@router.get("/datasets/{dataset_id}", response_model=EvaluationDatasetDetailOut)
def get_dataset(dataset_id: int, db: Session = Depends(get_db)) -> EvaluationDatasetDetailOut:
    _get_dataset_or_404(db, dataset_id)
    detail = evaluation_service.dataset_detail(db, dataset_id)
    if detail is None:  # pragma: no cover - deleted between calls
        raise HTTPException(status_code=404, detail="Dataset not found.")
    return detail


@router.delete("/datasets/{dataset_id}", response_model=MessageResponse)
def delete_dataset(dataset_id: int, db: Session = Depends(get_db)) -> MessageResponse:
    try:
        deleted = evaluation_service.delete_dataset(db, dataset_id)
    except EvaluationValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Dataset not found.")
    return MessageResponse(message="Dataset and its runs were deleted.")


# ----------------------------------------------------------------------- runs
@router.get("/runs", response_model=list[EvaluationRunSummaryOut])
def list_runs(
    dataset_id: int | None = Query(default=None),
    kind: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[EvaluationRunSummaryOut]:
    return evaluation_service.list_runs(
        db, dataset_id=dataset_id, kind=kind, status=status, limit=limit
    )


@router.post("/datasets/{dataset_id}/run", response_model=EvaluationRunOut, status_code=201)
def run_dataset(dataset_id: int, db: Session = Depends(get_db)) -> EvaluationRunOut:
    """Execute a labelled dataset through the real production pipeline."""
    _get_dataset_or_404(db, dataset_id)
    run = evaluation_service.execute_dataset_by_id(db, dataset_id)
    if run is None:  # pragma: no cover - checked above
        raise HTTPException(status_code=404, detail="Dataset not found.")
    return evaluation_service.run_out(run)


@router.get("/runs/{run_id}", response_model=EvaluationRunOut)
def get_run(run_id: int, db: Session = Depends(get_db)) -> EvaluationRunOut:
    run = _get_run_or_404(db, run_id)
    return evaluation_service.run_out(run)


@router.get("/runs/{run_id}/export")
def export_run(
    run_id: int,
    format: str = Query(default="csv", pattern="^(csv|pdf)$"),
    db: Session = Depends(get_db),
) -> Response:
    run = _get_run_or_404(db, run_id)
    if run.status != "completed":
        raise HTTPException(
            status_code=409,
            detail="Only completed runs can be exported; this run has no valid metrics.",
        )
    rendered = evaluation_service.export_run(db, run_id, format)
    if rendered is None:  # pragma: no cover - checked above
        raise HTTPException(status_code=404, detail="Evaluation run not found.")
    content, media_type, filename = rendered
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ------------------------------------------------------------------ dashboard
@router.get("/dashboard", response_model=EvaluationDashboardOut)
def dashboard(db: Session = Depends(get_db)) -> EvaluationDashboardOut:
    """Performance cards, charts, confusion matrices and live analytics."""
    return evaluation_service.dashboard(db)


@router.get("/analytics/agents", response_model=AgentPerformanceSummary)
def agent_analytics(db: Session = Depends(get_db)) -> AgentPerformanceSummary:
    return evaluation_service._agent_summary(db)


@router.get("/analytics/documents", response_model=DocumentAnalyticsOut)
def document_analytics(db: Session = Depends(get_db)) -> DocumentAnalyticsOut:
    return evaluation_service._document_analytics(db)
