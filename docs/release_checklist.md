# Release Checklist — NeuroSync 1.0.0

Use this checklist for **every** release. Boxes tagged *(verified 1.0.0)* were
executed and recorded on 2026-10-11; the recorded output is in
[`release_notes.md`](release_notes.md). Re-run every box on the target host before
promotion — do not copy a prior tick.

Commands assume the repo root unless stated.

---

## 0. Pre-flight

- [ ] Confirm version is `1.0.0` in all three places *(verified 1.0.0)*:
  - `backend/app/__init__.py` → `__version__`
  - `backend/app/config.py` → `Settings.app_version`
  - `frontend/package.json` → `version`
- [ ] `CHANGELOG.md` has an entry for this version with today's date *(verified 1.0.0)*.
- [ ] Release notes updated with this version's actual results *(verified 1.0.0)*.
- [ ] Known issues reviewed and current *(verified 1.0.0)*.
- [ ] Working tree contains no secrets: no real `.env`/`*.db`/upload files tracked
      (`git status`, `.gitignore`) *(verified 1.0.0)*.
- [ ] Confirm the deployment target is a **single host** (see known issue §3).

## 1. Backend quality gates

- [ ] `cd backend` then install deps: `pip install -r requirements.txt`.
- [ ] Full suite green:
      `.\venv\Scripts\python.exe -m pytest app/tests -q`
      → expected **204 passed** *(verified 1.0.0: 204 passed, 147.31s)*.
- [ ] Security/authorization subset green:
      `.\venv\Scripts\python.exe -m pytest app/tests/test_security.py -q`
      → expected **21 passed** *(verified 1.0.0)*.
- [ ] No skips/xfails/failures; third-party deprecation warnings are acceptable.
- [ ] Application imports cleanly:
      `.\venv\Scripts\python.exe -m compileall -q app`.

## 2. Evaluation gate

- [ ] `cd backend` then `.\venv\Scripts\python.exe -m evaluation.run_evaluation`.
- [ ] Metrics match the recorded baseline *(verified 1.0.0)*:
  - conflict detection precision **0.9091**, recall **0.8333**, F1 **0.8696**,
    FPR 0.0500, FNR 0.1667, accuracy 0.9062 (32 examples).
  - evidence sufficiency status accuracy **1.0000**, partition traceability **1.0000**.
  - conclusion traceability **7/7 = 1.0000**.
- [ ] Exactly the 3 documented lexical-variation failure cases, no new ones
      *(verified 1.0.0)*.
- [ ] Dataset hashes in `evaluation/results/summary.json` match the previous release.

## 2. Frontend quality gates

- [ ] `cd frontend` then `npm ci` (CI) or `npm install` (local).
- [ ] Type-check: `npm run lint` (`tsc -b --noEmit`) → must be clean.
- [ ] Production build:
      `npm run build` → success *(verified 1.0.0: 2360 modules, 4.24s)*.
- [ ] `frontend/dist/index.html` and `dist/assets/*` emitted *(verified 1.0.0)*.

## 3. Feature smoke test (isolated DB, no user data)

- [ ] Start backend on the documented command:
      `uvicorn app.main:app --reload --port 8000` *(verified 1.0.0: 200)*.
- [ ] `GET /api/health` → 200 with `"version":"1.0.0"` *(verified 1.0.0)*.
- [ ] `GET /api/health/live` → 200 *(verified 1.0.0)*.
- [ ] `GET /` → 200 *(verified 1.0.0)*.
- [ ] Start frontend: `npm run dev`, open `http://localhost:5173` → app loads
      *(verified 1.0.0: 200, root div present)*.
- [ ] Run the demo investigation; confirm all six agents act *(verified 1.0.0: 6/6)*.
- [ ] Confirm the conclusion shows evidence, uncertainty (unresolved questions +
      limitations) and traceable citations *(verified 1.0.0)*.
- [ ] Load the Knowledge Graph: nodes/edges render, no truncation
      *(verified 1.0.0: 23 nodes / 40 edges)*.
- [ ] Generate a report; verify Markdown, JSON and PDF exports
      *(verified 1.0.0: 28 sections, valid PDF)*.
- [ ] Toggle the optional AI layer off/on and confirm the app behaves sanely in
      both modes (deterministic mode is the default).

## 2. Security review

- [ ] Every `/api/*` route except health returns **401** without the token
      *(verified 1.0.0 via test_security.py)*.
- [ ] `/api/health` and `/api/health/live` remain reachable unauthenticated.
- [ ] Provider key never returned by the API and never logged
      *(verified 1.0.0)*.
- [ ] CORS: allowed origin passes, disallowed origin is rejected *(verified 1.0.0)*.
- [ ] No hardcoded secrets in source *(verified 1.0.0)*.
- [ ] Upload limits enforced (size, type, filename, orphan cleanup)
      *(verified 1.0.0 via suite)*.

## 2. Data safety

- [ ] Back up before upgrading: `./scripts/backup.sh` (SQLite + uploads)
      *(scripts present; verified 1.0.0)*.
- [ ] Confirm the restore path on a throwaway copy: `./scripts/restore.sh` prompts
      before overwriting.
- [ ] Never delete `backend/neurosync.db` or uploads during release.

## 3. Build & package

- [ ] Backend image builds: `docker build -t neurosync-backend backend`
      *(not run here — Docker unavailable; review only)*.
- [ ] Frontend image builds: `docker build -t neurosync-frontend frontend`
      *(not run here — Docker unavailable; review only)*.
- [ ] Tag the release commit: `git tag -a v1.0.0 -m "NeuroSync 1.0.0"` then
      push the tag *(repo is not a git repo in this working copy — skip if
      packaging externally)*.

## 4. Deploy (manual, on target host)

- [ ] Docker Engine + Compose v2 installed; DNS points at the host.
- [ ] `cp .env.prod.example .env` and replace every `<CHANGE_ME>`
      (`SITE_ADDRESS`, `ACME_EMAIL`, `CORS_ORIGINS`, `TRUSTED_HOSTS`, strong
      `API_TOKEN`). Never commit `.env`.
- [ ] `docker compose -f docker-compose.prod.yml up -d --build`.
- [ ] `docker compose -f docker-compose.prod.yml ps` → all healthy.
- [ ] Firewall allows `22/80/443` only; backend exposes no host port.
- [ ] `curl -s -o /dev/null -w '%{http_code}\n' https://<host>/api/documents`
      → **401** without a token.
- [ ] Run the demo investigation through the public URL; confirm SSE progress and
      report export.
- [ ] Enable TLS (Caddy auto-HTTPS) and edge access control (basic-auth / IP
      allow-list).

## 5. Post-deploy

- [ ] `scripts/backup.sh` scheduled via cron; verify a fresh backup appears.
- [ ] Monitor logs for redaction (no token/key leakage) and 5xx rate.
- [ ] Record the deployed version (`/api/health` → `version`) and the date.

## 6. Rollback plan

- [ ] Previous image/tag retained and deployable.
- [ ] Latest pre-upgrade backup identified (`backups/<UTC-stamp>/`).
- [ ] Rollback = redeploy previous tag, then restore the DB + uploads from that
      backup if the schema changed. Additive migrations are safe to leave in place.
- [ ] Document the incident and open follow-up issues.

---

## Sign-off

| Role | Name | Date | Result |
|------|------|------|--------|
| Test/verification | | | |
| Security review | | | |
| Release owner | | | |

**Verdict:** ☐ GO  ☐ CONDITIONAL GO  ☐ NO-GO — notes: ______________________
