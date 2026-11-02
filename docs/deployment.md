# Deploying NeuroSync

This guide covers putting NeuroSync on a public host. The recommended shape is
**Docker Compose on a single Linux VM (VPS)** with **Caddy** terminating TLS.

> Nothing here is applied automatically. Follow the steps, fill in the
> `<CHANGE_ME>` values, and run the verification checklist at the end.

## Architecture

```
Internet
   │  80/443
   ▼
Caddy  ──TLS, security headers──▶  frontend (nginx)
                                      │  serves the SPA
                                      │  proxies /api/* (adds the API bearer token)
                                      ▼
                                   backend (FastAPI, uvicorn --workers 1)
                                      │  /app/data/neurosync.db  (SQLite)
                                      │  /app/data/uploads/      (documents)
                                      ▼
                                   internal Docker network  (backend has NO public port)
```

- A single public entry point (Caddy). The backend is reachable **only** from
  the frontend container, so the API is never exposed directly.
- The browser talks to `/api` on the same origin, so **no CORS** is involved in
  the default setup.
- The API bearer token is injected by nginx **server-side**; it never lands in
  the browser bundle or network tab.

## Prerequisites

- A Linux host with a public IP and ports **80** and **443** reachable.
- Docker Engine + the Compose v2 plugin (`docker compose version` ≥ 2.x).
- A DNS **A/AAAA record** for your domain pointing at the host (needed for
  automatic HTTPS).
- ~1 GB RAM and a few GB of disk (SQLite + uploads are small).

## 1. Configuration values you must supply

Everything is read from environment variables. For the Compose deployment, copy
the template and edit it:

```bash
cp .env.prod.example .env
```

| Variable | Required | Secret | What to set |
|---|---|---|---|
| `SITE_ADDRESS` | yes | no | Public hostname Caddy serves, e.g. `neurosync.example.com`. Use `localhost` only for a local trial (self-signed CA). |
| `ACME_EMAIL` | recommended | no | Contact e-mail for Let's Encrypt expiry notices. |
| `CORS_ORIGINS` | yes | no | Public origin(s) of the app, e.g. `https://neurosync.example.com`. Comma-separated, no wildcard. |
| `TRUSTED_HOSTS` | yes | no | Hostnames the backend answers to, e.g. `neurosync.example.com`. Blocks Host-header attacks. |
| `API_TOKEN` | yes | **yes** | Long random string guarding every `/api` route. Generate: `python -c "import secrets; print(secrets.token_urlsafe(48))"`. |
| `VITE_API_URL` | no | no | Leave empty for same-origin `/api` (recommended). Set only if the API is on a different origin, e.g. `https://api.example.com/api`. |
| `MAX_UPLOAD_MB` | no | no | Max upload size in MB (default 25). Must be ≤ the nginx `client_max_body_size` (30m). |
| `MAX_EXTRACTED_CHARS` | no | no | Zip-bomb guard on extracted text (default 5,000,000). |
| `LOG_LEVEL` / `LOG_FORMAT` | no | no | `INFO` / `json` are good production defaults. |
| `ENABLE_LLM` | no | no | `false` = deterministic demonstration mode (no key needed). |
| `OPENAI_API_KEY` | only if `ENABLE_LLM=true` | **yes** | OpenAI-compatible API key. |
| `OPENAI_MODEL` / `OPENAI_BASE_URL` | no | no | Model and endpoint for the optional LLM layer. |

Backend-only variables (set directly via `backend/.env` or the platform's env
UI) are documented in [`backend/.env.production.example`](../backend/.env.production.example).

**Never commit a filled-in `.env`.** `.gitignore` excludes `.env` and
`.env.prod`; the `*.example` files are safe to commit.

## 2. Verify locally before deploying

Run the test suite and build the frontend:

```powershell
cd neurosync/backend
.\venv\Scripts\python.exe -m pytest app/tests -q     # expect all green

cd ../frontend
npm ci
npm run build                                         # must succeed
```

Optionally smoke-test the production stack locally (Caddy will use a local CA):

```bash
# in neurosync/
cp .env.prod.example .env
# set SITE_ADDRESS=localhost, and put any non-empty value in API_TOKEN
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml ps          # all services healthy
```

## 3. Deploy (Docker Compose on a VPS)

```bash
# on the server, in the repo root
cp .env.prod.example .env
$EDITOR .env                       # fill in SITE_ADDRESS, ACME_EMAIL, CORS_ORIGINS,
                                   # TRUSTED_HOSTS, API_TOKEN, etc.

docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs -f caddy
```

Caddy obtains a certificate on first request. Point your DNS record at the host
**before** starting so the challenge can succeed.

Firewall: allow only `22` (SSH), `80`, `443`. Do **not** expose `8000` — the
backend compose service publishes no host port.

## 4. HTTPS and restricting access

- **HTTPS** is automatic: Caddy issues and renews Let's Encrypt certificates for
  `SITE_ADDRESS`. Nothing to configure beyond DNS + port 443.
- **Restrict who can use the app** — edit [`Caddyfile`](../Caddyfile) and
  uncomment one of:
  - **Basic auth** (generate a hash:
    `docker run --rm caddy:2.8-alpine caddy hash-password --plaintext 'YOUR_PASSWORD'`).
  - **IP allowlist** (the commented `@allowed remote_ip` block).
  Then `docker compose -f docker-compose.prod.yml restart caddy`.

Additional layers already in place:

- API bearer token (`API_TOKEN`) — required on every `/api` route.
- `TrustedHostMiddleware` allowlist (`TRUSTED_HOSTS`).
- Security headers (`X-Content-Type-Options`, `X-Frame-Options`,
  `Referrer-Policy`) set by both Caddy and the API.
- Interactive API docs disabled (`ENABLE_DOCS=false`).

> NeuroSync is a **single-user demonstration** and has no user accounts. See
> [`multi_user_evaluation.md`](multi_user_evaluation.md) for why multi-user
> support is intentionally not implemented, and which controls secure a shared
> host (the token gate plus edge basic-auth / IP allowlist).

## 5. Database initialisation and migrations

- The database is **SQLite**, created automatically on first start
  (`Base.metadata.create_all` in `backend/app/database.py`). No separate step.
- **New tables** are added automatically on upgrade. **Column changes are not**:
  SQLAlchemy's `create_all` never alters existing tables, and there is no Alembic
  setup. If a future release changes a column, either provide a migration or
  re-create the database from a backup/export.
- SQLite runs with **WAL** mode and a **5 s busy timeout** so the background
  investigation thread and API readers don't collide.
- For a larger, multi-writer deployment, switch `DATABASE_URL` to PostgreSQL
  (SQLAlchemy is already the abstraction); SQLite is ideal for a single Host here.

## 6. Persistent storage

All runtime state lives on the `neurosync-prod-data` named volume, mounted at
`/app/data`:

```
/app/data/neurosync.db          # database
/app/data/uploads/              # uploaded documents
```

It survives container restarts and `up --build`. The container runs as a
non-root user that owns `/app/data`, so no host permission tweaks are needed for
named volumes. To back up or inspect from the host:

```bash
docker compose -f docker-compose.prod.yml exec backend ls -la /app/data
```

## 7. Backups and restore

```bash
./scripts/backup.sh                 # -> backups/<UTC-timestamp>/{neurosync.db,uploads.tar}
./scripts/restore.sh backups/<ts>   # asks for confirmation, then restores
```

`backup.sh` uses the SQLite online-backup API for a consistent snapshot, then
tars the uploads. Schedule it from cron (make the scripts executable first):

```cron
# mktemp-free daily backup at 03:15 UTC
15 3 * * * cd /srv/neurosync && ./scripts/backup.sh /var/backups/neurosync >>/var/log/neurosync-backup.log 2>&1
```

Copy `backups/` off the host periodically. **Test a restore** at least once on a
throwaway host before you rely on it.

## 8. Logging and monitoring

- Backend logs are structured JSON (`LOG_FORMAT=json`). Secrets (`API_TOKEN`,
  `OPENAI_API_KEY`) are scrubbed by a redaction filter in
  `backend/app/logging_config.py`.
- Read them with `docker compose -f docker-compose.prod.yml logs -f backend`.
- Health checks:
  - `GET /api/health/live` — liveness (process up), used by the container
    `HEALTHCHECK`. No database access.
  - `GET /api/health` — readiness (checks the database).
  - Both are exempt from the API token so external monitors can probe them.
- Ship container logs to your aggregator of choice (e.g. Loki, CloudWatch) by
  adding a logging driver, or leave Caddy's JSON access log as the front door.

## 9. Single-worker limitation (important)

Investigations run in an **in-process background thread**, and the
"running investigation" registry (pause/resume/cancel) plus the live event bus
are **in-memory**. Therefore:

- Keep `APP_WORKERS=1`. Running multiple workers would split that state (e.g.
  pause a run on one worker, status reads hit another).
- The SSE endpoint itself is backed by the database (it polls the DB), so event
  streams survive restarts — but **only one backend instance** should run for a
  given database. Do not scale the backend horizontally against the same SQLite
  file; move to PostgreSQL and external state before doing so.

## 10. Updating and rollback

```bash
git pull
docker compose -f docker-compose.prod.yml up -d --build   # rebuild + rolling restart
```

- Back up first: `./scripts/backup.sh`.
- Roll back by checking out the previous revision and rebuilding, or restore the
  database from a backup if a schema change was involved.

## 11. Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| Caddy can't get a certificate | DNS not pointing at the host, or 80/443 blocked. |
| `502` from Caddy | Frontend/backend container unhealthy — check `docker compose ... ps` and `logs frontend backend`. |
| All `/api` calls return `401` | `API_TOKEN` mismatch between backend and the token nginx injects (both come from the same `.env`, so rebuild/restart after editing). |
| Uploads fail with `413` | File exceeds nginx `client_max_body_size` (30m) or `MAX_UPLOAD_MB`. |
| `database is locked` | Another process/worker writing the same SQLite file; ensure a single backend worker. |
| Host-header errors | `TRUSTED_HOSTS` doesn't include the public domain. |

## 12. Verification checklist (after deploying)

- [ ] `docker compose -f docker-compose.prod.yml ps` shows **all services healthy**.
- [ ] `https://<SITE_ADDRESS>/` loads the app with a valid certificate (padlock).
- [ ] `curl -s https://<SITE_ADDRESS>/api/health/live` returns `200`.
- [ ] `curl -s https://<SITE_ADDRESS>/api/health` reports the database is OK.
- [ ] `curl -s -o /dev/null -w '%{http_code}' https://<SITE_ADDRESS>/api/documents` is `401` (token enforced).
- [ ] Uploading a document in the UI succeeds and the file appears under
      `/app/data/uploads` (`docker compose ... exec backend ls /app/data/uploads`).
- [ ] An investigation runs and its event stream updates in the UI (SSE works
      through the proxy).
- [ ] `./scripts/backup.sh` produces a non-empty `neurosync.db` and `uploads.tar`,
      and a restore on a test host brings the data back.
- [ ] `http://<host>` redirects to `https://` and the backend port `8000` is **not**
      reachable from the internet.
- [ ] Restarting the host (`docker compose ... down && up -d`) preserves data.

## Alternative: no-Docker deployment

If you can't run Docker, run the backend under systemd (`uvicorn app.main:app
--host 127.0.0.1 --port 8000 --workers 1`) and the built frontend under nginx,
with `UPLOAD_DIR` and `DATABASE_URL` pointing at persistent paths, and nginx
proxying `/api` with `client_max_body_size 30m`, `proxy_buffering off` and
`proxy_read_timeout 3600s` (the settings in
[`frontend/nginx.conf.template`](../frontend/nginx.conf.template)). Terminate TLS
with certbot. The environment variables, health checks, backup approach and the
single-worker rule are all identical.
