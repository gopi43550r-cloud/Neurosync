# Changelog

All notable changes to NeuroSync are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

The version is declared in three places and they must stay in step:

- `backend/app/__init__.py` — `__version__`
- `backend/app/config.py` — `Settings.app_version`
- `frontend/package.json` — `version`

---

## [Unreleased]

### Added

- **Claim-level fact verification** — claims are verified against the documents,
  claims and evidence already stored, producing `supported`, `contradicted`,
  `partially_supported` or `unverified` with grounded citations (document,
  page/character location, snippet), a rationale and a missing-information list.
  Only independent sources count as corroboration; optional AI rationale cannot
  change the verdict and fabricated citations are rejected
  (`services/fact_verification_service.py`, `/api/verification/*`). Rendered on
  the Evidence page, document claims and the investigation workspace.
- **Source credibility analyzer** — six-factor assessment of each stored source
  (authenticity, author/organization, publication date, evidence quality,
  traceability and consistency with other sources), computed on read. Unknown
  factors return `score: null` and are excluded from the aggregate rather than
  scored as zero; no credentials are inferred from filenames or text
  (`services/source_credibility_service.py`, `/api/source-credibility`).
  Integrated into Documents, Evidence and Investigations.
- **Grounded investigation chat** — deterministic, investigation-scoped Q&A
  answering why a conflict was detected, which document supports a claim, what
  evidence contradicts a hypothesis, why the investigation is inconclusive and
  what additional evidence is required. Every answer uses only stored Blackboard
  rows, attaches numbered citations to documents (with page or character
  location), explicitly states when information is insufficient and refuses to
  answer from other investigations (`services/chat_assistant_service.py`,
  `/api/investigations/{id}/chat`, `/api/investigations/{id}/chat/suggestions`).
  Integrated into the investigation workspace.
- **Multi-factor evidence assessment** — every evidence item now carries an
  inspectable `assessment` object (relevance, provenance, recency, completeness,
  corroboration, contradictory-evidence penalty) with per-factor labels,
  explanations, a `missing_information` list, the documented formula and an
  explicit `unknown` source-reliability label rather than an invented value
  (`services/assessment_service.py`). Rendered on the Evidence page.
- **Human-review decisions `inconclusive` and `reopen`** — the review service and
  API now accept these two additional decisions, mapped to the `inconclusive` and
  `open` conflict statuses; the UI exposes them on the conflict detail page.
  Reviews report `review_kind = "local_manual_review"`.
- **Dashboard filters and distributions** — `GET /api/blackboard/snapshot` now
  accepts a `days` window (default 14) and returns four enum distributions
  (`conflict_type`, `conflict_status`, `investigation_status`,
  `evidence_verification`), each covering every known value. The Overview
  dashboard adds a 7/14/30/90-day selector and clickable distribution cards that
  deep-link into pre-filtered list pages (Conflicts, Evidence, Investigations now
  initialise filters from URL query parameters).
- **Documents** — `docs/ARCHITECTURE.md`, `docs/API_REFERENCE.md`,
  `docs/TESTING.md` and `docs/FEATURE_GAP_ANALYSIS.md`.

### Changed

- Renamed `docs/architecture.md` → `docs/ARCHITECTURE.md` and `docs/api.md` →
  `docs/API_REFERENCE.md`.

### Tests

- Added `test_fact_verification.py`, `test_source_credibility.py`,
  `test_evidence_assessment.py`, `test_dashboard_snapshot.py`,
  `test_chat_assistant.py` and new review-decision cases in
  `test_audit_review_ranking.py`. Backend suite: **245 tests passing**.

---

## [1.0.0] — 2026-10-11

First stable release. NeuroSync is an evidence-driven, multi-agent investigation
workspace built on a Blackboard Architecture. It runs fully without any AI API
key (deterministic mode) and optionally uses an OpenAI-compatible model.

### Added

- **Blackboard pipeline** — documents → claims → conflicts → evidence →
  hypotheses → conclusions, with a dynamic scheduler that scores each candidate
  action by severity, uncertainty, evidence gap and expected information gain.
- **Six specialised agents** — Evidence Collector, Conflict Detector, Hypothesis
  Generator, Investigator, Verification Agent, Decision Agent (with an
  orchestrator ledger recording every action, its reason and its blackboard
  changes).
- **Transparent conflict detection** — deterministic rules for direct
  contradictions, numerical disagreement, temporal inconsistency, missing
  context and more, each with a human-readable "why was this flagged?" rationale.
- **Evidence scoring and hypothesis ranking** — bounded support indicators
  (not calibrated probabilities), support/contradiction accounting and a ranked
  comparison with evidence gaps.
- **Human-in-the-loop review** — approve, reject or request more investigation on
  a conclusion; attributed, timestamped and reflected in the audit trail.
- **Audit trail** — an append-only, attributed record of every blackboard change.
- **Optional, validated AI assistance** — provider-independent LLM layer, off by
  default, selectable at runtime; document text is treated as untrusted
  (prompt-injection hardened) and every citation is validated against real
  evidence before use.
- **Live experience** — Server-Sent Events stream investigation progress, and an
  interactive Knowledge Graph projects the blackboard from persisted records only.
- **Reports** — structured reports with a confidence explanation, hypothesis
  ranking, evidence gaps and limitations; exportable as Markdown, JSON and PDF.
- **Demonstration scenario** — the labelled *Machine M-17 Temperature
  Disagreement* investigation.
- **Evaluation harness** — a curated, labelled dataset measuring conflict
  detection, evidence sufficiency and conclusion traceability (see
  `backend/evaluation/README.md`).
- **Deployment tooling** — single-host Docker Compose stack (Caddy + nginx +
  FastAPI/SQLite), backup/restore scripts and a deployment guide.

### Security

- Optional shared-secret bearer token (`API_TOKEN`) required on every `/api/*`
  route (exhaustively covered by tests); disabled by default for loopback-only
  local use.
- CORS origin allow-list, `TrustedHostMiddleware`, security headers and a
  secret-redaction logging filter.
- Upload safety: extension/content-type checks, size caps, safe filenames,
  streamed writes and orphan-file cleanup; extracted-text length cap (zip-bomb
  guard).
- Single-user by design: no user accounts. See
  [`docs/multi_user_evaluation.md`](docs/multi_user_evaluation.md).

### Documentation

- `docs/ARCHITECTURE.md`, `docs/API_REFERENCE.md`, `docs/TESTING.md`,
  `docs/orchestration.md`, `docs/deployment.md`, `docs/performance.md`,
  `docs/user_guide.md`, `docs/multi_user_evaluation.md`, plus this changelog,
  release notes, release checklist and known issues.

### Known limitations

See [`docs/known_issues.md`](docs/known_issues.md). The headline ones: the
rule-based extractor/detector misses lexical-variation cases (measured in the
evaluation), global Knowledge Graph and graph traversal are O(total records),
and a single host/worker is required for the in-process investigation runtime.

[1.0.0]: https://example.invalid/neurosync/releases/tag/v1.0.0
