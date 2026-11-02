# Multi-user support: evaluation and decision

**Status:** Not implemented — evaluated as inappropriate for the current product.
**Decision:** Keep NeuroSync a **single-tenant, single-user demonstration / reference
implementation**. Do **not** add user accounts, sessions, ownership or sharing.
**Preserved:** The existing local demonstration mode (no credentials required on
loopback) is unchanged.

This document records the architecture review, the decision, the rationale, the
controls that already protect the (optional) shared-secret deployment, and the
configuration and migration path that would be needed *if* the product is ever
repositioned as a multi-user service.

---

## 1. Scope of the review

Inspected:

- Authentication and authorization: `backend/app/main.py`, `backend/app/config.py`.
- Database and ownership model: `backend/app/database.py`, `backend/app/models/*`.
- Deployment topology: `docs/deployment.md`, `Caddyfile`,
  `frontend/nginx.conf.template`, `docker-compose.prod.yml`.
- Existing security regression coverage: `backend/app/tests/test_security.py`.
- Product intent: `README.md`.

---

## 2. Current architecture

### Authentication

- **One optional shared secret**, `API_TOKEN` (`app/config.py:33-37`). Empty by
  default, which disables authentication for local, loopback-only use — this is
  the **local demonstration mode**.
- A single ASGI middleware enforces it (`app/main.py:107-130`): every `/api/*`
  route requires `Authorization: Bearer <token>` or `X-API-Token: <token>`.
  Comparison is constant-time (`hmac.compare_digest`).
- Exemptions: CORS `OPTIONS` preflight and `/api/health*` probes. The SSE stream
  (`/api/investigations/{id}/events`) additionally accepts `?token=` because the
  browser `EventSource` API cannot send headers — a documented trade-off.
- There are **no user accounts, no passwords, no login/logout, and no sessions**
  anywhere in the codebase.

### Authorization / ownership

- No `User` table and **no `user_id` / `owner_id` columns** on `documents`,
  `investigations` or any other model (`app/models/`).
- Application settings live in a **single global key/value table** shared by the
  whole instance (`app/models/setting.py`); there is no per-user settings scope.
- Authorization is therefore purely **binary**: authenticated (shared secret) or
  not. Within an authenticated instance, every caller sees the same data.

### Database

- SQLite via SQLAlchemy 2.0, `create_all` + idempotent additive migrations
  (`app/database.py`). WAL journal, foreign keys on, 5 s busy timeout.
- One database file per deployment; no tenant scoping.

### Deployment

- Single Linux host, single backend container, **`APP_WORKERS=1`** (the running-
  investigation registry and live event bus are in-process) against one SQLite
  file (`docs/deployment.md:195-206`).
- The API is not exposed directly: the browser talks to same-origin `/api`, and
  **nginx injects the bearer token server-side** so it never reaches the browser
  (`docs/deployment.md:26-31`).
- Access restriction is done at the edge (Caddy basic-auth or IP allowlist),
  not in the application.

### Product intent

`README.md:319`: *"Provided as a reference implementation for demonstration and
evaluation."* There is no collaboration story in the README, user guide,
architecture, or API docs.

---

## 3. Evaluation against the requested capabilities

| # | Capability | Verdict | Notes |
|---|------------|---------|-------|
| 1 | Secure authentication | Not applicable | No accounts exist or are implied. Optional shared-secret gate already protects non-loopback deployments. |
| 2 | Session management | Not applicable | There are no sessions; the shared secret is per-deployment, not per-user. |
| 3 | User ownership of investigations/documents | Not applicable | Single-tenant data model; adding ownership columns would imply a user concept the product does not have. |
| 4 | Authorization on backend endpoints | Already satisfied structurally | The token gate covers **all** `/api/*` routes, verified exhaustively by a test (see §6). No per-user authorization is meaningful without users. |
| 5 | Isolation between users' private data | Not applicable | The isolation boundary is the deployment instance (one database + token per tenant), enforced by the edge, not in-app. |
| 6 | Explicit sharing | Not applicable | Requires users; no sharing concept exists. |
| 7 | Roles (owner/collaborator/viewer) | Not applicable | Requires users. |
| 8 | Audit for collaborative actions | Not applicable | The audit trail already attributes every blackboard/review action to an actor and timestamp (`docs/ARCHITECTURE.md`); a *collaborative* audit implies users. |
| 9 | Secure logout and session expiration | Not applicable | No session to expire. The shared secret is rotated by changing `API_TOKEN` and restarting. |
| 10 | Tests for unauthorized access and isolation | Partially delivered | Unauthorized-access coverage added/strengthened (§6). Data-isolation tests are not meaningful for a single-tenant app; the isolation control is the per-deployment database + token gate. |

---

## 4. Decision and rationale

**Do not add multi-user authentication.** Reasons:

1. **Product intent is single-user.** NeuroSync is documented as a demonstration /
   evaluation reference implementation with no account, collaboration, or sharing
   concept. The brief's own guardrail applies: *do not add authentication
   unnecessarily if the application is intended to remain a local single-user
   demonstration.* That condition holds.

2. **Cost and risk are disproportionate.** Items 1–10 imply a new `User` model,
   password hashing and policy, a session store with expiry/rotation, ownership
   columns and migrations across every aggregate, a share model, RBAC, and a
   login/account/sharing frontend — a large amount of new attack surface and
   ongoing maintenance for a demo.

3. **It would break the current deployment model.** Today the bearer token is
   injected **server-side** and never held by the browser. Per-user browser
   sessions would invert that design (the client must hold credentials), forcing a
   rework of the nginx/Caddy topology that currently keeps the API unexposed.

4. **Single-tenant isolation is already adequate.** For any non-loopback
   deployment, one instance = one tenant = one database, protected by the shared
   secret plus edge auth. Multi-user adds complexity without a demonstrated need.

5. **No cryptographic algorithms are introduced.** Because we are not adding
   accounts, there is no password storage at all — the safest possible position
   with respect to "never store plaintext passwords".

---

## 5. Deployment configuration (current, single-tenant)

These are the settings that make a non-loopback deployment safe. None require
code changes.

### Application (`backend/.env`, see `backend/.env.production.example`)

| Variable | Set to | Purpose |
|----------|--------|---------|
| `API_TOKEN` | a long random value | **Required** off-loopback; gates every `/api/*` route. Generate with `python -c "import secrets; print(secrets.token_urlsafe(48))"`. |
| `ENVIRONMENT` | `production` | Hardened defaults. |
| `ENABLE_DOCS` | `false` | Removes `/docs`, `/redoc`, `/openapi.json` from the surface. |
| `TRUSTED_HOSTS` | your domain | Host-header protection (`TrustedHostMiddleware`). |
| `CORS_ORIGINS` | your origin (or omit for same-origin) | No wildcard with credentials. |
| `UPLOAD_DIR` | persistent path (e.g. `/app/data/uploads`) | Survives restarts. |
| `DATABASE_URL` | persistent path (e.g. `sqlite:////app/data/neurosync.db`) | Survives restarts. |
| `LOG_FORMAT` / `LOG_LEVEL` | `json` / `INFO` | Structured logs; secrets are redacted by `app/logging_config.py`. |
| `MAX_UPLOAD_MB` | ≤ the nginx `client_max_body_size` | Upload bound. |

### Edge (`Caddyfile`, `docker-compose.prod.yml`)

- TLS terminated by Caddy (automatic Let's Encrypt).
- Restrict access to the whole app with **Caddy basic-auth** or an **IP allowlist**
  (`docs/deployment.md:114-123`). This is the tenant boundary for a shared host.
- The backend container publishes **no host port**; only the frontend container
  reaches it, and it injects the bearer token server-side.
- Keep **one backend worker** (`APP_WORKERS=1`) — running investigations and the
  live bus are in-process; a single SQLite file must not be shared across
  instances.

### Verification

The deployment checklist is in `docs/deployment.md:230-245`. One practical check
that the tenant boundary holds:

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://<host>/api/documents   # expect 401
```

---

## 6. Security tests (unauthorized-access coverage)

`backend/app/tests/test_security.py` already covered the token gate on a few
routes. It now additionally asserts the boundary is complete:

- `test_all_health_endpoints_are_exempt_from_token` — both `/api/health` and
  `/api/health/live` remain probeable.
- `test_every_api_route_requires_token_when_configured` — enumerates the live
  OpenAPI schema and asserts **every** `/api/*` route (except health) returns
  `401` without the token, so a newly added endpoint cannot silently bypass the
  gate.
- `test_unknown_api_path_does_not_leak_route_existence` — an unauthenticated
  probe of a non-existent `/api` path returns `401`, not `404`, so the real route
  set cannot be enumerated.
- `test_document_data_is_not_served_without_a_token` — documents list, detail and
  search are all refused without the token and succeed with it.

Run them with:

```powershell
cd neurosync/backend
.\venv\Scripts\python.exe -m pytest app/tests/test_security.py -q   # 21 passed
.\venv\Scripts\python.exe -m pytest app/tests -q                    # 204 passed
```

---

## 7. If multi-user is required later (reversible plan)

If the product is repositioned as a collaborative, multi-user service, the
following is the intended path. It is intentionally **not** implemented now.

1. **Authentication.** Add a `User` model. Use a maintained library — FastAPI's
   `OAuth2PasswordBearer` + `passlib[argon2]` (or `bcrypt`) for hashing. Never
   store or log plaintext passwords. Enforce a password policy.
2. **Sessions.** Short-lived signed tokens (JWT via `python-jose`/`pyjwt`, or
   server-side sessions in a `sessions` table) with expiry and rotation; a
   `/auth/logout` that invalidates the session/refresh token.
3. **Ownership.** Add `owner_id` (FK to `User`) to `documents` and
   `investigations`; migrate via additive, nullable columns, then backfill.
4. **Authorization.** A dependency that resolves the current user and asserts
   owner/collaborator/viewer access on every read and write of owned resources.
5. **Isolation.** All list/search/aggregate queries scoped by the current user's
   visibility (owner ∪ shared). Add tests proving one user cannot read another's
   documents, investigations, claims, evidence, conflicts or reports.
6. **Sharing and roles.** A `shares` table (resource, user, role) and an
   owner-controlled share endpoint; roles `owner` / `collaborator` / `viewer`.
7. **Collaborative audit.** Extend the audit trail with the acting user id for
   share/role/ownership changes and review actions.
8. **Deployment.** Move from SQLite to PostgreSQL for multi-writer, and externalize
   the in-process investigation registry/event bus (Redis or a DB-backed queue)
   before running more than one worker/instance. Update the edge so the browser —
   not nginx — carries the user's session.

Because none of this is built yet, there is no half-finished auth surface to
maintain, and the current deployment remains secure for its single-tenant use.
