# ADR-0006: Evaluate grounded commerce behavior with versioned offline fixtures

- Status: Accepted
- Date: 2026-07-22
- Scope: Regression evaluation of V2 commerce response traces

## Context

Prompt or provider changes can regress prices, stock, policy claims, Egyptian Arabic behavior, and escalation. A test must preserve the evidence behind each expected decision and must not fabricate live-provider performance, merchant outcomes, latency, or cost.

## Decision

Maintain a versioned, synthetic, offline evaluation dataset and reference-response file. Record prompt/model/provider identifiers, evidence IDs, claim support, decision class, provider/fallback state, and deterministic metrics. Treat `answer`, `escalation`, `refusal`, and `unsupported_claim` as separate outcomes.

Reference traces test the evaluation contract. They are not production model scores. Human acceptance/edit, latency, and cost remain null unless measured inputs are supplied.

## Consequences

- Future prompt/provider changes have a reproducible regression gate.
- Sensitive price/stock claims must link to evidence.
- Stale, missing, or conflicting evidence can require escalation or refusal.
- Synthetic pass rates cannot be presented as customer or market results.

## Evidence in the current code

- `backend/evaluation/phase6_commerce_suite.py`
- `backend/evals/phase6/egyptian_commerce_v1.json`
- `backend/evals/phase6/reference_responses_v1.json`
- `backend/scripts/run_phase6_evaluation.py`
- `backend/tests/test_phase6_commerce_evaluation.py`

## Not decided

This ADR does not fine-tune a model, add a provider, change production prompts, or certify live-provider quality.
