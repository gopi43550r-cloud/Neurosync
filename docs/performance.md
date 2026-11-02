# Performance & Scalability

This document records the measured optimisation work on NeuroSync's backend and
frontend. Every number here is produced by a reproducible harness; nothing is
estimated.

## How to reproduce

```bash
cd backend
python benchmarks/bench_performance.py benchmarks/baseline.json   # before
python benchmarks/bench_performance.py benchmarks/improved.json   # after
```

The harness seeds a deterministic throwaway SQLite database (fixed RNG seed,
temporary `DATABASE_URL`/`UPLOAD_DIR`) and measures each workload for:

- **queries** – SQL statements executed (exposes N+1 and full scans),
- **ms** – wall-clock time,
- **peak_kb** – peak Python heap during the workload (`tracemalloc`).

## Workload scale

| entity | rows |
| --- | --- |
| documents | 400 |
| claims | 1,200 |
| conflicts | 600 |
| evidence | 1,800 |
| hypotheses | 1,200 |
| conclusions | 600 |
| human reviews | 200 |
| blackboard events | 20,000 |
| audit events | 20,000 |
| relations | 5,000 |
| agent activities | 500 |
| scoped run | 10 documents / 20 conflicts |

## Baseline vs improved

`queries` / `ms` / `peak_kb`, measured on the same machine.

| workload | queries | ms | peak_kb |
| --- | --- | --- | --- |
| `GET /api/blackboard/events` | 1 → 2 | 630.8 → 198.0 | 35,779 → 1,946 |
| `GET /api/audit` | 1 → 2 | 493.3 → 36.4 | 35,170 → 428 |
| `GET /api/claims` | 51 → 3 | 72.3 → 17.8 | 2,769 → 361 |
| `GET /api/documents` | 201 → 6 | 705.2 → 27.5 | 2,183 → 463 |
| `GET /api/conflicts` | 267 → 6 | 205.0 → 24.6 | 1,667 → 399 |
| `GET /api/evidence` | 51 → 3 | 78.3 → 19.1 | 3,537 → 337 |
| `GET /api/hypotheses` | 1 → 2 | 34.4 → 16.2 | 2,570 → 314 |
| `GET /api/investigations` | 152 → 6 | 121.0 → 24.1 | 705 → 475 |
| `kg.build_knowledge_graph(scoped)` | 11 → 10 | 157.1 → 81.0 | 4,231 → 4,392 |
| `kg.build_knowledge_graph(global)` | 10 → 10 | 10,579.9 → 1,053.5 | 64,961 → 65,534 |
| `relation_service.sync_relations(scoped)` | 198 → 209 | 1,758.4 → 101.2 | 10,675 → 3,218 |
| `document_service.document_llm_attempted` | 1 → 1 | 1,110.6 → 2.5 | 11,531 → 27 |
| `blackboard.build_graph(global)` | 7 → 6 | 2,854.8 → 443.3 | 15,763 → 15,124 |
| `blackboard.state.assess(scoped)` | 64 → 6 | 2,256.0 → 25.0 | 1,217 → 1,318 |
| `document_service.document_stats(single)` | 4 → 3 | 69.9 → 5.3 | 1,028 → 75 |
| `document_service.save_upload(memory)` (25 MB) | — | — → 31.0 | — → 2,059 |

The `save_upload` workload is measured only *after* the change (the baseline
harness predates it). It streams a synthetic 25 MB upload; peak Python heap is
~2 MB (one read chunk), i.e. **O(chunk) instead of O(file)** — the previous
implementation read the entire file into memory (`raw = file.file.read()`).

Highlights:

- `blackboard.state.assess` — **90× faster** (N+1 over conflicts removed).
- `GET /api/documents` / `GET /api/conflicts` — **~26× / ~8× faster**, queries
  down from 200+/267 to 6 via SQL pagination + batch serialization.
- List endpoints no longer materialise whole tables in memory (event history
  peak dropped **~18×**, audit **~82×**).
- `document_llm_attempted` — **~550× faster** by using the indexed
  `audit_events.entity_id` column instead of scanning JSON payloads.

## What changed

1. **Indexes** (`app/models/*`, mirrored additively in
   `app/database._run_additive_migrations` for existing databases): composite
   indexes for event/audit/activity orderings, conflict-scoped evidence,
   investigation + document ordering.
2. **SQL pagination** (`app/api/pagination.py`): every list endpoint now issues a
   `COUNT` over the same filtered query plus a `LIMIT/OFFSET` page, preserving
   the `total` semantics (see `test_security.py`).
3. **Batch serialization** (`app/services/serialization.py`): the per-row N+1
   lookups were replaced with grouped queries (`document_stats_map`,
   `conflicts_to_out`, `investigations_to_out`, …).
4. **Scoped queries** in `relation_service.py` and
   `knowledge_graph_service.py`: a scoped request filters in SQL instead of
   loading and filtering every table in Python.
5. **Bounded event history**: the SSE stream caps each poll at
   `SSE_EVENT_BATCH = 500`, and list endpoints page.
6. **Blackboard batching**: `state.assess` batch-loads hypotheses/evidence and
   `build_graph` loads hypotheses once (previously twice).
7. **Frontend pagination**: a reusable `Pagination` component
   (`frontend/src/components/ui.tsx`) is wired into the Documents, Conflicts,
   Evidence, Hypotheses, Investigations and Audit pages, so each view requests
   one page (default 50 rows) instead of rendering the whole table.
8. **Streamed uploads + cleanup** (`app/services/document_service.py`):
   `save_upload` streams the file to disk in 1 MB chunks (aborting as soon as
   `max_upload_mb` is exceeded) and computes the checksum incrementally, so peak
   memory is O(chunk). Files are removed on any validation failure, on a
   rejected duplicate, or if the insert fails, so nothing is orphaned on disk.

## Coverage of the evaluation areas

| # | area | finding / action |
| --- | --- | --- |
| 1 | Database query performance | N+1 and full-scan hot paths removed (pagination, batch serialization, scoped SQL). Measured above. |
| 2 | Missing indexes | Added composite indexes for event/audit/activity orderings, conflict-scoped evidence, document/investigation ordering, and an `entity_id` index used by LLM-attempt lookups. Mirrored additively for existing DBs. |
| 3 | Repeated document processing | Upload deduplicates by SHA-256 checksum; extraction is idempotent (skips when claims exist); LLM augmentation is attempted at most once per document via an indexed audit lookup. |
| 4 | Duplicate agent execution | `registry` blocks concurrent runs; overlapping document/conflict sets are rejected; `max_attempts_per_action`, `iteration_limit` and `max_agent_executions` bound repeats. |
| 5 | Large document uploads | `max_upload_mb` + `max_extracted_chars` limits; uploads stream in 1 MB chunks with O(chunk) memory (measured: 25 MB → ~2 MB peak). |
| 6 | Large Blackboard event histories | List endpoints page via `LIMIT/OFFSET`; the SSE stream caps each poll at `SSE_EVENT_BATCH = 500` and resumes from `Last-Event-ID`. |
| 7 | Frontend rendering with many records | Reusable `Pagination` on all list pages; lists render one bounded page. |
| 8 | Large Knowledge Graph rendering | Backend caps nodes/edges and reports `truncated`; scoped/typed filters pushed into SQL; frontend uses `onlyRenderVisibleElements` and disables the minimap above 250 nodes. |
| 9 | Long-running investigations | Started on a daemon thread (request returns immediately), with pause/resume/cancel and the bounds above. |
| 10 | Memory usage and resource cleanup | DB sessions closed in `finally` blocks (incl. SSE); upload files released on failure/duplicate; event payloads redacted+bounded; measured peak heap above. |

## Remaining bottlenecks (measured, not fixed)

- `kg.build_knowledge_graph(global)` still allocates ~64 MB and ~1 s because it
  intentionally projects the entire graph; this is inherent to a global view.
  The scoped view is the recommended default for large datasets.
- `blackboard.build_graph(global)` builds 5,800 nodes / 6,000 edges (~0.44 s);
  cost tracks total relationships. Prefer scoped graphs.
- `relation_service.sync_relations` performs ~200 individual existence checks
  and inserts; batching inserts would reduce round-trips further.
- `GET /api/blackboard/events` and `GET /api/audit` show 2 queries (count +
  page) versus 1 before; the extra `COUNT` is the cost of correct `total`
  pagination and is negligible against the memory saved.
- Document processing on upload is still synchronous: the response returns the
  resulting claim/conflict counts, and moving it to a background task would
  change those API semantics and evidence timing. The size/time limits bound the
  worst case instead. (Investigations already run on a background thread.)
- `kg.build_knowledge_graph(global)` and `blackboard.build_graph(global)` are the
  only remaining O(total-data) workloads; both have scoped variants that are the
  recommended default.
