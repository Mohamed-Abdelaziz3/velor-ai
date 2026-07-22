# VELOR Conversation Quality Report

## Deterministic semantic results

The collision corpus contains 300 cases across Arabic and Egyptian Arabic,
English, mixed language, punctuation, bounded phrase collisions, negation,
double-negation, pending-action scope, delivery, payment/order, callback,
handoff, verification, purchase, and unknown-fact cases.

| Measure | Result |
| --- | --- |
| Primary capability accuracy | 300/300 (100%) |
| Supported-action precision | 100% |
| Supported-action recall | 100% |
| False-positive persistent actions | 0 |
| False-positive handoff / verification / budget in collision coverage | 0 / 0 / 0 |
| Clarification outcomes in collision corpus | 30/300 (10.0%) |
| Universal fallback dominance | Absent; 14 capability classes appeared in the 150-turn route campaign |

The companion semantic corpus contains 216 additional bounded regression
cases. The combined focused semantic, V2, and atomic suite passed 571 tests.

## Runtime campaigns

- Adversarial real route: 150 turns, all HTTP 200, zero 5xx, p95 56.416 ms,
  fallback-only with no provider, and all eight release collision cases passed.
- Mixed load: 25 visitors × 10 normal turns. All 250 normal turns completed;
  zero 5xx, zero normal-traffic 4xx, zero duplicate normal reply IDs, zero
  unhandled errors, and p95 turn latency 1,597.076 ms (under 5,000 ms).
- Two-tenant API proof: passed for overlapping product/policy data, state,
  pending actions, handoff, Queue, Workspace, Ask VELOR, drafts, attention,
  and SSE isolation.
- Browser: 40 two-turn scenarios (80 submitted turns) were completed in the
  real in-app Public Chat. Required collision, verification, handoff, and
  tenant-specific catalog behavior were visibly inspected.

## Regression result

The final complete backend suite passed: **1,396 passed** in 231.80 seconds.
Frontend checks passed: **26 tests**, lint **0 errors** (10 pre-existing
warnings), and a production Vite build with 2,279 transformed modules.

## Evidence

See [final browser trace](evidence/BROWSER_ACTION_TRACE.md),
[final closure evidence](evidence/FINAL_CLOSURE_EVIDENCE.md), and the
sanitized [adversarial / tenant API JSON](../../../backend/docs/product/conversation_reconstruction/evidence/FINAL_ADVERSARIAL_AND_TENANT_API.json)
and [25×10 load JSON](../../../backend/docs/product/conversation_reconstruction/evidence/FINAL_MIXED_LOAD_25X10.json).
