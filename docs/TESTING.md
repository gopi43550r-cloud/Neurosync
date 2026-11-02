# NeuroSync — Testing

This document describes how NeuroSync is tested: the test layout, how to run the
suite, the evaluation harness, and the conventions to follow when adding tests.

The guiding rule is **determinism**: with no API key configured, the entire
pipeline is rule-based, so a given input always produces the same output. The
test suite never contacts the network, never requires an API key, and never
touches real data.

---

## 1. Prerequisites

- **Backend** — a Python virtual environment with dependencies installed
  (`backend/venv`). All backend commands below are run from `backend/`.
- **Frontend** — Node.js with dependencies installed (`frontend/node_modules`).
- No API key is required. Tests force `ENABLE_LLM=false`.

---

## 2. Running the backend test suite

From the `backend/` directory:

```powershell
.\venv\Scripts\python.exe -m pytest app\tests -q
```

Run a single file or test:

```powershell
.\venv\Scripts\python.exe -m pytest app\tests\test_reports.py -q
.\venv\Scripts\python.exe -m pytest app\tests\test_api.py::test_health -q
```

The current suite is **284 tests** and completes in roughly four minutes.

---

## 3. Test layout

Tests live in `backend/app/tests/`. Each file targets one subsystem:

| File | Covers |
| ---- | ------ |
| `test_api.py` | Core HTTP endpoints: health, config, documents, uploads. |
| `test_qa_backend.py` | End-to-end backend question/answer flows. |
| `test_qa_scenarios.py` | Scenario-driven regression cases. |
| `test_conflict_detection.py` | Conflict types, severity, tolerance and de-duplication. |
| `test_agents.py` | The six agents. |
| `test_scheduler.py` | Scheduler factor computation and prioritisation. |
| `test_orchestration.py` | Retries, the execution ledger and stop conditions. |
| `test_blackboard.py` | The blackboard facade and graph projection. |
| `test_progress_stream.py` | The SSE progress stream. |
| `test_audit_review_ranking.py` | Audit trail, human review and hypothesis ranking. |
| `test_evidence_assessment.py` | Multi-factor evidence assessment. |
| `test_dashboard_snapshot.py` | Snapshot counts, `days` window and distributions. |
| `test_reports.py` | Report assembly, traceability and exports. |
| `test_knowledge_graph.py` | The typed, filterable knowledge-graph projection. |
| `test_intelligence.py` | Derived intelligence records. |
| `test_demo_scenario.py` | The labelled demo scenario. |
| `test_settings_api.py` | Reasoning-mode preference and effective mode. |
| `test_fact_verification.py` | Claim-level fact verification with grounded citations. |
| `test_source_credibility.py` | Source-credibility analyzer factors and aggregation. |
| `test_chat_assistant.py` | Grounded investigation chat: scoping, citations and explicit uncertainty. |
| `test_llm_settings.py` | In-app API-key management: masking, persistence, validation, production guard and immediate activation. |
| `test_evaluation_dashboard.py` | Evaluation seeding, labelled test-set create/upload, real-code runs, recomputed metrics, dashboard analytics, CSV/PDF exports and validation errors. |
| `test_llm_service.py` / `test_llm_validation.py` / `test_llm_end_to_end.py` | The optional LLM layer: provider interface, grounding/validation and AI-assisted flows (no live calls). |
| `test_security.py` | Security regressions (upload/validation/path safety). |

---

## 4. Fixtures and isolation

Shared fixtures live in `conftest.py`:

- **Temporary database.** `conftest.py` sets `DATABASE_URL` and `ENABLE_LLM`
  *before* importing the app, and the `db` fixture drops and re-creates every
  table per test, so tests never share state.
- **`db`** — a fresh SQLAlchemy session against the temporary database.
- **`client`** — a FastAPI `TestClient` wired to the same database.
- **`blackboard`** — a `Blackboard` facade bound to the test session.
- **`run_investigation_sync(db, investigation_id)`** — runs an investigation to
  completion synchronously, so tests over agent output are deterministic instead
  of racing the background thread. Prefer this over starting an investigation and
  polling.

Tests that need fully populated data load the demo scenario
(`app.demo.scenario.load_demo`) and then drive it with
`run_investigation_sync`, rather than asserting on a fresh, empty blackboard.

---

## 5. Frontend checks

From the `frontend/` directory:

```powershell
npm run build      # tsc -b && vite build  (type-check + production build)
npm run lint       # tsc -b --noEmit       (type-check only)
```

`npm run build` is the authoritative gate: it fails the build on any type error.
There is no runtime test runner wired into CI for the frontend; correctness of
the API client and pages is enforced by the TypeScript build plus the backend
contract tests.

---

## 6. Evaluation harness

The evaluation harness measures conflict-detection quality, evidence
verification and traceability against labelled sets. From `backend/`:

```powershell
.\venv\Scripts\python.exe -m evaluation.run_evaluation
```

It uses a throwaway database and upload directory and is fully deterministic
(LLM off). Results are written to `evaluation/results/` as `summary.json` and
`summary.md`. See `evaluation/README.md` for the metric definitions and the
documented known failures.

The same labelled datasets are exercised through the app in
`test_evaluation_dashboard.py`, which covers:

- idempotent seeding of `builtin:conflict-detection` (32 cases) and
  `builtin:evidence-verification` (9 cases);
- creating and uploading user-labelled test sets;
- executing both kinds through the **real** extraction, conflict-detection and
  fact-verification code in an isolated in-memory database;
- verifying headline metrics are recomputed from persisted per-case results
  (including the documented TP=10/FP=1/FN=2/TN=19 conflict benchmark);
- dashboard aggregation of agent and document statistics;
- CSV and PDF export content, and 409 handling for failed runs;
- validation errors, cascade deletion and the no-pollution guarantee (runs never
  create real `Document` rows).

Because evaluation runs execute production code, this module is intentionally
slower than the pure unit tests; it still uses the shared test database and needs
no network or API key.

---

## 7. Adding tests

- Prefer the `test_*` naming convention and mirror the existing file for the
  subsystem you are changing.
- Cover the new behaviour **and** its edge cases (empty input, unknown values,
  fallbacks).
- Keep assertions on persisted records where the feature claims traceability.
- Run the full backend suite before finishing:

```powershell
.\venv\Scripts\python.exe -m pytest app\tests -q
```

For a new backend feature, a typical addition is one focused test module plus an
entry in this table.
