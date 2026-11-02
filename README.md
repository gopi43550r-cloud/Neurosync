# NeuroSync

**An evidence-driven, multi-agent investigation workspace built on a Blackboard
Architecture.**

NeuroSync ingests documents, extracts structured claims, detects contradictions
across sources, and then lets a collective of specialized reasoning agents
investigate those conflicts. Agents never talk to each other directly — they
read from and write to a **shared blackboard**. A dynamic scheduler decides which
agent should act next, based on severity, uncertainty, evidence gaps and expected
information gain. Every action, piece of evidence and conclusion is transparent
and traceable.

> NeuroSync runs fully **without any AI API key**. With no credentials configured
> it uses deterministic, rule-based reasoning so results are reproducible. If you
> provide an OpenAI-compatible key and enable AI-assisted mode in **Settings**, the
> agents can additionally use a language model — but the app remains functional
> and correct without it, and every model suggestion is validated against the
> source documents before it is used.

**Version 1.0.0** · [Release notes](docs/release_notes.md) · [Changelog](CHANGELOG.md) · [Known issues](docs/known_issues.md)

---

## Highlights

- **Blackboard architecture** — a single shared knowledge store (documents →
  claims → conflicts → evidence → hypotheses → conclusions).
- **Six specialized agents** — Evidence Collector, Conflict Detector, Hypothesis
  Generator, Investigator, Verification Agent, Decision Agent.
- **Dynamic scheduler** — scores candidate actions each cycle; the highest-value
  action wins, and every decision is logged with its reason.
- **Transparent conflict detection** — deterministic rules for direct
  contradictions, numerical disagreement, temporal inconsistency, missing context
  and more, each with a human-readable "why was this flagged?" explanation.
- **Evidence weighting** — hypotheses are scored from evidence relevance,
  reliability and directness, with support/contradiction accounting.
- **Explainable hypothesis ranking** — competing hypotheses are ranked by
  transparent criteria (supporting/contradicting evidence weight, distinct
  sources, directness), each listing the evidence that supports or opposes it and
  the gap to the next explanation.
- **Human-in-the-loop review** — a reviewer can approve, reject or request more
  investigation on any conclusion; the decision is timestamped, attributed and
  updates the conflict status.
- **Audit trail** — every change to the blackboard (claims, evidence, hypotheses,
  verifications, conflicts, conclusions, reviews) is recorded with actor and time.
- **Optional, validated AI assistance** — a provider-independent LLM layer that is
  off by default and selected at runtime in Settings. When enabled it assists
  claim extraction, hypothesis generation, evidence interpretation and
  explanation. Model output is treated as untrusted: document text is passed as
  data (prompt-injection hardened), supporting quotes must appear verbatim in the
  documents, and any citation that does not match real evidence is discarded.
- **Claim-level fact verification** — every extracted claim is compared with the
  documents, claims and evidence that actually exist, producing `supported`,
  `contradicted`, `partially_supported` or `unverified` with grounded citations
  (document, page/character location, snippet) and an explicit missing-information
  list. Only independent sources count as corroboration; insufficient evidence is
  always `unverified`.
- **Source credibility analyzer** — six factors (source authenticity,
  author/organization, publication date, evidence quality, source traceability and
  consistency with other sources) assessed on read from stored records. Unknown
  inputs are excluded and reported instead of being scored as zero, and credentials
  are never inferred. Integrated into Documents, Evidence and Investigations.
- **Grounded investigation chat** — ask why a conflict was detected, which
  document supports a claim, what contradicts a hypothesis, why an investigation
  is inconclusive, or what evidence is still required. The assistant is
  deterministic and scoped to one investigation's Blackboard records; every answer
  carries numbered citations to stored documents (with page or character location)
  and says explicitly when the records cannot answer.
- **Uncertainty handling** — missing evidence and informational gaps are surfaced
  explicitly rather than hidden behind a single confidence number.
- **Real-time experience** — investigations stream server-sent events; the UI
  shows live agent activity, the blackboard graph and an event feed.
- **Reports** — export investigations as Markdown or JSON with a confidence
  explanation, hypothesis ranking, evidence gaps and explicit limitations.
- **Clearly labelled demo data** — an industrial diagnostic scenario is shipped
  and always marked as demonstration data.

---

## Architecture at a glance

```
                 ┌──────────────────────── Blackboard ────────────────────────┐
                 │  documents · claims · conflicts · evidence · hypotheses     │
                 │  conclusions · activity log · events                        │
                 └───────▲───────────────▲───────────────▲───────────────▲────┘
                         │ read/write    │               │               │
   Evidence Collector ───┘   Conflict Detector   Hypothesis Generator   Investigator
                                                     Verification Agent   Decision Agent
                         ▲
                 Dynamic Scheduler (severity · uncertainty · evidence gap · info gain)
```

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full design, the
scheduler formula, the conflict rules and the scoring model.

---

## Tech stack

| Layer     | Technology                                                             |
| --------- | --------------------------------------------------------------------- |
| Backend   | FastAPI, SQLAlchemy 2.0, Pydantic v2, SQLite, Uvicorn                 |
| Extraction| PyMuPDF (PDF), python-docx (DOCX), rule-based NLP for text formats    |
| Frontend  | React 19, TypeScript, Vite, Tailwind CSS v4, React Flow, Recharts     |
| Realtime  | Server-Sent Events (SSE)                                               |
| Tests     | pytest (backend)                                                      |

---

## Quickstart

### Prerequisites

- Python 3.11+
- Node.js 18+

### 1. Backend

```powershell
cd neurosync/backend
python -m venv venv
.\venv\Scripts\Activate.ps1          # Windows PowerShell
# source venv/bin/activate            # macOS / Linux

pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

The API is now at `http://127.0.0.1:8000` (interactive docs at `/docs`).

Optional: copy `.env.example` to `.env` to change the database URL, CORS origins,
upload limits or scheduler weights, or to enable LLM assistance.

### 2. Frontend

```powershell
cd neurosync/frontend
npm install
npm run dev
```

Open `http://localhost:5173`. The dev server proxies `/api` to the backend.

### 3. See it work in 30 seconds

1. Open the app → **Overview** → click **Load demo**.
2. You are taken to the **Investigation workspace**; click **Start** if it is not
   already running.
3. Watch the agents work in real time: the activity timeline and live event
   stream update as claims are extracted, conflicts detected, hypotheses
   proposed, evidence gathered and a decision reached.
4. Open **Conflicts** to read the "why flagged" explanation, compare the two
   claims side by side, and inspect evidence and hypotheses.
5. Open **Reports** to read and export the result as Markdown or JSON.

---

## Running the tests

```powershell
cd neurosync/backend
.\venv\Scripts\python.exe -m pytest app/tests -q
```

The suite covers extraction, conflict detection, agent behaviour, the scheduler,
the blackboard, hypothesis ranking, the audit trail, human review, claim-level
fact verification, the source-credibility analyzer, the grounded investigation
chat, the optional LLM layer (parsing, retries, grounding/citation validation and
prompt-injection hardening — all with a mocked provider, so no API key or network
is needed), the demonstration scenario, the full HTTP API, and the evaluation
harness.

### Running the evaluation

A curated, labelled evaluation harness measures how reliably the system detects
contradictions, evaluates evidence sufficiency and produces traceable
conclusions. It runs the real pipeline in deterministic mode against an isolated
temporary database (your data is never touched):

```powershell
cd neurosync/backend
.\venv\Scripts\python.exe -m evaluation.run_evaluation
```

Reports are written to `evaluation/results/`. See
[`backend/evaluation/README.md`](backend/evaluation/README.md) for the dataset,
labels, metrics, failure cases and limitations.

---

## Project layout

```
neurosync/
├── backend/
│   ├── app/
│   │   ├── agents/          # the six reasoning agents + base class
│   │   ├── api/             # FastAPI routers (documents, conflicts, SSE, …)
│   │   ├── blackboard/      # blackboard service, graph, scheduler, controller
│   │   ├── demo/            # labelled demonstration scenario
│   │   ├── models/          # SQLAlchemy models + enums
│   │   ├── schemas/         # Pydantic request/response models
│   │   ├── services/        # extraction, conflicts, evidence, scoring, ranking, audit, review, reports, llm, settings
│   │   ├── tests/           # pytest suite
│   │   ├── config.py        # env-driven settings
│   │   └── main.py          # app assembly
│   ├── evaluation/          # labelled evaluation harness (datasets, metrics, reports)
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   └── src/
│       ├── api/             # typed API client
│       ├── components/      # shell, UI primitives, badges, toasts
│       ├── hooks/           # data fetching + SSE
│       └── pages/           # the eleven application pages
├── docs/
│   ├── ARCHITECTURE.md      # design, scheduler, scoring, knowledge graph
│   ├── API_REFERENCE.md     # endpoint-by-endpoint reference
│   ├── TESTING.md           # test layout, fixtures, evaluation harness
│   ├── FEATURE_GAP_ANALYSIS.md
│   ├── orchestration.md     # agent scheduler / blackboard design
│   ├── deployment.md        # public-hosting guide
│   ├── performance.md       # benchmarks and scale notes
│   ├── user_guide.md
│   ├── multi_user_evaluation.md
│   ├── release_notes.md
│   ├── release_checklist.md
│   └── known_issues.md
├── scripts/                 # backup.sh / restore.sh
├── docker-compose.yml       # local development stack
├── docker-compose.prod.yml  # production stack (Caddy + automatic HTTPS)
├── Caddyfile
├── .env.prod.example
└── README.md
```

---

## Docker

Development stack:

```powershell
cd neurosync
docker compose up --build
```

Frontend on `http://localhost:5173`, backend on `http://localhost:8000`.

For a public host, use the separate production stack (Caddy terminates TLS, the
backend has no public port, and the API token is injected server-side):

```bash
cp .env.prod.example .env    # fill in the required values
docker compose -f docker-compose.prod.yml up -d --build
```

See [`docs/deployment.md`](docs/deployment.md) for the full guide, including
configuration, HTTPS, access restriction, backups and a verification checklist.

---

## Configuration

All configuration is environment-driven (see `backend/.env.example`):

| Variable                   | Default                              | Purpose                                  |
| -------------------------- | ------------------------------------ | ---------------------------------------- |
| `DATABASE_URL`             | `sqlite:///./neurosync.db`           | Database connection string               |
| `CORS_ORIGINS`             | `http://localhost:5173,...`          | Allowed frontend origins                 |
| `MAX_UPLOAD_MB`            | `25`                                 | Per-file upload limit                    |
| `ENVIRONMENT`              | `development`                        | `production` for a hardened deployment   |
| `UPLOAD_DIR`               | _(backend/uploads)_                  | Upload storage dir (persistent volume)   |
| `LOG_LEVEL` / `LOG_FORMAT` | `INFO` / `text`                      | Log verbosity and `text`/`json` format   |
| `ENABLE_DOCS`              | `true`                               | Serve `/docs`; disable in production     |
| `TRUSTED_HOSTS`            | `*`                                  | Allowed Host headers (set in production) |
| `API_TOKEN`                | _(empty)_                            | Bearer token required on every `/api` route |
| `WEIGHT_SEVERITY`          | `0.30`                               | Scheduler weight: conflict severity      |
| `WEIGHT_UNCERTAINTY`       | `0.25`                               | Scheduler weight: uncertainty            |
| `WEIGHT_EVIDENCE_GAP`      | `0.25`                               | Scheduler weight: evidence gaps          |
| `WEIGHT_INFO_GAIN`         | `0.20`                               | Scheduler weight: expected information   |
| `DEFAULT_ITERATION_LIMIT`  | `25`                                 | Default max scheduler cycles             |
| `DEFAULT_MIN_EVIDENCE`     | `1`                                  | Default evidence threshold before a call |
| `ENABLE_LLM`               | `false`                              | Allow LLM assistance (deployment switch) |
| `LLM_PROVIDER`             | `openai`                             | Provider identifier (OpenAI-compatible)  |
| `OPENAI_API_KEY`           | _(empty)_                            | Key for an OpenAI-compatible endpoint    |
| `OPENAI_MODEL`             | `gpt-4o-mini`                        | Model name when LLM is enabled           |
| `OPENAI_BASE_URL`          | `https://api.openai.com/v1`          | Base URL of the OpenAI-compatible API    |
| `LLM_TIMEOUT_SECONDS`      | `30`                                 | Per-request timeout                      |
| `LLM_MAX_RETRIES`          | `2`                                  | Retry attempts for transient failures    |

> `ENABLE_LLM` and a key make AI *available*; the user-ready **reasoning mode**
> toggle in Settings (`deterministic` / `ai_assisted`, stored in the DB) decides
> whether it is actually used. If AI is selected without a configured provider,
> the app reports this and runs deterministically rather than failing.

---

## Optional AI-assisted reasoning

The reasoning engine is switchable at runtime from **Settings → Reasoning mode**:

- **Deterministic** (default) — pure rule-based reasoning. Fully reproducible and
  requires no credentials or network.
- **AI-assisted** — the same agents, but they may additionally consult an
  OpenAI-compatible language model for claim extraction, hypothesis generation,
  evidence interpretation and natural-language explanations.

Safety properties, all enforced in code and covered by tests:

- **Off by default; no key required.** With no provider configured, selecting
  AI-assisted mode gracefully degrades to deterministic and the API reports why.
- **Documents are data, not instructions.** Document text is wrapped in explicit
  data delimiters and the system prompt forbids following embedded instructions,
  mitigating prompt injection.
- **No fabricated evidence or citations.** Any supporting quote the model returns
  must appear verbatim in the source document, and any citation must reference a
  real evidence record — otherwise the suggestion is dropped.
- **Transparent provenance.** LLM-derived claims, hypotheses and evidence are
  tagged (`ai_suggested`) so they are always distinguishable from rule-based ones.
- **Resilient to provider failures.** Timeouts, rate limits, 5xx and malformed
  responses are retried and then fall back to deterministic behaviour without
  crashing an investigation.
- **Keys never leak.** The API key is only sent in the `Authorization` header and
  is never logged or returned in a response.

To enable it:

```powershell
# backend/.env
ENABLE_LLM=true
OPENAI_API_KEY=sk-...
# optional:
OPENAI_MODEL=gpt-4o-mini
OPENAI_BASE_URL=https://api.openai.com/v1
```

Then choose **AI-assisted** under Settings. See
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the provider interface and the
validation pipeline.

---

## Release

Current version: **1.0.0**. The version is declared in `backend/app/__init__.py`,
`backend/app/config.py` (`app_version`) and `frontend/package.json`, and is
reported by `GET /api/health`.

- [Release notes](docs/release_notes.md) — verified test, build, evaluation and
  readiness results for this version.
- [Release checklist](docs/release_checklist.md) — run before every release.
- [Changelog](CHANGELOG.md) · [Known issues and limitations](docs/known_issues.md).

---

## License

Provided as a reference implementation for demonstration and evaluation.
