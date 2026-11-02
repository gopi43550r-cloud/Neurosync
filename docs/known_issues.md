# Known Issues and Limitations

Version: **1.0.0** · Last reviewed: 2026-10-11

This document records the limitations known at the 1.0.0 release. Items marked
**by design** are intentional trade-offs for a single-host, single-tenant
evidence tool; items marked **known bug** are reproducible defects with a
measurable impact.

---

## 1. Conflict detection: lexical variation and negation

**Type:** known bug · **Severity:** medium · **Area:** extraction / detection

The deterministic conflict detector compares normalised values and shared
keywords. It can miss contradictions when the same fact is expressed with
different wording, and can over-flag when a negation applies to the wrong scope.

Reproduced failure cases (from the evaluation dataset, 32 examples):

| Case | Failure | Example |
|------|---------|---------|
| `lex_subject_synonym_temp` | false negative | `temp` vs `temperature` treated as different subjects |
| `lex_state_synonym_running` | false negative | `not running` vs `operating normally` not matched |
| `lex_negation_scope_false_positive` | false positive | `...with no anomalies` read as an anomalous value |

**Impact:** precision 0.9091 / recall 0.8333 on the curated dataset; recall is the
weaker side. Measured in `backend/evaluation/README.md`.

**Mitigation:** the optional LLM layer improves recall when enabled; every LLM
suggestion is validated against real evidence. A synonym/ontology layer is the
planned deterministic fix (post-1.0).

---

## 2. Knowledge Graph and summaries are O(total records)

**Type:** by design (scale limit) · **Severity:** medium · **Area:** Knowledge Graph

`/api/graph` builds the full tenant graph in memory by scanning all documents,
claims, conflicts, evidence, hypotheses, conclusions and investigations for the
tenant. The UI graph can be paged/limited, but the server-side build is not
incremental.

**Impact:** memory and latency grow linearly with corpus size. Benchmarked at
~443 ms for the demo corpus (`docs/performance.md`); large tenants will be slower.

**Mitigation:** bounded by the UI's graph controls; for very large tenants, query
a subgraph by investigation. Persistent graph projection is a post-1.0 item.

---

## 3. Single host, single process required

**Type:** by design · **Severity:** high (for scaling) · **Area:** runtime

The investigation scheduler runs in an in-process background worker and the live
progress feature uses an in-process event bus. SQLite allows one writer.

**Impact:** running more than one backend worker/container would duplicate
investigation work and drop SSE events between processes. Do **not** horizontally
scale the backend on SQLite.

**Mitigation:** `APP_WORKERS=1` is enforced in the production compose file; scale
vertically. Moving to a real queue + Postgres is the documented path to
multi-host scaling (post-1.0).

---

## 4. No user accounts (single-tenant)

**Type:** by design · **Severity:** medium · **Area:** security / auth

NeuroSync authenticates with a single shared bearer token and has no user model,
roles or per-tenant isolation for human users. This was an explicit product
decision — see [`multi_user_evaluation.md`](multi_user_evaluation.md).

**Impact:** anyone with the token (or, in local mode, anyone who can reach the
loopback interface) has full access. There is no audit attribution to a real
person beyond free-text reviewer names.

**Mitigation:** restrict access at the edge (Caddy basic-auth and/or IP
allow-list) and always set a strong `API_TOKEN` for anything non-loopback. A
reversible multi-user design is documented but intentionally not implemented.

---

## 5. Optional AI layer is off by default and not live-tested

**Type:** by design · **Severity:** low · **Area:** LLM

The provider-agnostic LLM layer is disabled unless configured. The deterministic
path is the default and the fully tested path.

**Impact:** enabling the LLM changes output quality and requires network access,
a key, and trust in the provider. Live provider calls are **not** part of the
automated suite (the provider is mocked in tests).

**Mitigation:** use the deterministic mode for reproducible/auditable runs; treat
LLM output as suggestions that are citation-validated before display.

---

## 6. No standalone frontend test runner

**Type:** by design (test coverage) · **Severity:** low · **Area:** frontend

There is no JS unit/e2e test framework configured. Frontend correctness is
verified by TypeScript (`tsc -b`) and the production build.

**Impact:** behavioural regressions in React components are not caught by
automation.

**Mitigation:** `npm run lint` (`tsc -b --noEmit`) and `npm run build` run in CI
and before release; add Vitest/Playwright post-1.0.

---

## 7. Schema evolution without a migration framework

**Type:** by design · **Severity:** low · **Area:** persistence

The database is created with `Base.metadata.create_all` plus idempotent additive
migrations (`_run_additive_migrations`). There is no Alembic.

**Impact:** columns/tables are only *added* automatically; destructive schema
changes (renames, type changes, drops) are not handled and would need a manual
migration.

**Mitigation:** take a backup (`scripts/backup.sh`) before upgrading; additive
migrations are safe to re-run.

---

## 8. Evaluation dataset is small and synthetic

**Type:** by design (scope) · **Severity:** low · **Area:** evaluation

The 32-example conflict set and 6 evidence scenarios are curated contract checks,
not a representative accuracy benchmark.

**Impact:** reported precision/recall/F1 should not be read as general accuracy.

**Mitigation:** treat metrics as regression guards; expand the dataset before
making accuracy claims.

---

## 9. Production path not executed in this environment

**Type:** verification gap · **Severity:** low · **Area:** deployment

Docker is not installed on the verification host, so the images were not built or
run and the Caddy/nginx production path was not exercised end-to-end; configs
were reviewed only.

**Impact:** the first deployment on a real host is the first true test of the
compose stack.

**Mitigation:** follow [`release_checklist.md`](release_checklist.md) and §"Exact
deployment steps" in [`release_notes.md`](release_notes.md) on the target host.

---

## Reporting a new issue

Include: version (`/api/health` reports `app_version`), the reproduction steps, the
observed vs expected result, and any relevant log lines (secrets are redacted
automatically).
