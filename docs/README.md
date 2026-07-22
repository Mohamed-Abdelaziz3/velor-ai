# VELOR documentation map

Use the current architecture and ADRs for implementation decisions. Files under
`audits/` are date-bound evidence and must not be treated as evergreen product,
market, or production-readiness claims.

## Current implementation references

- [`architecture/CURRENT_ARCHITECTURE.md`](architecture/CURRENT_ARCHITECTURE.md) — runtime units, canonical V2 flow, persistence, delivery, tenant boundaries, and known limits.
- [`../README.md`](../README.md) — product purpose, implemented capabilities, setup, quality commands, and honest status.
- [`setup/LOCAL_SETUP.md`](setup/LOCAL_SETUP.md) — reproducible dependency installation and local verification.
- [`release/VELOR_LAUNCH_READINESS_AUDIT.md`](release/VELOR_LAUNCH_READINESS_AUDIT.md) — external gates that still block a public paid launch.

## Recommended GitHub Repository Topics

When publishing or configuring repository settings on GitHub, use the following topics:
- `artificial-intelligence`
- `conversational-ai`
- `llm`
- `rag`
- `saas`
- `fastapi`
- `react`
- `python`
- `multi-tenant`
- `ecommerce`


## Architecture Decision Records

- [`ADR-0001`](adr/0001-canonical-v2-conversation-path.md) — V2 is the canonical conversation path; V1 remains explicit rollback.
- [`ADR-0002`](adr/0002-bounded-modular-monolith.md) — improve one deployable incrementally through real capability boundaries.
- [`ADR-0003`](adr/0003-separate-decision-from-delivery.md) — decision, persistence, and channel delivery are distinct facts.
- [`ADR-0004`](adr/0004-message-backed-delivery-reliability.md) — outgoing messages provide durable, idempotent delivery intent.
- [`ADR-0005`](adr/0005-authenticated-tenant-context.md) — tenant context comes from authenticated/verified boundaries.
- [`ADR-0006`](adr/0006-evidence-grounded-offline-evaluation.md) — versioned synthetic fixtures provide an honest offline regression gate.

Phase 2 canonical-path decision: [`audits/VELOR_PHASE_2_CANONICAL_CONVERSATION_PATH_DECISION_2026-07-22.md`](audits/VELOR_PHASE_2_CANONICAL_CONVERSATION_PATH_DECISION_2026-07-22.md).

Phase 3A QR/V2 hardening: [`audits/VELOR_PHASE_3A_CANONICAL_V2_HARDENING_2026-07-22.md`](audits/VELOR_PHASE_3A_CANONICAL_V2_HARDENING_2026-07-22.md).

Phase 3B bounded modular-monolith refactor: [`audits/VELOR_PHASE_3B_BOUNDED_MODULAR_MONOLITH_REFACTOR_2026-07-22.md`](audits/VELOR_PHASE_3B_BOUNDED_MODULAR_MONOLITH_REFACTOR_2026-07-22.md).

Phase 4 outbox and delivery reliability: [`audits/VELOR_PHASE_4_OUTBOX_DELIVERY_RELIABILITY_2026-07-22.md`](audits/VELOR_PHASE_4_OUTBOX_DELIVERY_RELIABILITY_2026-07-22.md).

Phase 5 authentication and tenant isolation: [`audits/VELOR_PHASE_5_AUTHENTICATION_TENANT_ISOLATION_2026-07-22.md`](audits/VELOR_PHASE_5_AUTHENTICATION_TENANT_ISOLATION_2026-07-22.md).

Phase 6 Egyptian Commerce AI Evaluation Suite: [`audits/VELOR_PHASE_6_EGYPTIAN_COMMERCE_AI_EVALUATION_2026-07-22.md`](audits/VELOR_PHASE_6_EGYPTIAN_COMMERCE_AI_EVALUATION_2026-07-22.md).

Phase 7 product/UI simplification: [`audits/VELOR_PHASE_7_PRODUCT_UI_SIMPLIFICATION_2026-07-22.md`](audits/VELOR_PHASE_7_PRODUCT_UI_SIMPLIFICATION_2026-07-22.md).

The repository contains product contracts as well as historical engineering evidence. This index prevents an old phase report from being mistaken for the current product or launch verdict.

## Security and publication

- [`../SECURITY.md`](../SECURITY.md) — security reporting and handling policy.
- [`security/LOCAL_ARTIFACT_HANDLING.md`](security/LOCAL_ARTIFACT_HANDLING.md) — public-source boundary and backup-first handling for local artifacts.
- [`audits/VELOR_PHASE_8_GITHUB_READINESS_2026-07-22.md`](audits/VELOR_PHASE_8_GITHUB_READINESS_2026-07-22.md) — current GitHub-readiness audit, verification results, and license proposal.

## Repository setup and hygiene

- [`setup/LOCAL_SETUP.md`](setup/LOCAL_SETUP.md) — locked local setup and verification commands.
- [`audits/VELOR_PHASE_0_DISCOVERY_SECURITY_BASELINE_2026-07-22.md`](audits/VELOR_PHASE_0_DISCOVERY_SECURITY_BASELINE_2026-07-22.md) — pre-edit discovery and security baseline.
- [`audits/VELOR_PHASE_1_REPRODUCIBLE_SETUP_PUBLIC_REPOSITORY_HYGIENE_2026-07-22.md`](audits/VELOR_PHASE_1_REPRODUCIBLE_SETUP_PUBLIC_REPOSITORY_HYGIENE_2026-07-22.md) — implemented Phase 1 changes, verification evidence, and remaining limits.
- [`audits/VELOR_PHASE_1_COMPLETION_GIT_INITIALIZATION_2026-07-22.md`](audits/VELOR_PHASE_1_COMPLETION_GIT_INITIALIZATION_2026-07-22.md) — local initial-commit evidence and rollback references.

## Active architecture and behavior contracts

- [`architecture/CURRENT_ARCHITECTURE.md`](architecture/CURRENT_ARCHITECTURE.md) — current code-backed system map and channel lifecycle.
- [`product/VELOR_CONVERSATION_REVENUE_ENGINE.md`](product/VELOR_CONVERSATION_REVENUE_ENGINE.md) — current product thesis, paid value loop, analytics model, KPI framework, and implementation order.
- [`architecture/VELOR_COMMERCIAL_AUTHORITY_CONTRACT.md`](architecture/VELOR_COMMERCIAL_AUTHORITY_CONTRACT.md) — source-of-truth boundaries for commercial data.
- [`product/conversation_reconstruction/VELOR_CONVERSATION_ENGINE_ARCHITECTURE.md`](product/conversation_reconstruction/VELOR_CONVERSATION_ENGINE_ARCHITECTURE.md) — canonical V2 response path.
- [`product/conversation_reconstruction/VELOR_PROVIDER_AND_FALLBACK_CONTRACT.md`](product/conversation_reconstruction/VELOR_PROVIDER_AND_FALLBACK_CONTRACT.md) — provider and safe-fallback behavior.
- [`product/conversation_reconstruction/VELOR_ACTION_AND_HANDOFF_CONTRACT.md`](product/conversation_reconstruction/VELOR_ACTION_AND_HANDOFF_CONTRACT.md) — customer action and human handoff.
- [`product/semantic_fulfillment/VELOR_ANSWER_OBLIGATION_CONTRACT.md`](product/semantic_fulfillment/VELOR_ANSWER_OBLIGATION_CONTRACT.md) — bounded answer obligations.

## Pilot product research

`product/validation/` contains merchant recruitment, conversation review, KPI, pricing, and pilot-operation templates. These are experiment designs, not claims of measured customer outcomes.

## Historical evidence

`audits/` contains date-bound baselines and phase reports. Files named `PHASE_*`, `*_REPORT`, `*_ACCEPTANCE`, or `*_CLOSURE` are evidence snapshots, not evergreen launch claims. They remain useful for traceability, but only the current launch audit above may decide release readiness.

Local browser traces, databases, logs, remediation scripts, and bulky phase evidence are intentionally excluded from Git by `.gitignore`.
