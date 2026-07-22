# VELOR Phase 6 — Egyptian Commerce AI Evaluation Suite

Date: 2026-07-22
Baseline: `dd563718b119b7759baa684b21434f700c99d824` (Phase 5 checkpoint)
Scope: offline, reproducible evaluation of normalized V2 commerce response traces.

## Scope and safety contract

This phase adds only evaluation assets: a deterministic evaluator, versioned synthetic fixtures, reference traces, a CLI runner, and tests/reporting. It does not call a provider, alter `velor_chat_v2.py`, alter V1, or change tenant isolation, QR, delivery reliability, UI, billing, schemas, or migrations. Fixtures contain no secrets or real customer records.

## Harness design

- Dataset schema: `phase6.dataset.v1`; dataset `egyptian-commerce-v2` version `1.0.0`.
- Prompt contract recorded in the dataset: `v2-commerce-contract-2026-07-22`.
- Every decision records effective prompt, model, and provider versions. The reference set uses `fixture-reference-v1` and `offline-reference-v1`; these are harness identifiers, not production providers.
- Evidence is explicit by `evidence_id`; claims must link to an evidence ID and a used fact ID. Forbidden facts and ungrounded sensitive claims are rejected.
- Decision classes are distinct: `answer`, `escalation`, `refusal`, and `unsupported_claim`.
- Provider degradation is represented explicitly with `response_path`, `provider_available`, and `fallback_reason`.
- Reports are deterministic for identical dataset and response files. `runtime_quality_certified` is always false for the offline reference run.

The repository already contains a larger Phase 4 conversation-quality corpus (112 cases). The Phase 6 dataset is a focused, versioned commerce slice that is easier to run as a release gate and supports replacement with measured provider traces later.

## Coverage

The 24 synthetic cases cover price, discount, stock, size, color, delivery fees, return policy, stale evidence, missing evidence, conflicting catalog/policy data, ambiguous requests, Egyptian Arabic, Arabic-English mixing, Arabizi, spelling mistakes, angry customers, unsupported medical/discount claims, human handoff, purchase handoff, and provider failure/fallback. The reference run contains 12 answer, 8 escalation, 3 refusal, and 1 unsupported-claim outcomes.

## Metrics and honest baseline

The runner defines and reports grounded factual accuracy, unsupported-claim rate, price hallucination rate, stock hallucination rate, correct escalation rate, action-classification accuracy, human acceptance/edit rates, and measured latency/cost samples. On the synthetic reference traces:

| Metric | Reference result | Interpretation |
|---|---:|---|
| Grounded factual accuracy | 1.0 | Contract traces only; not a model score. |
| Unsupported-claim rate | 0.0667 | One deliberately adversarial unsupported-claim fixture among 15 claims. |
| Price hallucination rate | 0.0 | No unsupported price claim in the reference traces. |
| Stock hallucination rate | 0.0 | No unsupported stock claim in the reference traces. |
| Correct escalation rate | 1.0 | Expected escalation flags matched the reference traces. |
| Action-classification accuracy | 1.0 | Expected action labels matched the reference traces. |
| Human acceptance/edit rate | null | No human labels were supplied. |
| Latency / cost | null | No provider calls or measured samples were supplied. |

These numbers are fixture-contract measurements, not merchant outcomes, customer outcomes, market evidence, or a claim of zero hallucinations in production.

## Verification

- `python scripts/run_phase6_evaluation.py` → 24/24 reference traces passed; report is deterministic and marked `runtime_quality_certified: false`.
- `python -m pytest -q tests/test_phase6_commerce_evaluation.py` → **6 passed, 1 warning**.
- The focused V2 regression suite and the complete backend suite were run after the harness changes; exact results are recorded in the final handoff.
- `python -m py_compile evaluation/phase6_commerce_suite.py scripts/run_phase6_evaluation.py tests/test_phase6_commerce_evaluation.py` → passed.
- `git diff --check` → passed.

## Status

### Implemented

The versioned dataset, reference traces, deterministic evaluator, metric definitions, repeatable CLI, evidence checks, decision-class checks, and regression tests are implemented.

### Tested

The evaluator's positive reference run and negative controls for missing responses, missing versions, invalid evidence, price hallucination, stock hallucination, stale/conflicting evidence, and provider fallback are tested.

### Demonstrated

Only the offline synthetic reference contract is demonstrated. No provider was called and no production V2 response was scored in this phase.

### Production-ready

Not claimed. Before using this as a release gate, measured provider traces need to be exported with prompt/model/provider versions, evidence IDs, latency, cost, and (where available) human acceptance/edit labels. Dataset expansion and adjudication are still required for a production-quality quality claim.

### Market evidence

None. This phase produced no customer, revenue, conversion, or market-performance evidence.

## Rollback

Rollback is the unchanged Phase 5 checkpoint `dd563718b119b7759baa684b21434f700c99d824`. Removing the single Phase 6 commit restores the previous repository without touching sessions, databases, logs, or user data.
