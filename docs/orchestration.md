# Multi-Agent Orchestration

NeuroSync is a **state-driven, blackboard-mediated** multi-agent system. Six
specialized agents reason over a shared blackboard (documents, claims, conflicts,
hypotheses, evidence, conclusions) while a central controller decides what runs
next based on the current state of that blackboard.

> Agents are specialized Python classes, not autonomous general intelligences.
> Their value is separation of concerns and explicit contracts, not independent
> reasoning. All shared state lives on the blackboard; the controller owns the
> schedule and the stopping decisions.

## The loop

`app/blackboard/controller.py::InvestigationController.run` implements:

1. **Assess** the blackboard (`app/blackboard/state.py::assess`) into a single
   serialisable `BlackboardState`: counts of documents, awaiting extraction,
   claims, conflicts, unresolved conflicts, hypotheses, evidence, unverified /
   missing evidence, and how many conflicts are `ready_for_decision`.
2. **Propose.** Ask every eligible agent for its candidate `Action`s
   (`BaseAgent.candidates`). A candidate is derived from the state, so an agent
   with no useful work returns nothing.
3. **Select.** `Scheduler.select` scores candidates (severity, uncertainty,
   evidence gap, information gain, cost) and picks the single highest-priority
   action. The `BlackboardState` the choice was based on is attached to the
   decision.
4. **Execute.** Run the responsible agent with failure isolation and bounded
   retries.
5. **Record.** Write an execution-ledger row (`AgentActivity`): agent, action,
   status, duration, the **input and output record ids**, the state summary, the
   attempt number, and the sequence position.
6. **Repeat** until a stopping condition is met.

## Declarative agent contracts

`BaseAgent` declares a contract that is both used by the system and exposed to
the UI (`manifest()`, `app/agents/__init__.py::agent_manifests`):

| Field | Meaning |
| --- | --- |
| `responsibility` | What the agent is accountable for. |
| `required_inputs` | Blackboard data it reads before acting. |
| `expected_outputs` | Blackboard records it creates or updates. |
| `run_conditions` | State that makes it eligible to run. |
| `stop_conditions` | State that means it has no further useful work. |

`GET /agents` returns these alongside live status, and the Agents page renders
them.

## Agents

| Agent | Reads | Produces |
| --- | --- | --- |
| Evidence Collector | unprocessed documents | claims |
| Conflict Detector | claims | conflicts |
| Hypothesis Generator | conflicts | hypotheses |
| Investigator | conflicts | evidence, missing-information flags |
| Verification Agent | hypotheses + evidence | hypothesis support scores |
| Decision Agent | evaluated hypotheses + evidence | conclusions |

## Failure isolation and retries

`safe_run` wraps `run`:

* On success, the blackboard changes are committed.
* On failure, the session is **rolled back** — only the failed attempt's
  uncommitted writes are discarded; everything committed by earlier agents is
  preserved — and a structured `failed` result is returned (with a best-effort
  list of the record ids the action referenced).

The controller retries a failed action up to `AGENT_MAX_RETRIES` times (default
`2`, i.e. 3 attempts). Every attempt is a separate ledger row, so retries are
fully auditable. If the action still fails, that agent is **parked** for the
current revision and the loop continues with the others — the investigation is
never aborted by a single agent failure, and it never crashes the application.

## Loop / repeat prevention

Three independent guards stop runaway processing:

1. **Iteration limit** (per investigation) — number of scheduler steps.
2. **Execution limit** — `MAX_AGENT_EXECUTIONS` (default `200`) caps *total*
   executions including retries. Reaching it stops the run with
   `execution_limit_reached`.
3. **Per-action de-duplication** — an action (`agent|objective|conflict`) is
   skipped once it has executed `MAX_ATTEMPTS_PER_ACTION` times (default `3`)
   within the same blackboard revision. This is the anti-infinite-loop guard.

### Re-running on new evidence

A blackboard **revision** counter advances whenever an agent succeeds *and*
reports a non-empty change set. Advancing the revision re-enables previously
parked agents and resets per-action counts, so genuinely new information
(new evidence, a new conflict) naturally re-opens the relevant reasoning.
Change-free successes do **not** advance the revision, so a stub that keeps
proposing identical work is capped rather than looped.

## Cancellation

Cancellation is cooperative and checked:

* before every step,
* before every retry,
* and inside long-running agents via `AgentContext.cancelled()`
  (`controller` supplies a `cancel_check` callback).

A cancelled run stops with `cancelled_by_user`, marks the investigation
`cancelled`, and keeps every committed result.

## Stopping conditions

`InvestigationStopReason`: `no_unresolved_conflicts`,
`no_useful_actions_remaining`, `iteration_limit_reached`,
`execution_limit_reached`, `cancelled_by_user`, `error_prevented_continuation`,
`human_review_required`, `investigation_converged`.

## Determinism

In the default `deterministic` reasoning mode the same inputs produce the same
agent sequence (ordering is by score, tie-broken deterministically). Setting
`max_agent_retries = 0` gives single-attempt execution; scheduling still depends
only on blackboard state and configured weights.

## Configuration

| Setting | Default | Purpose |
| --- | --- | --- |
| `DEFAULT_ITERATION_LIMIT` | `25` | Per-investigation step ceiling. |
| `AGENT_MAX_RETRIES` | `2` | Automatic retries for a failed action. |
| `MAX_AGENT_EXECUTIONS` | `200` | Hard ceiling on total executions (incl. retries). |
| `MAX_ATTEMPTS_PER_ACTION` | `3` | Change-free repeats before an action is parked. |

Exposed read-only via `GET /config`. See `docs/API_REFERENCE.md` and `docs/ARCHITECTURE.md`.

## Tests

`app/tests/test_orchestration.py` covers state assessment, the scheduler
decision state, ledger tracking (sequence + record ids), retry-then-succeed,
exhausted-agent parking, change-free repeat prevention, the execution limit,
pre-run and between-step cancellation, contract manifests, and deterministic
execution ordering.
