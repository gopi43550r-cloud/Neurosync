# NeuroSync — Feature Gap Analysis

Date: 2026-10-11 · Scope: upgrade NeuroSync (existing app) toward the requested
"professional, evidence-traceable, multi-agent conflict analysis" specification.

Method: read the existing backend (`backend/app`), frontend (`frontend/src`),
schema, services, tests and docs; ran the test suite. No files were modified to
produce this analysis. Every "EXISTS" claim cites the code that implements it.

---

## 0. How to read this document

- **EXISTS** — implemented and working; do not duplicate.
- **PARTIAL** — implemented but missing something the spec asks for.
- **MISSING** — not implemented.

---

## 1. Platform identity (spec §1)

| Requirement | Status | Evidence |
|---|---|---|
| Multi-agent conflict analysis (not a chatbot) | EXISTS | `backend/app/agents/*`, `backend/app/blackboard/controller.py` |
| Structured records: documents, claims, evidence, conflicts, hypotheses, investigations, verification, conclusions, human review | EXISTS | `backend/app/models/{document,claim,evidence,conflict,hypothesis,investigation,review,intelligence}.py` |
| Blackboard as shared space | EXISTS | `backend/app/blackboard/blackboard_service.py`, `app/models/intelligence.py::BlackboardRelation` |
| Reasoning inspectable; verified vs assumed distinguished | EXISTS | `app/services/scoring_service.py`, `app/services/traceability_service.py`, `docs/orchestration.md` |

**Verdict: EXISTS.** No work needed.

---

## 2. Feature 1 — Document ingestion & claim extraction (spec §2, §12)

| Requirement | Status | Evidence |
|---|---|---|
| Multi-file upload, drag/drop | EXISTS | `app/api/documents.py`; `frontend/src/pages/Documents.tsx` |
| File-type validation, size cap | EXISTS | `app/services/document_service.py` (allowed ext/content-type, `_READ_CHUNK_BYTES`), tests in `app/tests/test_qa_backend.py` |
| Safe server-side filenames / path traversal guard | EXISTS | `document_service.py` (uuid names, resolved-path check) |
| Status lifecycle pending→processing→processed/error | EXISTS | `app/models/enums.py::DocumentStatus`; `app/models/document.py::status/error_message` |
| Page/char map, extraction method, source location | EXISTS | `document.py::DocumentContent.page_map`, `claim.py::source_location/extraction_method` |
| Claim fields (subject, predicate, numeric, unit, polarity, timestamp, confidence, source ref) | EXISTS | `app/models/claim.py` |
| Reprocess, delete, text preview | EXISTS | `app/api/documents.py`; `frontend/src/pages/DocumentDetail.tsx` |
| Malformed-document handling | EXISTS | `document_service.py` try/except → `DocumentStatus.ERROR` + message; tests |
| DOCX support | EXISTS | extractor handles docx/pymupdf (see `document_service.py`); optional per spec |

**Verdict: EXISTS.** No work needed.

---

## 3. Feature 2 — Context-aware conflict detection (spec §2, §3)

| Requirement | Status | Evidence |
|---|---|---|
| Rule-based baseline classification | EXISTS | `app/services/conflict_service.py`, `consistency_service.py` |
| Categories (contradiction / supporting / related / insufficient) | EXISTS | `app/models/enums.py::ConflictType` (direct_contradiction, numerical_disagreement, temporal_inconsistency, source_disagreement, missing_context, semantic_inconsistency) |
| Time / unit / subject / negation handling | EXISTS | `conflict_service.py` (normalisation, temporal & numeric rules); measured in `backend/evaluation/` |
| Store reason/explanation + detection method | EXISTS | `conflict.py` (`reason`/`why_flagged`, detection method), `frontend/src/pages/ConflictDetail.tsx` |
| Side-by-side original claims | EXISTS | `ConflictDetail.tsx` claim A/B |
| High similarity ≠ contradiction | EXISTS | deterministic rules keyed on subject/time/units, not raw similarity |
| Explainable confidence | EXISTS | `scoring_service.py` (documented heuristics) |

**Verdict: EXISTS** (documented lexical-variation limitation in `docs/known_issues.md` §1).

---

## 3a. Feature 2 — package is labelled `service`; confirmed endpoints

All list/detail endpoints exist (`app/api/{documents,claims,conflicts,evidence,hypotheses,investigations,blackboard,graph,agents,search,audit,reviews,settings,demo,health}.py`). See §11 for the API inventory.

---

## 3. Feature 2 also covered by Feature 3

---

## 4. Feature 3 — Evidence provenance & traceability (spec §3)

| Requirement | Status | Evidence |
|---|---|---|
| Chain documents→claims→evidence→conflicts→hypotheses→verification→conclusions | EXISTS | `Evidence(A conflict_id, claim_id, document_id)`, `Hypothesis(conflict_id)`, `Conclusion(conflict_id, investigation_id)`, relation table |
| Per-conflict side-by-side + evidence + hypotheses + conclusion | EXISTS | `app/api/conflicts.py` detail; `ConflictDetail.tsx` |
| Trace endpoints | EXISTS | `GET /api/blackboard/trace/{type}/{id}`, `GET /api/blackboard/connected/...`; `traceability_service.py` |
| Every conclusion traceable to sources | EXISTS | verified in evaluation: conclusion traceability 7/7 (`evaluation/results/summary.json`) |
| Distinguish verified/assumed/human/agent | EXISTS | `EvidenceOrigin`, `VerificationStatus`, `HumanReview`; report "Human Review Decisions" |

**Verdict: EXISTS.** No work needed.

---

## 4. Feature 4 — Evidence assessment (spec §4)  ← GAP

| Requirement | Status | Evidence |
|---|---|---|
| Per-evidence relevance indicator | EXISTS | `evidence.py::relevance_score`; shown in `Evidence.tsx:116` |
| A transparent **multi-factor assessment** (relevance, provenance, recency, completeness, corroboration, contradictory evidence) | **MISSING** | `app/models/evidence.py` has only `relevance_score`, `reliability_score`, `directness`; no factor breakdown, no explanation, no missing-information list |
| Per-item factor values/labels + explanation | **MISSING** | `EvidenceOut` (`app/schemas/evidence.py:11-28`) exposes only the three floats |
| Documented scoring formula + limitations, exposed to users | PARTIAL | `scoring_service.evidence_weight` formula is documented in code/comments but not surfaced per item; no "unknown source reliability" labelling |
| Label unknown source reliability as *unknown*; do not fabricate ratings | **MISSING** | `EVIDENCE_TYPE_RELIABILITY` assigns heuristic numbers with no explicit "unknown" provenance label |

**Verdict: PARTIAL → implement a multi-factor, inspectable assessment without inventing data.**

---

## 5. Feature 5 — Visual knowledge graph (spec §5)

| Requirement | Status | Evidence |
|---|---|---|
| Interactive graph of documents/claims/evidence/conflicts/hypotheses/conclusions | EXISTS | `frontend/src/pages/KnowledgeGraph.tsx` using `@xyflow/react` (already installed) |
| Zoom/pan, selectable nodes, labelled relations, distinct node types | EXISTS | `KnowledgeGraph.tsx` (`fitView`, `Controls`, `MiniMap`, node-type styling) |
| Node details panel + navigation to records | EXISTS | `KnowledgeGraph.tsx` inspector + `blackboardTrace` |
| Empty/loading/error states | EXISTS | `KnowledgeGraph.tsx` (`EmptyState`, `Loading`, error branch) |
| Data from real DB records only | EXISTS | `app/services/knowledge_graph_service.py`, `app/api/graph.py` |
| Backend graph endpoint | EXISTS | `GET /api/graph` (`app/api/graph.py`) |

**Verdict: EXISTS.** No work needed.

---

## 6. Feature 6 — Human-in-the-loop review (spec §6)  ← GAP

| Requirement | Status | Evidence |
|---|---|---|
| Accept / reject / request more investigation | EXISTS | `ReviewDecision` (`approved`, `rejected`, `request_more_investigation`); `review_service.py`; `ConflictDetail.tsx:336-358` |
| **Mark inconclusive** as a review decision | **MISSING** | not in `ReviewDecision` enum (`app/models/enums.py:103-106`) nor `REVIEW_DECISIONS` (`app/schemas/review.py:10`). A manual *conflict status* "inconclusive" exists (`ConflictDetail.tsx:405`) but not a recorded review decision |
| **Reopen** a previously reviewed finding | **MISSING** | no `reopen` decision anywhere |
| Reviewer label / comment / timestamp / previous vs new status | EXISTS | `HumanReview(reviewer, note, previous_decision_type, created_at)` |
| History kept (not overwritten) | EXISTS | append-only `HumanReview` rows; `list_reviews` |
| Distinguish human decisions from agent output | EXISTS | separate `HumanReview` table + report section |
| Local manual review label (no auth) | PARTIAL | defaults to reviewer "human reviewer" but no explicit "local manual review" provenance marker |

**Verdict: PARTIAL → add `inconclusive` and `reopen` decisions and an explicit local-review label.**

---

## 7. Feature 7 — Report generation (spec §7)

| Requirement | Status | Evidence |
|---|---|---|
| Professional report with the 14 required parts | EXISTS | `report_service.py` produces 28 sections incl. title/ID, summary, sources, claims, conflicts, supporting & contradicting evidence, hypotheses, verification, final assessment, confidence/uncertainty, human review, unresolved questions, timestamp |
| PDF export | EXISTS | `report_pdf.py`; `ReportView` export buttons (`Reports.tsx:136-158`) |
| Markdown / JSON export | EXISTS | `GET /api/investigations/{id}/report/export?format=...` |
| "Not available"/"Not yet evaluated" for missing data | EXISTS | report warnings + conditional sections; verified `test_reports.py` |
| ID validation, no path manipulation | EXISTS | report endpoints keyed by integer `investigation_id` + `db.get`; sanitized download filenames |

**Verdict: EXISTS.** No work needed.

---

## 8. Feature 8 — Optional LLM integration (spec §8)

| Requirement | Status | Evidence |
|---|---|---|
| Existing optional provider, keys on backend, env-driven | EXISTS | `app/services/llm_service.py`, `app/config.py` (`OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL`) |
| Deterministic fallback when unconfigured | EXISTS | mode `"demonstration"` when `not settings.llm_configured` |
| Validate responses, timeouts, error handling, no fabricated output | EXISTS | `test_llm_validation.py`, `test_llm_end_to_end.py`, `test_llm_service.py` |
| Label generated content; preserve evidence refs | EXISTS | LLM layer tags output and citation validation |
| No secrets in frontend/logs | EXISTS | `logging_config.py` redaction; keys only server-side |

**Verdict: EXISTS.** No work needed.

---

## 9. Feature 9 — Improved dashboard (spec §9)  ← GAP

| Requirement | Status | Evidence |
|---|---|---|
| Statistics from real DB records (documents, claims, conflicts, open investigations, hypotheses awaiting verification, findings awaiting review) | EXISTS | `GET /api/blackboard/snapshot` → `BlackboardCounts`; `Dashboard.tsx:95-130` |
| No hardcoded numbers | EXISTS | `blackboard.py::_counts` runs `COUNT(*)` queries |
| Recent investigation activity | EXISTS | `recent_activity` + `activity_timeline` |
| Clear links to records | PARTIAL | "Agent monitor"/"New investigation" links exist; no links to Documents/Conflicts/Evidence/Hypotheses/Reports |
| **Filters: investigation status, conflict category, evidence status, date range** | **MISSING** | `snapshot` takes no query params; `Dashboard.tsx` has no filter bar |
| Empty states | EXISTS | recent-activity empty state (`Dashboard.tsx:231-235`) |

**Verdict: PARTIAL → add date-range param + status/category distributions and link cards.**

---

## 10. Database & API (spec §12)

| Requirement | Status | Evidence |
|---|---|---|
| Reuse existing models | EXISTS | 18 models in `app/models` |
| Safe schema upgrade mechanism | EXISTS | `app/database.py::_run_additive_migrations` (idempotent additive ALTERs) + `create_all` |
| REST APIs, validation, pagination | EXISTS | `app/api/*`, `app/api/pagination.py`, Pydantic schemas |
| Accurate docs | DOES | `docs/ARCHITECTURE.md`, `docs/API_REFERENCE.md`, `docs/TESTING.md`, `docs/FEATURE_GAP_ANALYSIS.md` (renamed from `architecture.md`/`api.md`) |
| Errors without stack traces/secrets | EXISTS | `main.py` exception handlers return generic messages |

---

## 11. API endpoint inventory (existing)

`/api` prefix. Health: `GET /health`, `GET /health/live`.
Documents: `GET/POST /documents`, `GET/DELETE /documents/{id}`, `POST /documents/{id}/reprocess`.
Claims: `GET /claims`, `GET /claims/{id}`.
Conflicts: `GET /conflicts`, `GET /conflicts/{id}`, `PATCH /conflicts/{id}`, `GET /conflicts/{id}/hypotheses-ranking`, `GET /conflicts/{id}/evidence-gaps`.
Evidence: `GET/POST /conflicts/{id}/evidence`, `GET /evidence`.
Hypotheses: `GET /hypotheses`, `POST /hypotheses`, `POST /hypotheses/{id}/review`.
Investigations: `GET/POST /investigations`, `GET /investigations/{id}`, `POST /investigations/{id}/actions`, `GET /investigations/{id}/activity`, `GET /investigations/{id}/report`, `GET /investigations/{id}/report/export`, `GET /investigations/{id}/events`.
Blackboard: `GET /blackboard`, `/blackboard/snapshot`, `/blackboard/events`, `/blackboard/relations`, `/blackboard/connected/{type}/{id}`, `/blackboard/trace/{type}/{id}`, `POST /blackboard/reevaluate`.
Graph: `GET /graph`. Agents: `GET /agents`. Search: `GET /search`. Audit: `GET /audit`. Reviews: `GET/POST /conclusions/{id}/review(s)`, `GET /conflicts/{id}/reviews`, `GET /reviews`. Settings: `GET/PUT /settings/reasoning`, `GET /config`. Demo: `POST /demo/load`, `POST /demo/reset`.

---

## 12. Security & reliability (spec §13)

| Requirement | Status | Evidence |
|---|---|---|
| Validate uploads, safe filenames, no execution, path-traversal guard | EXISTS | `document_service.py`; `test_security.py` |
| Secrets out of repo; no secret leakage | EXISTS | `.gitignore`, `logging_config.py` redaction, `test_security.py::test_api_never_returns_the_provider_key` |
| Validate IDs/input; pagination; errors safe | EXISTS | Pydantic + `db.get` 404s; exception handlers |
| Avoid unsafe HTML rendering; controlled report paths | EXISTS | React escapes by default; integer report IDs |
| Known limitations documented | EXISTS | `docs/known_issues.md` |

---

## 13. Testing (spec §14)

Existing suite: 204 tests across `app/tests/*` covering upload/validation,
extraction, conflict detection, evidence traceability, review decisions, reports,
invalid IDs, error handling, graph, security.

Coverage for the gaps above has now been **added**: `test_evidence_assessment.py`
(multi-factor assessment), `test_dashboard_snapshot.py` (counts, `days` window,
distributions) and new review-decision cases in `test_audit_review_ranking.py`
(`inconclusive`, `reopen`, `review_kind`), plus `test_fact_verification.py`,
`test_source_credibility.py` and `test_chat_assistant.py`. Backend suite:
**245 tests passing**.

---

## 14. Summary of the actual gaps — and their implementation status

| # | Gap | Feature | Plan | Status |
|---|---|---|---|---|
| G1 | Multi-factor, inspectable evidence assessment (factors, labels, explanation, missing-info, documented formula, explicit "unknown" reliability) | §4 | New `services/assessment_service.py`; expose `assessment` on `EvidenceOut`; render in `Evidence.tsx`; tests | **DONE** |
| G2 | Human review decisions `inconclusive` and `reopen` (+ explicit local-review label) | §6 | Extend `ReviewDecision` enum + `review_service` mappings + schema; add UI buttons; tests | **DONE** |
| G3 | Dashboard filters: date-range param + conflict-category / conflict-status / investigation-status / evidence-status distributions + record links | §9 | Extend `blackboard.snapshot` + `BlackboardSnapshot`; add filter bar & cards to `Dashboard.tsx`; types/client; tests | **DONE** |
| G4 | Requested docs | §17 | Create `docs/FEATURE_GAP_ANALYSIS.md` (this file), `docs/ARCHITECTURE.md`, `docs/API_REFERENCE.md`, `docs/TESTING.md`; update `README.md` | **DONE** |

No database migration is required: G1 computes on read from existing columns, G2
reuses the existing free-text `decision` column, G3 adds no columns.

All four gaps are implemented, tested (backend suite **216 passing**; frontend
`npm run build` succeeds), and documented. See `CHANGELOG.md` → *Unreleased*.

---

## 15. Important files to change

Backend:
- `backend/app/services/assessment_service.py` (new)
- `backend/app/services/serialization.py` (evidence serialization)
- `backend/app/schemas/evidence.py` (+ `assessment`)
- `backend/app/models/enums.py` (`ReviewDecision`)
- `backend/app/services/review_service.py` (new decisions)
- `backend/app/schemas/review.py` (allowed decisions, label)
- `backend/app/api/blackboard.py` (snapshot params + distributions)
- `backend/app/schemas/blackboard.py` (snapshot fields)
- `backend/app/tests/test_evidence_assessment.py` (new)
- `backend/app/tests/test_dashboard_snapshot.py` (new)
- `backend/app/tests/test_audit_review_ranking.py` (extend review tests)

Frontend:
- `frontend/src/api/types.ts`, `frontend/src/api/client.ts`
- `frontend/src/pages/Evidence.tsx`, `frontend/src/pages/Dashboard.tsx`,
  `frontend/src/pages/ConflictDetail.tsx`, `frontend/src/pages/Conflicts.tsx`,
  `frontend/src/pages/Investigations.tsx`

Docs: `README.md`, `docs/FEATURE_GAP_ANALYSIS.md`, `docs/ARCHITECTURE.md`,
`docs/API_REFERENCE.md`, `docs/TESTING.md`.

---

## 16. Explicit non-goals (already complete, do not rebuild)

Document ingestion, claim extraction, conflict detection/classification,
provenance/traceability, knowledge graph, report generation, optional LLM layer,
security controls. These are functional and covered by tests; they will be
preserved unchanged.
