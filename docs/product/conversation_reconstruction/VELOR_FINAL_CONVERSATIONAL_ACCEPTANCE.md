# VELOR Final Conversational Acceptance

## Status

`STATUS: VELOR CONVERSATIONAL INTELLIGENCE ACCEPTED — REAL PROVIDER QUALITY PENDING`

The deterministic V2 route, public-turn transaction boundary, browser checks,
tenant proof, adversarial route campaign, and mixed load campaign have passed.
The configured provider is unavailable, so this acceptance is limited to the
safe deterministic/fallback path.

## Accepted closure

- Bounded Arabic-aware routing replaced unbounded substring dispatch. It uses
  normalized tokens, bounded phrases, negation scope, evidence, confidence,
  pending-action scope, and deterministic action gates.
- `CapabilityDecision` exposes capability, optional secondary capability,
  policy kind, offer/execute action, confidence, evidence, negation,
  dependencies, eligibility, clarification, and reason code. It is internal
  only and is not exposed in public responses.
- V2 keeps the idempotency lease uncommitted while planning. One executor then
  commits the inbound message, response, state delta, zero-or-one action,
  lineage, invalidation, telemetry, and claim completion together. A failed
  generation rolls back the lease itself.
- The concurrent acceptance fence permits exactly one response and one action
  for a claimed turn. Sequential replays reuse the accepted response.

## Closure gates

| Gate | Result |
| --- | --- |
| Collision corpus | 300/300 routing cases passed; supported-action precision and recall 100% in corpus coverage |
| Focused semantic / V2 / atomic suite | 571 passed |
| Adversarial real-route campaign | 150/150 HTTP 200; zero 5xx; p95 56.416 ms |
| Browser acceptance | 40 two-turn browser scenarios (80 submitted turns), required collision/action checks visibly verified |
| Two-tenant proof | API isolation passed for state, actions, handoff, verification, Queue, Workspace, Ask VELOR, drafts, and SSE; browser showed tenant-specific 7,500 EGP catalog price |
| Mixed load | 25 visitors × 10 turns = 250 normal turns; zero 5xx, zero duplicate normal reply IDs; p95 1,597.076 ms |
| Complete backend suite | 1,396 passed |
| Frontend | 26 tests passed; lint 0 errors / 10 pre-existing warnings; production build passed |

## Remaining risk

No real provider was configured for this verification. Provider-assisted
classification and prose quality therefore remain to be assessed separately.
The production provider must still be configured with valid credentials and
observed under its own latency, safety, and quality monitoring.
