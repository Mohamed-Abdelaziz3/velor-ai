# VELOR Final Semantic Fulfillment Acceptance

STATUS: VELOR SEMANTIC FULFILLMENT ACCEPTED — REAL PROVIDER QUALITY PENDING

## Production acceptance result

The public V2 route was run against a freshly migrated SQLite verification database at Alembic head `9f8e7d6c5b4a`, seeded with the isolated ARVENA and BARAKA fixtures. The provider was unavailable and every accepted response used the real fallback path.

| Gate | Result |
| --- | --- |
| Development corpus | 300 / 300 passed |
| Hidden corpus | 150 / 150 passed |
| Mandatory V2 fixtures | 10 / 10 passed |
| Real public-route campaign | 200 / 200 HTTP 200; 200 semantic traces passed |
| Campaign latency | 56.0 ms mean; 63.0 ms p95 |
| Collision checks | 8 / 8 passed |
| Two-tenant proof | passed: state, actions, handoff, queue, workspace, timeline, copilot, SSE, and tenant lookup isolated |
| Browser review | 50 complete conversations / 100 turns accepted |
| 25×10 fallback load | passed; 25 sessions, 250 turns, 0 normal 4xx, 0 5xx |
| Load latency | session p95 1,275.154 ms; turn p95 1,349.506 ms |
| Complete backend suite | 1,850 passed |

The final campaign used 12 bounded loopback clients and a 1.05-second cadence so every request remained within the unchanged default per-IP, per-visitor, and per-tenant public-route rate limits. Its evidence contains no visitor identifiers, customer messages, reply prose, bearer tokens, or prompts.

The throughput test used a verification-only high-capacity rate profile to measure 25-way fallback throughput without intentionally treating production anti-abuse throttling as a load failure. Default rate-limit behavior is separately exercised by the campaign above.

## Remaining risk

No valid real text-generation provider was configured for this acceptance run. The deterministic fallback is production-accepted for the documented semantic contract, but live-provider writing quality, latency, and repair behavior require a separately configured provider rehearsal before provider-quality certification.

## Evidence

- `evidence/FINAL_SEMANTIC_HTTP_200.json`
- `evidence/FINAL_SEMANTIC_MIXED_LOAD_25X10.json`

No frontend source files changed in this closure, so frontend tests/lint/build were not rerun.
