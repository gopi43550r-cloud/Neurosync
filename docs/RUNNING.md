# Running & Checking NeuroSync

How to start the app and verify it is actually up and working.

- Backend (FastAPI): `http://127.0.0.1:8000`
- Frontend (Vite/React): `http://127.0.0.1:5173`
- The dev server proxies `/api` from the frontend to the backend.

---

## 1. Start the backend

From the `backend` folder:

```powershell
cd backend
.\venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

Leave this window open. On startup you should see `Application startup complete.`

## 2. Start the frontend

Open a second terminal, from the `frontend` folder:

```powershell
cd frontend
npm run dev -- --host 127.0.0.1
```

Leave this window open. Wait for `Local: http://127.0.0.1:5173/` before opening the browser.

> Use `--host 127.0.0.1`. Plain `localhost` may resolve to IPv6 (`::1`) and fail to connect.

## 3. Open the app

Open a browser at:

```
http://127.0.0.1:5173
```

---

## 4. Check that it is running

### Backend health check

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/health"
```

Expected (success):

```json
{ "status": "ok", "app": "NeuroSync", "version": "1.0.0", "ai_configured": false, "mode": "demonstration", "reasoning_mode": "deterministic", "effective_mode": "deterministic", "llm_model": null }
```

`status: ok` means the backend is up. `version` confirms the build.

### Frontend check

```powershell
Invoke-WebRequest -Uri "http://127.0.0.1:5173" -UseBasicParsing
```

Expected: `StatusCode 200`.

### Interactive API docs

```
http://127.0.0.1:8000/docs
```

Swagger UI listing every endpoint.

### One-line "is everything up?" check

```powershell
try { (Invoke-RestMethod "http://127.0.0.1:8000/api/health").status } catch { "backend DOWN" }
try { (Invoke-WebRequest "http://127.0.0.1:5173" -UseBasicParsing).StatusCode } catch { "frontend DOWN" }
```

Expected: `ok` then `200`.

---

## 5. Key endpoints to sanity-check

| Method | Path | Purpose |
| ------ | ---- | ------- |
| GET  | `/api/health` | Service status/version |
| GET  | `/api/config` | Runtime configuration/mode |
| POST | `/api/demo/seed` | Seed the demonstration dataset |
| POST | `/api/investigations/{id}/run` | Run the agent pipeline |
| GET  | `/api/blackboard/snapshot?days=14` | Dashboard snapshot (distributions, timeline) |
| GET  | `/api/evidence` | Evidence with multi-factor assessment |
| GET  | `/api/conflicts` | Conflict list |
| POST | `/api/conflicts/{id}/review` | Submit a human review decision (returns `201`) |

Full reference: [`API_REFERENCE.md`](API_REFERENCE.md).

---

## 6. Frontend routes to check

| Route | Page |
| ----- | ---- |
| `/` | Dashboard (snapshot, distributions, 7/14/30/90-day window) |
| `/investigations` | Investigations list |
| `/evidence` | Evidence explorer |
| `/conflicts` | Conflicts |
| `/reports` | Generated reports |
| `/graph` | Knowledge graph |

---

## 7. Stop the servers

Click into each server window and press `Ctrl+C`, or close the two PowerShell windows.

Verify they are stopped:

```powershell
Get-NetTCPConnection -LocalPort 8000,5173 -State Listen -ErrorAction SilentlyContinue
```

No rows = both stopped.

---

## 8. Troubleshooting

| Symptom | Cause / fix |
| ------- | ----------- |
| `Unable to connect to the remote server` | Server not started, or the terminal window was closed. Re-run steps 1–2. |
| Frontend loads but API calls fail | Backend not running, or open frontend on `127.0.0.1` not `localhost`. |
| `npm run dev` hangs / no URL | Still compiling; wait for the `Local:` line. |
| Port already in use | Another instance is running. Close it, or use `--port 8001` (backend) and update the proxy. |
| `ai_configured: false` | Normal. Runs in deterministic demonstration mode without an LLM key. |

---

## 9. Automated tests (optional, deeper check)

```powershell
cd backend
.\venv\Scripts\python.exe -m pytest app\tests -q
```

Expected: `216 passed`. See [`TESTING.md`](TESTING.md).
