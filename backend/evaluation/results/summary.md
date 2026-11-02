# NeuroSync Evaluation Summary

- Generated: 2026-10-10T23:36:41.985518+00:00
- Deterministic mode: True (LLM disabled)

## Conflict detection (headline: confirmed contradictions)

Positive class: confirmed_contradiction (types: direct_contradiction, numerical_disagreement, semantic_inconsistency)

- Examples: 32
- Precision: 0.9091
- Recall: 0.8333
- F1: 0.8696
- False-positive rate: 0.0500
- False-negative rate: 0.1667
- Accuracy: 0.9062
- Confusion: TP=10, FP=1, FN=2, TN=19
- Flag accuracy (any conflict surfaced): 0.9062
- Type accuracy: 0.9062

### Per category

| Category | n | Precision | Recall | F1 | FPR | FNR |
|---|---|---|---|---|---|---|
| conflicting_documents | 4 | 1.0000 | 1.0000 | 1.0000 | n/a | 0.0000 |
| different_measurement_units | 5 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0.0000 |
| different_timestamps | 5 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0.0000 |
| equivalent_statements | 4 | n/a | n/a | n/a | 0.0000 | n/a |
| insufficient_evidence | 4 | n/a | n/a | n/a | 0.0000 | n/a |
| lexical_variation_and_negation | 3 | 0.0000 | 0.0000 | 0.0000 | 1.0000 | 1.0000 |
| missing_context | 3 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0.0000 |
| unreliable_sources | 4 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0.0000 |

### Failure cases

- **lex_subject_synonym_temp** (lexical_variation_and_negation, false_negative): false negative: a real contradiction was missed. Expected contradiction types ['numerical_disagreement'], detector returned ['no conflict']. Extraction produced claims_a=1, claims_b=1.
- **lex_state_synonym_running** (lexical_variation_and_negation, false_negative): false negative: a real contradiction was missed. Expected contradiction types ['direct_contradiction'], detector returned ['no conflict']. Extraction produced claims_a=1, claims_b=0.
- **lex_negation_scope_false_positive** (lexical_variation_and_negation, false_positive): false positive: a non-contradiction was reported as a contradiction. Expected contradiction types ['no conflict (expected)'], detector returned ['direct_contradiction']. Extraction produced claims_a=1, claims_b=1.

## Evidence sufficiency

- Scenarios: 6
- Status accuracy: 1.0000 (6/6)
- Evidence-partition traceability: 1.0000

| Scenario | Expected | Predicted | Correct |
|---|---|---|---|
| no_evidence | inconclusive | inconclusive | True |
| single_source_direct_support | review_required | review_required | True |
| multi_source_direct_support | supported | supported | True |
| contradicting_outweighs | contradicted | contradicted | True |
| balanced_support_and_contradiction | inconclusive | inconclusive | True |
| unreliable_support_outweighed | contradicted | contradicted | True |

## Conclusion traceability (demo investigation)

- Conclusions: 7
- Fully traceable: 7 (rate 1.0000)
- Linked to conflict: 7
- Linked to source claims: 7
- Decisions observed: human_review_required, inconclusive, supported_conclusion
