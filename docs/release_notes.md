# NeuroSync 1.0.0 — Release Notes

- **Version:** 1.0.0 (first stable release)
- **Release date:** 2026-10-11
- **Status:** Release candidate verified locally; **not deployed** (deployment is a
  manual, operator action — see §6).
- **Changelog:** [`../CHANGELOG.md`](../CHANGELOG.md)

All results below were produced by running the commands in this repository on the
verification host. Nothing here is asserted without a measurement; nothing that
failed or was skipped is reported as passing.

---

## 1. Environment used for verification

| Component | Version |
|---|---|
| OS | Windows (win32) |
| Python (backend venv) | 3.13.3 |
| FastAPI | 0.143.0 |
| SQLAlchemy | 2.0.36 |
| Pydantic | 2.10.4 |
| pytest | 9.0.3 |
| Node.js | v24.19.0 |
| npm | 11.17.0 |

Production images pin Python 3.12 (backend) and Node 20 (frontend build); see the
`Dockerfile`s.

---

## 1a. Verification summary

| # | Check | Result |
|---|-------|--------|
| 1 | Full backend test suite | **204 passed, 0 failed** (147.31s, 6 warnings) |
| 2 | Frontend production build | **Succeeded** (2360 modules, 4.24s) |
| 3 | Evaluation dataset | **Reproduced exactly** (see metrics below) |
| 4 | Six-agent workflow | **6/6 agents acted**; investigation completed |
| 5 | Evidence traceability / uncertainty | **Traceable**; explicit uncertainty surfaced |
| 6 | Knowledge Graph | **23 nodes, 40 edges**; all required relations present |
| 7 | Report generation | **28 sections**, Markdown + JSON + PDF all render |
| 8 | Configuration / secret handling | **No committed secrets**; redaction active |
| 9 | DB persistence / backup | SQLite on a persistent volume; backup/restore scripts present |
| 10 | Prod frontend/backend config | Coherent (token injected server-side, single worker) |
| 11 | App starts via documented commands | **Backend 200** (health/live/root/documents); **frontend 200** |
| 12 | README / installation guide | Reviewed — accurate (minor notes below) |

The 6 warnings in the backend run are third-party deprecation notices
(`httpx`/`TestClient` and PyMuPDF `swigvarlink`), not test failures.

---

## 2. Backend test suite (actual)

```
cd neurosync/backend
.\venv\Scripts\python.exe -m pytest app/tests -q
```

Result: **204 passed, 6 warnings in 147.31s**. No tests were skipped, xfailed or
failed. The suite covers extraction, conflict detection, all six agents, the
scheduler, the blackboard, hypothesis ranking, the audit trail, human review, the
optional LLM layer (mocked provider), the demonstration scenario, the HTTP API,
the security controls, the reporting layer, the progress stream, the Knowledge
Graph and the evaluation harness.

Security/authorization specifically: `app/tests/test_security.py` → **21 passed**,
including an exhaustive check that every `/api/*` route (except health) returns
401 without the token.

---

## 3. Evaluation dataset (actual metrics)

```
cd neurosync/backend
.\venv\Scripts\python.exe -m evaluation.run_evaluation
```

Deterministic mode, LLM disabled, isolated temporary database.

**Conflict detection** (positive class = confirmed contradiction; 32 examples):

| Metric | Value |
|--------|-------|
| Precision | **0.9091** |
| Recall | **0.8333** |
| F1 | **0.8696** |
| False-positive rate | 0.0500 |
| False-negative rate | 0.1667 |
| Accuracy | 0.9062 |
| Confusion | TP=10, FP=1, FN=2, TN=19 |
| Flag accuracy / type accuracy | 0.9062 / 0.9062 |

**Evidence sufficiency** (6 scenarios): **status accuracy 1.0000 (6/6)**,
evidence-partition traceability **1.0000**.

**Conclusion traceability** (demo investigation): **7/7 fully traceable
(rate 1.0000)**; all conclusions linked to a conflict and to source claims.

**Known failure cases (3, retained deliberately)** — all in
`lexical_variation_and_negation`:

- `lex_subject_synonym_temp` — false negative (`temp` vs `temperature`).
- `lex_state_synonym_running` — false negative (`not running` vs `operating normally`).
- `lex_negation_scope_false_positive` — false positive (`...with no anomalies`).

These are genuine, reproducible limitations of the rule-based detector and are
documented in `backend/evaluation/README.md`. Dataset SHA-256 hashes are recorded
in `evaluation/results/summary.json` for reproducibility.

---

## 4. Frontend production build (actual)

```
cd neurosync/frontend
npm run build
```

Result: **success** — `tsc -b && vite build`, 2360 modules, built in 4.24s.
Emitted to `frontend/dist/`:

| Artifact | Size | gzip |
----------|------|------|
| `index.html` | 0.75 kB | 0.38 kB |
| `assets/index-*.css` | 50.81 kB | 9.20 kB |
| `assets/vendor-*.js` | 52.34 kB | 18.45 kB |
| `assets/reactflow-*.js` | 173.60 kB | 55.43 kB |
| `assets/index-*.js` | 361.76 kB | 100.34 kB |
| `assets/charts-*.js` | 389.30 kB | 108.03 kB |

---

## 4a. Feature verification (isolated demo, end-to-end)

Run in a throwaway database; no user data touched.

- **Six-agent workflow:** all six agents acted (Evidence Collector 1,
  Conflict Detector 2, Hypothesis Generator 1, Investigator 1, Verification
  Agent 1, Decision   Agent 1 action). Investigation reached `completed` with
  `stop_reason = no_useful_actions_remaining` after 7 iterations.
- **Evidence traceability:** the demo conclusion
  (`human_review_required`, confidence 0.129) cites 1 supporting evidence item
  and every cited id resolves to a **real** stored evidence row. Uncertainty is
  explicit: 8 unresolved questions and 2 limitations recorded on the conclusion.
- **Knowledge Graph:** 23 nodes / 40 edges, `truncated=False`; node types
  document=3, claim=3, conflict=1, evidence=4, hypothesis=4, conclusion=1,
  investigation=1, agent=6. All required relation types present
  (`challenges, contains, contradicts, created, derived_from, investigated_in,
  supported_by, supports`).
- **Report generation:** 28 sections, `schema_version=2`, Markdown ~14,095
  characters; PDF rendered (~52,980 bytes, valid `%PDF` header). JSON export
  carries 23 typed keys.

---

## 5. Deployment readiness assessment

**Status: READY for a single-host single-user deployment.**

Passing:

- Full automated suite green; evaluation metrics reproduce deterministically.
- Production artifacts build cleanly.
- App boots via the documented command and serves health, root and API.
- Secrets are env-driven, never committed; logs redact the API token and LLM key.
- Production stack is defined and coherent: no public backend port, token
  injected server-side by nginx, Caddy TLS, `APP_WORKERS=1`, persistent volume,
  backup/restore scripts.

Caveats (see [`known_issues.md`](known_issues.md) for detail):

- **Single host, single worker.** The investigation runtime and live event bus are
  in-process; do not scale horizontally on SQLite without externalising them.
- **No user accounts.** Single-tenant by design; restrict access at the edge
  (Caddy basic-auth / IP allow-list) plus the API token.
- **Not verified in this environment:** Docker images were not built or run here
  (Docker is not installed), and the production Caddy/nginx path was not
  exercised end-to-end. The compose/Dockerfile/nginx configs were reviewed but
  not executed.
- **Small synthetic evaluation dataset** — metrics are contract checks, not a
  general accuracy claim.
- **Syntax/type-check only.** No JS unit-test runner is configured for the
  frontend; correctness is covered by `tsc`/`vite build`.

**Deployment readiness: CONDITIONAL GO** — safe to deploy as a single-tenant,
access-restricted instance after running the release checklist on the target host.

---

## 5a. Exact local startup instructions

Prerequisites: Python 3.11+ and Node.js 18+ (verified with Python 3.13, Node 24).

**Backend (terminal 1):**

```powershell
cd neurosync/backend
python -m venv venv
.\venv\Scripts\Activate.ps1          # Windows PowerShell
# source venv/bin/activate            # macOS / Linux
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

API at `http://127.0.0.1:8000` (docs at `/docs`). No `.env` is required;
optional settings come from `backend/.env` (copy `backend/.env.example`).

**Frontend (terminal 2):**

```powershell
cd neurosync/frontend
npm install
npm run dev
```

Open `http://localhost:5173` (the dev server proxies `/api` to the backend).

**Optional checks:**

```powershell
cd neurosync/backend
.\venv\Scripts\python.exe -m pytest app/tests -q          # 204 passed
.\venv\Scripts\python.exe -m evaluation.run_evaluation     # writes evaluation/results/
```

---

## 5b. Exact deployment steps (do not run automatically)

Target: one Linux VM, Docker Engine + Compose v2, a DNS A/AAAA record pointing at
the host, ports 80/443 open. Full detail in [`deployment.md`](deployment.md).

1. Install Docker Engine and the Compose v2 plugin on the host.
2. Point your DNS record at the host **before** first start (ACME challenge).
3. In the repo root on the host:
   ```bash
   cp .env.prod.example .env
   ```
4. Edit `.env` and replace every `<CHANGE_ME>`:
   `SITE_ADDRESS`, `ACME_EMAIL`, `CORS_ORIGINS`, `TRUSTED_HOSTS`, and a strong
   `API_TOKEN`:
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(48))"
   ```
   Never commit this file (`.gitignore` excludes `.env`).
5. Build and start:
   ```bash
   docker compose -f docker-compose.prod.yml up -d --build
   docker compose -f docker-compose.prod.yml ps
   ```
5. Firewall: allow `22`, `80`, `443` only. The backend publishes **no** host port.
6. Verify (from `deployment.md` §verification):
   ```bash
   curl -s -o /dev/null -w '%{http_code}\n' https://<host>/api/documents   # expect 401
   ```
   Then load the app in a browser and run the demo investigation.
5. Configure backups (cron) using `scripts/backup.sh`, and test a restore on a
   throwaway host at least once:
   ```cron
   15 3 * * * cd /srv/neurosync && ./scripts/backup.sh /var/backups/neurosync >>/var/log/neurosync-backup.log 2>&1
   ```

---

## 5c. Configuration and secret handling (verified)

- Secrets come only from the environment: `API_TOKEN`, `OPENAI_API_KEY`
  (`backend/app/config.py`). `.gitignore` excludes `.env`, `.env.local`,
  `.env.prod`, `*.db`, `*.sqlite`, and `backend/uploads/*`.
- Only `*.example` templates are tracked (backend `.env.example` /
  `.env.production.example`, root `.env.prod.example`, frontend `.env.example`).
- The logging filter (`backend/app/logging_config.py`) redacts every configured
  secret value; `test_security.py::test_api_never_returns_the_provider_key` proves
  the API never returns the provider key.
- Repository scan found **no hardcoded secrets** in `backend/app`.

---

## 6. Release artifacts / versioning

- Version **1.0.0** is declared in `backend/app/__init__.py`,
  `backend/app/config.py` (`app_version`) and `frontend/package.json`.
- Release notes: this file. Changelog: [`CHANGELOG.md`](../CHANGELOG.md).
- Checklist: [`release_checklist.md`](release_checklist.md). Known issues:
  [`known_issues.md`](known_issues.md).

This document records verification only. **No deployment, publishing or data
deletion was performed.**
