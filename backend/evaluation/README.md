# NeuroSync Evaluation

This directory contains the **evaluation harness** for NeuroSync's core
reasoning capabilities. It measures how reliably the system detects
contradictions, evaluates evidence sufficiency, and produces traceable
conclusions. It is deliberately separate from the application (`app/`) and from
the unit-test suite (`app/tests/`); its datasets are labelled evaluation
fixtures and are never loaded into a production database.

> The harness runs the **actual production code**, not a re-implementation:
> claim extraction (`app/services/document_service.extract_document_content`),
> conflict detection (`app/services/conflict_service.detect_conflicts`) and
> evidence scoring (`app/services/scoring_service.score_hypothesis`) are all
> invoked directly.

---

## Quick start

From `neurosync/backend`:

```powershell
.\venv\Scripts\python.exe -m evaluation.run_evaluation
```

This prints a summary and writes reproducible reports to `evaluation/results/`:

- `summary.json` / `summary.md` — overall report
- `conflict_detection.json` — full per-example conflict results
- `evidence_sufficiency.json` — per-scenario evidence results
- `conclusion_traceability.json` — per-conclusion traceability audit

Run it under pytest too:

```powershell
.\venv\Scripts\python.exe -m pytest app/tests/test_evaluation.py -q
```

### Isolation guarantees

- `DATABASE_URL` is redirected to a throwaway SQLite file in a temporary
  directory — your `neurosync.db` is never touched.
- The document-upload directory is redirected to a temporary directory, so the
  demonstration run writes no files into `uploads/`.
- `ENABLE_LLM=false` and no API key: results are deterministic and require no
  network or credentials.

---

## What is measured

### 1. Conflict detection (headline)

A curated, labelled dataset (`datasets/conflicts.json`) of short source pairs is
fed through real extraction + detection. Reported metrics, overall and per
category: **precision, recall, F1, false-positive rate, false-negative rate,
accuracy**, plus the confusion matrix.

**Label definition (ground truth authored independently of the detector):**

- **Positive (`label = true`)** — the two sources make *incompatible* assertions
  about the same subject and property (contemporaneous, or with no legitimate
  differentiator), so they cannot both be accurate. The positive class is a
  **confirmed contradiction**: a detected conflict whose type is one of
  `numerical_disagreement`, `direct_contradiction`, `semantic_inconsistency`.
- **Negative (`label = false`)** — the sources are compatible, equivalent after
  unit normalisation, refer to different times (so a difference may be a genuine
  change), lack the context to compare, or carry insufficient information.

Each example also records:

- `expected_flagged` — whether the detector should surface *any* conflict,
  including the softer `temporal_inconsistency` and `missing_context` signals
  that are **not** themselves confirmed contradictions.
- `expected_types` — the `conflict_type`(s) the detector should assign.

Two auxiliary signals are reported: **flag accuracy** (was any conflict
surfaced?) and **type accuracy** (was the right conflict type assigned?).

### 2. Evidence sufficiency

Labelled evidence configurations (`datasets/evidence_sufficiency.json`) are
materialised as real `Conflict`/`Hypothesis`/`Evidence` rows and scored with
`score_hypothesis`. It checks the **design contract**, for example:

- no evidence → `inconclusive` (never "supported");
- single-source support → `review_required` (one source is *not* independent
  corroboration);
- multi-source direct support → `supported`;
- contradicting evidence outweighing support → `contradicted`;
- balanced support and contradiction → `inconclusive`.

Reported: **status accuracy** (predicted vs expected status) and
**evidence-partition traceability** (does the scorer attribute exactly the right
supporting/contradicting evidence to the hypothesis?).

### 3. Conclusion traceability

The shipped Machine M-17 demonstration is run to completion in deterministic
mode through the real blackboard controller. For every conclusion the audit
checks that it:

- is linked to a conflict, and that conflict to its two source claims;
- for `supported`/`tentative` decisions, cites specific supporting evidence;
- never cites evidence that does not exist or does not belong to its conflict.

Reported: **traceability rate** = fraction of conclusions that satisfy all of
the above.

---

## Scenario categories

The conflict dataset covers all of the following (`categories` in the JSON):

| Category | What it probes |
|---|---|
| `different_measurement_units` | Unit conversion (°C/°F/K) and non-convertible dimensions |
| `different_timestamps` | The 30-minute gap rule; genuine change vs contradiction |
| `missing_context` | Missing timestamps/units; incomparable quantities |
| `conflicting_documents` | Direct numeric/state contradictions across sources |
| `unreliable_sources` | Detection is reliability-agnostic; reliability applied downstream |
| `insufficient_evidence` | Nothing comparable to contradict |
| `equivalent_statements` | Same fact, different wording/units — must not be flagged |
| `lexical_variation_and_negation` | Known-hard cases (see below) |

---

## Representative failure cases

These are genuine, reproducible limitations of the rule-based detector, retained
deliberately so the evaluation measures reality rather than a curated success
set. Each is explained in the `failures` array of `conflict_detection.json`.

| Example | Kind | Why it fails |
|---|---|---|
| `lex_subject_synonym_temp` | False negative | `temp` vs `temperature`: the rule-based subject extractor keys on the literal word `temperature`, so the two claims land on different subjects and the same-time disagreement is missed. |
| `lex_state_synonym_running` | False negative | `not running` vs `operating normally`: `running` is not in the state/status vocabulary, so the second statement yields no claim. |
| `lex_negation_scope_false_positive` | False positive | `...operating normally, with no anomalies`: the token `no` is treated as a negation of the whole statement, flipping polarity and producing a spurious `direct_contradiction`. |

These point to concrete improvements (a synonym/lemma layer for subjects and
states, and negation-scope handling) and are the intended candidates for future
work.

---

## Metrics reference

For the positive class defined above:

- **Precision** = TP / (TP + FP)
- **Recall** = TP / (TP + FN)
- **F1** = 2·TP / (2·TP + FP + FN)
- **False-positive rate** = FP / (FP + TN)
- **False-negative rate** = FN / (FN + TP)

Rates with an undefined denominator (e.g. recall in a category with no positive
examples) are reported as `null`/`n/a`, never as an invented number. See
`metrics.py`.

---

## Reproducing and interpreting results

- **Reproducible:** metrics are a pure function of the datasets and the code.
  The `generated_at` timestamp and the *details* of generated IDs are metadata
  and do not affect any metric. The report also stores SHA-256 hashes of the
  datasets so a run can be tied to exact inputs.
- **Honest by construction:** the positive class, the "confirmed contradiction"
  types and every label are defined *before* running the detector; the harness
  only compares the detector's output to those labels. No metric is asserted
  without a measurement.
- **Known-hard cases are included on purpose**, so a perfect score is not the
  expected outcome. A change to the detector should move the failure set; the
  pytest wrapper (`app/tests/test_evaluation.py`) pins the current failure set
  and metric floors so drift is caught.

---

## Limitations

- **Small, synthetic, hand-labelled dataset.** It is designed to be transparent
  and diagnostic, not to be a statistically representative benchmark. Metrics
  should be read as *contract checks on these scenarios*, not as general
  accuracy on arbitrary real-world corpora.
- **English, fixed formats.** Texts use a neutral `HH:MM` style and vocabulary
  the deterministic extractor supports. Vocabulary variation is exactly where
  the detector is weakest (see failures).
- **Detection scope.** The headline positive class excludes `temporal_
  inconsistency` and `missing_context`; those are reported separately as
  *flags*, because they are surfaced-for-review signals rather than confirmed
  contradictions.
- **Evidence sufficiency tests the scorer's contract**, using synthetic
  evidence rows; it does not measure end-to-end evidence *discovery* quality.
- **Deterministic mode only.** The harness forces `ENABLE_LLM=false`; AI-assisted
  behaviour is not evaluated here (it is covered by the unit suite's mocked
  provider).
- **Traceability is structural**, not semantic: it verifies that cited evidence
  exists and belongs to the conclusion's conflict, not that the citation is a
  good argument.

---

## Layout

```
evaluation/
├── datasets/
│   ├── conflicts.json               # labelled contradiction dataset
│   └── evidence_sufficiency.json    # labelled evidence scenarios
├── conflict_eval.py                 # runs conflicts through the real pipeline
├── evidence_eval.py                 # evidence sufficiency + traceability
├── metrics.py                       # precision/recall/F1/FPR/FNR
├── run_evaluation.py                # CLI entry point
├── results/                         # generated (reproducible) reports
└── README.md
```
