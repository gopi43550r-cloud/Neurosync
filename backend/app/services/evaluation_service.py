"""Evaluation and performance analytics.

Design contract
---------------
* **Ground truth only.** A conflict is never counted as correct because the
  detector produced it; it is correct only when a human-authored label says the
  same thing. Evidence verdicts are compared with manually labelled outcomes.
* **Real code paths.** Runs invoke the shipped extraction, conflict detection
  and fact-verification functions in an isolated in-memory database. Evaluation
  documents never touch the application's real documents, uploads or blackboard.
* **No invented numbers.** Every rate is recomputed from persisted per-case
  results. Undefined denominators (for example recall with no positive examples)
  are returned as ``None`` and rendered as "n/a".
* **Demonstration vs validated.** Only labelled datasets produce metrics. The
  dashboard separates built-in reference benchmarks from user-labelled test
  sets and never scores unlabelled demonstration records.
"""
from __future__ import annotations

import csv
import io
import json
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from ..config import BACKEND_DIR
from ..models import (
    AgentActivity,
    Claim,
    Conflict,
    Document,
    EvaluationCase,
    EvaluationCaseResult,
    EvaluationDataset,
    EvaluationRun,
    Evidence,
    Hypothesis,
    Investigation,
)
from ..models.evaluation import utcnow
from ..schemas.evaluation import (
    AgentPerformanceOut,
    AgentPerformanceSummary,
    DocumentAnalyticsOut,
    EvaluationCaseOut,
    EvaluationCaseResultOut,
    EvaluationDashboardOut,
    EvaluationDatasetDetailOut,
    EvaluationDatasetIn,
    EvaluationDatasetOut,
    EvaluationRunOut,
    EvaluationRunSummaryOut,
)
from . import evaluation_export

BUILTIN_DATASETS_DIR = Path(BACKEND_DIR) / "evaluation" / "datasets"

BUILTIN_SPECS = (
    {
        "key": "builtin:conflict-detection",
        "filename": "conflicts.json",
        "kind": "conflict_detection",
        "name": "Conflict detection benchmark (reference)",
        "description": (
            "Curated human-labelled claim-pair examples that exercise the production "
            "extraction and conflict-detection path. Labels are authored independently "
            "of the detector's output."
        ),
    },
    {
        "key": "builtin:evidence-verification",
        "filename": "evidence_verification.json",
        "kind": "evidence_verification",
        "name": "Evidence verification benchmark (reference)",
        "description": (
            "Human-labelled claim/source pairs covering supported, contradicted, "
            "partially supported and unverified outcomes from the production "
            "fact-verification engine."
        ),
    },
)

CONFLICT_KIND = "conflict_detection"
EVIDENCE_KIND = "evidence_verification"
VERDICT_LABELS = ["supported", "contradicted", "partially_supported", "unverified"]


class EvaluationValidationError(ValueError):
    """Raised when a dataset or case is missing required ground truth."""


# --------------------------------------------------------------------- helpers
def _loads(value: str | None, default: Any) -> Any:
    try:
        parsed = json.loads(value or "")
    except (TypeError, json.JSONDecodeError):
        return default
    return parsed if isinstance(parsed, type(default)) else default


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _load_builtin(filename: str) -> dict:
    path = BUILTIN_DATASETS_DIR / filename
    if not path.exists():  # pragma: no cover - packaging failure, surfaced loudly
        raise EvaluationValidationError(f"Built-in dataset file is missing: {filename}")
    return json.loads(path.read_text(encoding="utf-8"))


def _builtin_cases(kind: str, payload: dict) -> list[dict]:
    cases: list[dict] = []
    if kind == CONFLICT_KIND:
        for example in payload.get("examples", []):
            label = bool(example.get("label"))
            cases.append(
                {
                    "case_key": str(example["id"]),
                    "category": example.get("category", "general"),
                    "payload": {
                        "text_a": example.get("text_a", ""),
                        "text_b": example.get("text_b", ""),
                    },
                    "expected": {
                        "label": label,
                        "expected_flagged": bool(
                            example.get("expected_flagged", label)
                        ),
                        "expected_types": list(example.get("expected_types", [])),
                    },
                    "rationale": example.get("rationale", ""),
                }
            )
    else:
        for case in payload.get("cases", []):
            cases.append(
                {
                    "case_key": str(case["id"]),
                    "category": case.get("category", "general"),
                    "payload": {
                        "claim_text": case.get("claim_text", ""),
                        "documents": list(case.get("documents", [])),
                    },
                    "expected": dict(case.get("expected", {})),
                    "rationale": case.get("rationale", ""),
                }
            )
    return cases


# ------------------------------------------------------------------ seeding/CRUD
def ensure_builtin_datasets(db: Session) -> None:
    """Seed the shipped labelled benchmarks once (idempotent)."""
    existing = {
        row.key
        for row in db.execute(select(EvaluationDataset.key)).all()
    }
    created = False
    for spec in BUILTIN_SPECS:
        if spec["key"] in existing:
            continue
        payload = _load_builtin(spec["filename"])
        dataset = EvaluationDataset(
            key=spec["key"],
            name=spec["name"],
            description=spec["description"],
            kind=spec["kind"],
            source="reference",
            version=str(payload.get("version", "1.0.0")),
            is_builtin=True,
        )
        db.add(dataset)
        db.flush()
        for case in _builtin_cases(spec["kind"], payload):
            db.add(
                EvaluationCase(
                    dataset_id=dataset.id,
                    case_key=case["case_key"],
                    category=case["category"],
                    payload=_dumps(case["payload"]),
                    expected=_dumps(case["expected"]),
                    rationale=case["rationale"],
                )
            )
        created = True
    if created:
        try:
            db.commit()
        except IntegrityError:  # pragma: no cover - concurrent startup
            db.rollback()


def _normalise_expected(kind: str, expected: dict) -> dict:
    if not isinstance(expected, dict):
        raise EvaluationValidationError("expected ground truth must be an object")
    if kind == CONFLICT_KIND:
        if "label" not in expected:
            raise EvaluationValidationError(
                "conflict-detection cases require expected.label (true/false)"
            )
        label = expected["label"]
        if not isinstance(label, bool):
            raise EvaluationValidationError("expected.label must be a boolean")
        types = expected.get("expected_types", [])
        if not isinstance(types, list) or any(not isinstance(t, str) for t in types):
            raise EvaluationValidationError("expected.expected_types must be a list of strings")
        normalised = {
            "label": label,
            "expected_flagged": bool(expected.get("expected_flagged", label)),
            "expected_types": types,
        }
        if not expected.get("expected_types") and expected.get("expected_flagged") is None:
            normalised["expected_flagged"] = label
        return normalised

    verdict = expected.get("verdict")
    if verdict not in VERDICT_LABELS:
        raise EvaluationValidationError(
            "evidence-verification cases require expected.verdict to be one of "
            + ", ".join(VERDICT_LABELS)
        )
    return {"verdict": verdict}


def _normalise_case(kind: str, case) -> dict:
    if kind == CONFLICT_KIND:
        text_a = (case.text_a or "").strip()
        text_b = (case.text_b or "").strip()
        if not text_a and not text_b:
            raise EvaluationValidationError(
                f"case {case.case_key}: at least one source text is required"
            )
        payload = {"text_a": text_a, "text_b": text_b}
    else:
        claim_text = (case.claim_text or "").strip()
        if not claim_text:
            raise EvaluationValidationError(
                f"case {case.case_key}: claim_text is required"
            )
        documents = [doc.model_dump() for doc in case.documents]
        if not documents:
            raise EvaluationValidationError(
                f"case {case.case_key}: at least one comparison document is required"
            )
        payload = {"claim_text": claim_text, "documents": documents}
    return {
        "case_key": case.case_key.strip(),
        "category": (case.category or "general").strip() or "general",
        "payload": payload,
        "expected": _normalise_expected(kind, case.expected),
        "rationale": case.rationale or "",
    }


def create_dataset(db: Session, payload: EvaluationDatasetIn) -> EvaluationDataset:
    """Persist a user-created labelled dataset."""
    dataset = EvaluationDataset(
        key=f"user:{uuid.uuid4().hex}",
        name=payload.name.strip(),
        description=payload.description or "",
        kind=payload.kind,
        source="user",
        version=payload.version or "1.0.0",
        is_builtin=False,
    )
    db.add(dataset)
    db.flush()
    for case in payload.cases:
        normalised = _normalise_case(payload.kind, case)
        db.add(
            EvaluationCase(
                dataset_id=dataset.id,
                case_key=normalised["case_key"],
                category=normalised["category"],
                payload=_dumps(normalised["payload"]),
                expected=_dumps(normalised["expected"]),
                rationale=normalised["rationale"],
            )
        )
    db.commit()
    db.refresh(dataset)
    return dataset


def create_dataset_from_json(db: Session, raw: bytes | str) -> EvaluationDataset:
    """Parse and persist a JSON upload in the documented dataset shape."""
    try:
        text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        data = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvaluationValidationError(f"Uploaded file is not valid JSON: {exc}") from exc
    try:
        payload = EvaluationDatasetIn.model_validate(data)
    except Exception as exc:  # pydantic ValidationError -> readable 422 message
        raise EvaluationValidationError(str(exc)) from exc
    return create_dataset(db, payload)


def list_datasets(db: Session) -> list[EvaluationDatasetOut]:
    datasets = list(
        db.execute(
            select(EvaluationDataset).order_by(
                EvaluationDataset.is_builtin.desc(), EvaluationDataset.name
            )
        ).scalars()
    )
    counts = {
        dataset_id: int(count)
        for dataset_id, count in db.execute(
            select(EvaluationCase.dataset_id, func.count()).group_by(EvaluationCase.dataset_id)
        ).all()
    }
    latest = _latest_runs_by_dataset(db)
    return [
        _dataset_out(dataset, counts.get(dataset.id, 0), latest.get(dataset.id))
        for dataset in datasets
    ]


def get_dataset(db: Session, dataset_id: int) -> EvaluationDataset | None:
    return db.get(EvaluationDataset, dataset_id)


def delete_dataset(db: Session, dataset_id: int) -> bool:
    dataset = db.get(EvaluationDataset, dataset_id)
    if dataset is None:
        return False
    if dataset.is_builtin:
        raise EvaluationValidationError("Built-in reference datasets cannot be deleted.")
    db.delete(dataset)
    db.commit()
    return True


def _latest_runs_by_dataset(db: Session) -> dict[int, EvaluationRun]:
    latest: dict[int, EvaluationRun] = {}
    for run in db.execute(select(EvaluationRun).order_by(EvaluationRun.id.desc())).scalars():
        latest.setdefault(run.dataset_id, run)
    return latest


def _dataset_out(
    dataset: EvaluationDataset,
    case_count: int,
    latest_run: EvaluationRun | None,
) -> EvaluationDatasetOut:
    return EvaluationDatasetOut(
        id=dataset.id,
        key=dataset.key,
        name=dataset.name,
        description=dataset.description or "",
        kind=dataset.kind,
        source=dataset.source,
        version=dataset.version,
        is_builtin=dataset.is_builtin,
        case_count=case_count,
        created_at=dataset.created_at,
        updated_at=dataset.updated_at,
        latest_run=_run_summary_out(latest_run) if latest_run else None,
    )


def dataset_detail(db: Session, dataset_id: int) -> EvaluationDatasetDetailOut | None:
    dataset = db.get(EvaluationDataset, dataset_id)
    if dataset is None:
        return None
    _latest = _latest_runs_by_dataset(db)
    base = _dataset_out(dataset, len(dataset.cases), _latest.get(dataset.id))
    return EvaluationDatasetDetailOut(
        **base.model_dump(),
        cases=[
            EvaluationCaseOut(
                id=case.id,
                case_key=case.case_key,
                category=case.category,
                payload=_loads(case.payload, {}),
                expected=_loads(case.expected, {}),
                rationale=case.rationale or "",
                created_at=case.created_at,
            )
            for case in dataset.cases
        ],
    )


# --------------------------------------------------------------------- run/export
def _run_summary_out(run: EvaluationRun) -> EvaluationRunSummaryOut:
    return EvaluationRunSummaryOut(
        id=run.id,
        dataset_id=run.dataset_id,
        dataset_name=run.dataset_name,
        kind=run.kind,
        provenance=run.provenance,
        status=run.status,
        case_count=run.case_count,
        passed=run.passed,
        failed=run.failed,
        duration_ms=run.duration_ms,
        error=run.error or "",
        metrics=_loads(run.metrics, {}),
        confusion=_loads(run.confusion, {}),
        started_at=run.started_at,
        completed_at=run.completed_at,
    )


def run_out(run: EvaluationRun, *, include_results: bool = True) -> EvaluationRunOut:
    summary = _run_summary_out(run)
    return EvaluationRunOut(
        **summary.model_dump(),
        by_category=_loads(run.by_category, {}),
        failures=_loads(run.failures, []),
        config=_loads(run.config, {}),
        results=[
            EvaluationCaseResultOut(
                id=result.id,
                case_key=result.case_key,
                category=result.category,
                expected=_loads(result.expected, {}),
                predicted=_loads(result.predicted, {}),
                passed=result.passed,
                duration_ms=result.duration_ms,
                explanation=result.explanation or "",
            )
            for result in run.results
        ]
        if include_results
        else [],
    )


def get_run(db: Session, run_id: int) -> EvaluationRun | None:
    return db.get(EvaluationRun, run_id)


def list_runs(
    db: Session,
    *,
    dataset_id: int | None = None,
    kind: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[EvaluationRunSummaryOut]:
    stmt = select(EvaluationRun)
    if dataset_id is not None:
        stmt = stmt.where(EvaluationRun.dataset_id == dataset_id)
    if kind:
        stmt = stmt.where(EvaluationRun.kind == kind)
    if status:
        stmt = stmt.where(EvaluationRun.status == status)
    stmt = stmt.order_by(EvaluationRun.id.desc()).limit(max(1, min(limit, 200)))
    return [_run_summary_out(run) for run in db.execute(stmt).scalars()]


@contextmanager
def _isolated_session():
    """A throwaway in-memory database for evaluation-only records."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    from ..database import Base

    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _conflict_dataset_dict(dataset: EvaluationDataset) -> tuple[dict, dict[str, tuple[dict, dict, str]]]:
    examples: list[dict] = []
    case_lookup: dict[str, tuple[dict, dict, str]] = {}
    for case in dataset.cases:
        payload = _loads(case.payload, {})
        expected = _loads(case.expected, {})
        label = bool(expected.get("label"))
        example = {
            "id": case.case_key,
            "category": case.category,
            "text_a": payload.get("text_a", ""),
            "text_b": payload.get("text_b", ""),
            "label": label,
            "expected_flagged": bool(expected.get("expected_flagged", label)),
            "expected_types": list(expected.get("expected_types", [])),
            "rationale": case.rationale or "",
        }
        examples.append(example)
        case_lookup[case.case_key] = (payload, expected, case.rationale or "")
    return (
        {
            "name": dataset.name,
            "version": dataset.version,
            "positive_class": "confirmed_contradiction",
            "examples": examples,
        },
        case_lookup,
    )


def _evidence_dataset_dict(dataset: EvaluationDataset) -> tuple[dict, dict[str, tuple[dict, dict, str]]]:
    cases: list[dict] = []
    case_lookup: dict[str, tuple[dict, dict, str]] = {}
    for case in dataset.cases:
        payload = _loads(case.payload, {})
        expected = _loads(case.expected, {})
        entry = {
            "id": case.case_key,
            "category": case.category,
            "claim_text": payload.get("claim_text", ""),
            "documents": list(payload.get("documents", [])),
            "expected": expected,
            "rationale": case.rationale or "",
        }
        cases.append(entry)
        case_lookup[case.case_key] = (payload, expected, case.rationale or "")
    return (
        {
            "name": dataset.name,
            "version": dataset.version,
            "cases": cases,
        },
        case_lookup,
    )


def _execute_conflict_run(dataset: EvaluationDataset) -> tuple[dict, list[dict]]:
    from evaluation import conflict_eval

    dataset_dict, case_lookup = _conflict_dataset_dict(dataset)
    with _isolated_session() as session:
        result = conflict_eval.run_conflict_evaluation(session, dataset_dict)

    examples = {example["id"]: example for example in result.get("examples", [])}
    failures = {failure["id"]: failure for failure in result.get("failures", [])}
    case_results: list[dict] = []
    for case in dataset.cases:
        payload, expected, rationale = case_lookup[case.case_key]
        example = examples.get(case.case_key)
        if example is None:
            case_results.append(
                {
                    "case_key": case.case_key,
                    "category": case.category,
                    "expected": expected,
                    "predicted": {},
                    "passed": False,
                    "explanation": "The evaluator produced no prediction for this case.",
                    "duration_ms": 0,
                }
            )
            continue
        passed = bool(example.get("classification_correct"))
        failure = failures.get(case.case_key)
        explanation = (
            "Classification correct."
            if passed
            else (failure["explanation"] if failure else "Classification incorrect.")
        )
        predicted = {
            "predicted_confirmed": example.get("predicted_confirmed"),
            "predicted_flagged": example.get("prediction", {}).get("predicted_flag"),
            "predicted_types": example.get("prediction", {}).get("predicted_types", []),
            "classification_correct": passed,
            "flagged_correct": example.get("flagged_correct"),
            "type_correct": example.get("type_correct"),
            "extraction": example.get("extraction", {}),
            "conflicts": example.get("prediction", {}).get("conflict_descriptions", []),
        }
        case_results.append(
            {
                "case_key": case.case_key,
                "category": case.category,
                "expected": expected,
                "predicted": predicted,
                "passed": passed,
                "explanation": explanation,
                "duration_ms": 0,
            }
        )

    overall = result["overall"]
    return (
        {
            "metrics": {
                "overall": overall,
                "signals": result.get("signals", {}),
                "dataset": result.get("dataset", {}),
            },
            "confusion": overall.get("counts", {}),
            "by_category": result.get("by_category", {}),
            "failures": result.get("failures", []),
        },
        case_results,
    )


def _execute_evidence_run(dataset: EvaluationDataset) -> tuple[dict, list[dict]]:
    from evaluation import evidence_verification_eval

    dataset_dict, case_lookup = _evidence_dataset_dict(dataset)
    with _isolated_session() as session:
        result = evidence_verification_eval.run_evidence_verification_evaluation(
            session, dataset_dict
        )

    cases = {case["id"]: case for case in result.get("cases", [])}
    case_results: list[dict] = []
    failures: list[dict] = []
    for case in dataset.cases:
        payload, expected, rationale = case_lookup[case.case_key]
        evaluated = cases.get(case.case_key)
        if evaluated is None:
            predicted = {
                "verdict": "unverified",
                "verdict_label": "Unverified",
                "claim_extracted": False,
            }
            passed = False
            explanation = "The evaluator produced no prediction for this case."
        else:
            predicted = evaluated.get("prediction", {})
            passed = bool(evaluated.get("correct"))
            explanation = (
                f"Expected {evaluated['expected_verdict']}; "
                f"predicted {evaluated['predicted_verdict']}."
            )
            if not passed:
                explanation += " " + str(predicted.get("explanation") or "")
                failures.append(
                    {
                        "case_key": case.case_key,
                        "category": case.category,
                        "expected": evaluated["expected_verdict"],
                        "predicted": evaluated["predicted_verdict"],
                        "explanation": explanation.strip(),
                    }
                )
        case_results.append(
            {
                "case_key": case.case_key,
                "category": case.category,
                "expected": expected,
                "predicted": predicted,
                "passed": passed,
                "explanation": explanation.strip(),
                "duration_ms": int(evaluated.get("duration_ms", 0)) if evaluated else 0,
            }
        )

    overall = result["overall"]
    return (
        {
            "metrics": {"overall": overall, "dataset": result.get("dataset", {})},
            "confusion": result.get("confusion", {}),
            "by_category": result.get("by_category", {}),
            "failures": failures,
        },
        case_results,
    )


def execute_dataset(db: Session, dataset: EvaluationDataset) -> EvaluationRun:
    """Run one labelled dataset and persist every case outcome."""
    run = EvaluationRun(
        dataset_id=dataset.id,
        dataset_name=dataset.name,
        kind=dataset.kind,
        provenance="reference_labelled" if dataset.is_builtin else "user_labelled",
        status="running",
        case_count=len(dataset.cases),
        started_at=utcnow(),
        config=_dumps(
            {
                "deterministic_mode": True,
                "llm_enabled": False,
                "dataset_version": dataset.version,
                "dataset_source": dataset.source,
                "case_count": len(dataset.cases),
            }
        ),
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    started = time.perf_counter()
    try:
        if dataset.kind == CONFLICT_KIND:
            result, case_results = _execute_conflict_run(dataset)
        elif dataset.kind == EVIDENCE_KIND:
            result, case_results = _execute_evidence_run(dataset)
        else:  # pragma: no cover - guarded by schema, defensive here
            raise EvaluationValidationError(f"Unsupported evaluation kind: {dataset.kind}")
    except Exception as exc:  # persist the failure so the UI can show it honestly
        run.status = "failed"
        run.error = f"{type(exc).__name__}: {exc}"[:2000]
        run.completed_at = utcnow()
        run.duration_ms = int((time.perf_counter() - started) * 1000)
        db.commit()
        db.refresh(run)
        return run

    passed = sum(1 for case in case_results if case["passed"])
    run.status = "completed"
    run.passed = passed
    run.failed = len(case_results) - passed
    run.metrics = _dumps(result["metrics"])
    run.confusion = _dumps(result["confusion"])
    run.by_category = _dumps(result["by_category"])
    run.failures = _dumps(result["failures"])
    run.duration_ms = int((time.perf_counter() - started) * 1000)
    run.completed_at = utcnow()
    for case in case_results:
        db.add(
            EvaluationCaseResult(
                run_id=run.id,
                case_key=case["case_key"],
                category=case["category"],
                expected=_dumps(case["expected"]),
                predicted=_dumps(case["predicted"]),
                passed=bool(case["passed"]),
                duration_ms=int(case.get("duration_ms", 0)),
                explanation=case["explanation"],
            )
        )
    db.commit()
    db.refresh(run)
    return run


def execute_dataset_by_id(db: Session, dataset_id: int) -> EvaluationRun | None:
    dataset = db.get(EvaluationDataset, dataset_id)
    if dataset is None:
        return None
    return execute_dataset(db, dataset)


# -------------------------------------------------------------------- analytics
def _agent_summary(db: Session) -> AgentPerformanceSummary:
    from ..agents import AGENT_RESPONSIBILITIES, default_agents

    aggregated = {
        (agent_name, status): (count, total_ms, max_ms)
        for agent_name, status, count, total_ms, max_ms in db.execute(
            select(
                AgentActivity.agent_name,
                AgentActivity.status,
                func.count(),
                func.coalesce(func.sum(AgentActivity.duration_ms), 0),
                func.coalesce(func.max(AgentActivity.duration_ms), 0),
            ).group_by(AgentActivity.agent_name, AgentActivity.status)
        ).all()
    }
    running_agents = {
        agent
        for (agent,) in db.execute(
            select(Investigation.current_agent).where(
                Investigation.status == "running", Investigation.current_agent != ""
            )
        ).all()
        if agent
    }

    agents: list[AgentPerformanceOut] = []
    total_tasks = completed_tasks = failed_tasks = skipped_tasks = 0
    total_duration = 0
    for agent in default_agents():
        name = agent.name
        statuses = {
            status: values for (agent_name, status), values in aggregated.items() if agent_name == name
        }
        completed = int(statuses.get("success", (0, 0, 0))[0])
        failed = int(statuses.get("failed", (0, 0, 0))[0])
        skipped = int(statuses.get("skipped", (0, 0, 0))[0])
        tasks = completed + failed + skipped
        agent_duration = sum(
            int(values[1]) for values in statuses.values()
        )
        max_duration = max((int(values[2]) for values in statuses.values()), default=0)

        last = db.execute(
            select(AgentActivity)
            .where(AgentActivity.agent_name == name)
            .order_by(AgentActivity.created_at.desc(), AgentActivity.id.desc())
            .limit(1)
        ).scalars().first()
        if name in running_agents:
            status = "running"
        elif tasks == 0:
            status = "idle"
        elif completed == 0 and failed > 0:
            status = "failed"
        else:
            status = "completed"

        agents.append(
            AgentPerformanceOut(
                name=name,
                responsibility=AGENT_RESPONSIBILITIES.get(name, ""),
                status=status,
                total_tasks=tasks,
                completed_tasks=completed,
                failed_tasks=failed,
                skipped_tasks=skipped,
                total_duration_ms=agent_duration,
                avg_duration_ms=round(agent_duration / tasks, 2) if tasks else None,
                max_duration_ms=max_duration,
                last_action=last.action if last else "",
                last_activity_at=last.created_at if last else None,
            )
        )
        total_tasks += tasks
        completed_tasks += completed
        failed_tasks += failed
        skipped_tasks += skipped
        total_duration += agent_duration

    return AgentPerformanceSummary(
        agents=agents,
        total_tasks=total_tasks,
        completed_tasks=completed_tasks,
        failed_tasks=failed_tasks,
        skipped_tasks=skipped_tasks,
        avg_duration_ms=round(total_duration / total_tasks, 2) if total_tasks else None,
    )


def _document_analytics(db: Session) -> DocumentAnalyticsOut:
    document_rows = list(
        db.execute(
            select(Document.status, Document.uploaded_at, Document.processed_at)
        ).all()
    )
    by_status: dict[str, int] = {}
    durations: list[float] = []
    for status, uploaded_at, processed_at in document_rows:
        by_status[status] = by_status.get(status, 0) + 1
        if uploaded_at and processed_at:
            elapsed = (processed_at - uploaded_at).total_seconds() * 1000
            if elapsed >= 0:
                durations.append(elapsed)

    investigation_rows = list(
        db.execute(
            select(
                Investigation.status,
                Investigation.started_at,
                Investigation.completed_at,
                Investigation.iteration_count,
            )
        ).all()
    )
    inv_by_status: dict[str, int] = {}
    inv_durations: list[float] = []
    total_iterations = 0
    for status, started_at, completed_at, iteration_count in investigation_rows:
        inv_by_status[status] = inv_by_status.get(status, 0) + 1
        total_iterations += int(iteration_count or 0)
        if started_at and completed_at:
            elapsed = (completed_at - started_at).total_seconds() * 1000
            if elapsed >= 0:
                inv_durations.append(elapsed)

    claims = int(db.execute(select(func.count()).select_from(Claim)).scalar() or 0)
    documents_with_claims = int(
        db.execute(select(func.count(func.distinct(Claim.document_id)))).scalar() or 0
    )
    conflicts = int(db.execute(select(func.count()).select_from(Conflict)).scalar() or 0)
    conflicts_resolved = int(
        db.execute(
            select(func.count()).select_from(Conflict).where(Conflict.status == "resolved")
        ).scalar()
        or 0
    )
    hypotheses = int(db.execute(select(func.count()).select_from(Hypothesis)).scalar() or 0)
    evidence = int(db.execute(select(func.count()).select_from(Evidence)).scalar() or 0)

    # Last 14 calendar days of document intake (real upload timestamps only).
    today = datetime.now(timezone.utc).date()
    day_keys = [(today - timedelta(days=offset)).isoformat() for offset in range(13, -1, -1)]
    day_counts: dict[str, dict[str, int]] = {
        key: {"documents": 0, "processed": 0} for key in day_keys
    }
    for status, uploaded_at, _processed_at in document_rows:
        if not uploaded_at:
            continue
        key = uploaded_at.date().isoformat()
        if key in day_counts:
            day_counts[key]["documents"] += 1
            if status == "processed":
                day_counts[key]["processed"] += 1

    return DocumentAnalyticsOut(
        documents_total=len(document_rows),
        documents_processed=by_status.get("processed", 0),
        documents_pending=by_status.get("pending", 0),
        documents_processing=by_status.get("processing", 0),
        documents_error=by_status.get("error", 0),
        documents_by_status=by_status,
        documents_with_timing=len(durations),
        avg_processing_ms=round(sum(durations) / len(durations), 2) if durations else None,
        max_processing_ms=int(max(durations)) if durations else None,
        total_processing_ms=int(sum(durations)),
        claims_extracted=claims,
        documents_with_claims=documents_with_claims,
        conflicts_detected=conflicts,
        conflicts_resolved=conflicts_resolved,
        hypotheses_total=hypotheses,
        evidence_total=evidence,
        investigations_total=len(investigation_rows),
        investigations_by_status=inv_by_status,
        investigations_with_timing=len(inv_durations),
        avg_investigation_ms=round(sum(inv_durations) / len(inv_durations), 2)
        if inv_durations
        else None,
        total_iterations=total_iterations,
        documents_by_day=[
            {"date": key, **values} for key, values in day_counts.items()
        ],
    )


def _select_headline_runs(db: Session) -> tuple[EvaluationRun | None, EvaluationRun | None]:
    """Latest completed reference run per kind, falling back to user-labelled."""
    completed = list(
        db.execute(
            select(EvaluationRun)
            .where(EvaluationRun.status == "completed")
            .order_by(EvaluationRun.id.desc())
        ).scalars()
    )
    chosen: dict[str, EvaluationRun] = {}
    fallback: dict[str, EvaluationRun] = {}
    for run in completed:
        fallback.setdefault(run.kind, run)
        if run.provenance == "reference_labelled":
            chosen.setdefault(run.kind, run)
    return (
        chosen.get(CONFLICT_KIND) or fallback.get(CONFLICT_KIND),
        chosen.get(EVIDENCE_KIND) or fallback.get(EVIDENCE_KIND),
    )


def dashboard(db: Session) -> EvaluationDashboardOut:
    ensure_builtin_datasets(db)
    datasets = list_datasets(db)
    conflict_run, evidence_run = _select_headline_runs(db)
    return EvaluationDashboardOut(
        generated_at=datetime.now(timezone.utc),
        disclaimer=(
            "Metrics below are computed only from labelled test cases with "
            "human-authored ground truth, using the actual production extraction, "
            "conflict-detection and fact-verification code. Demonstration records and "
            "unlabelled system output are never scored."
        ),
        validation_note=(
            "Reference benchmarks are curated human-labelled fixtures, not independently "
            "audited field trials. User-uploaded test sets are labelled by the user and "
            "are reported separately. A detected conflict is never assumed correct unless "
            "a ground-truth label says so."
        ),
        datasets=datasets,
        conflict_detection=run_out(conflict_run) if conflict_run else None,
        evidence_verification=run_out(evidence_run) if evidence_run else None,
        agents=_agent_summary(db),
        documents=_document_analytics(db),
    )


# ----------------------------------------------------------------------- export
def export_run(db: Session, run_id: int, fmt: str) -> tuple[bytes, str, str] | None:
    """Return ``(content, media_type, filename)`` for a completed run."""
    run = db.get(EvaluationRun, run_id)
    if run is None:
        return None
    dataset = db.get(EvaluationDataset, run.dataset_id)
    payload = run_out(run)
    if fmt == "csv":
        content = evaluation_export.render_csv(payload, dataset)
        return content.encode("utf-8-sig"), "text/csv", f"evaluation-run-{run.id}.csv"
    if fmt == "pdf":
        content = evaluation_export.render_pdf(payload, dataset)
        return content, "application/pdf", f"evaluation-run-{run.id}.pdf"
    raise EvaluationValidationError("format must be 'csv' or 'pdf'")
