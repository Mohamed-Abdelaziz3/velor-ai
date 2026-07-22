# VELOR Commercial Authority Contract

This document defines the strict, non-negotiable data authority hierarchy for VELOR's commercial operations. Any code path that bypasses, weakens, or overrides this hierarchy violates core product doctrine and must be rejected.

## 1. Deterministic Structure and Hierarchy

VELOR maintains commercial state through an evidence-bound structure. Truth flows from exact customer actions through deterministic systems. No speculative or generative path may overwrite or replace canonical commercial state.

**Authority Flow:**
1. **Source Evidence** (Highest Authority): Explicit incoming chat messages, signed API events, and verified webhooks.
2. **Deterministic Processing**: Verified matching against exact constraints (e.g. exact budget ranges, regex matching, specific button clicks).
3. **Canonical Truth (`CommercialDecisionLineage`, `CommercialEvent`, and source-linked `LeadEvidence`)**: The deterministic extraction results and explicit customer facts saved with their source-message linkage.
4. **Advisory Generation (`LeadIntelligenceSnapshot`)** (Lowest Authority): LLM-generated summaries, sentiment scores, and recommended actions.

## 2. Truth Classes

All business state is paired with a strict provenance marker known as a Truth Class.

- `OBSERVED`: Explicitly stated by the customer or external API. Example: Customer says "I have 7000 EGP."
- `DETERMINISTICALLY_DERIVED`: Computed via fixed rules from observed state. Example: "Customer budget is 7000. Ergo Pro costs 10900. Ergo Pro is excluded."
- `ADVISORY`: Generated probabilistically by LLMs or heuristics. May be shown to operators as hints, but NEVER drives automated commercial decisions. Example: "Customer seems frustrated."
- `UNKNOWN`: The lack of data. If an observed data point is missing, its value is UNKNOWN.
- `STALE`: Previously valid truth that has expired or been explicitly overridden by newer deterministic truth.

*Rule:* ADVISORY data MUST NEVER fill UNKNOWN fields. Unknown is not an invitation to speculate.

## 3. Consequence of Violating the Graph

Any system (UI, background worker, or API) that violates this graph:
- Corrupts product integrity and tenant isolation.
- Cannot be merged into production.
- If discovered in production, triggers an immediate Rollback and SEV-1 incident.

*Do not create a parallel brain.*

Deterministic writer services persist evidence, state and lineage.
CommercialAuthorityService performs read-only authority resolution.
Owner-facing readers consume the canonical view.

The resolver scopes inbound customer messages, lineage, and evidence by company;
it does not read `LeadIntelligenceSnapshot`. Canonical update SSE events are
invalidation-only and clients must refetch the canonical CRM response.

The resolver must not:
* perform ORM writes;
* generate lineage;
* extract new commercial facts;
* call an LLM;
* create new commercial decisions.

## 4. Revenue Recovery closure boundary

The Revenue Recovery queue is a read projection over source-linked evidence,
current message state, and durable follow-up tasks. Its normalized owner
categories are `WAITING_ON_US`, `READY_FOR_PURCHASE_STEP`, `AT_RISK`, and
`FOLLOW_UP_DUE`. A compact owner queue exposes at most one highest-priority
active item per lead; analytical views may retain source-linked rows where the
additional evidence is useful.

Follow-ups are tenant-scoped workflow state. They are created from explicit
policy reason codes, not arbitrary stage strings; a fresh customer turn
supersedes obsolete source-turn tasks, a successful owner reply completes only
matching reply-required tasks, and terminal lead state cancels remaining active
tasks. A message marked `processing` is not called stuck until its persisted
processing/message timestamp crosses the declared two-minute deterministic
policy. Snooze expiry is a server transition and emits sanitized reactivation
telemetry before the task returns to the due queue.

Product telemetry is not commercial truth. It records validated interactions
such as render, open, owner workspace arrival, suggestion insert, verified send,
dismissal, and stale-send rejection. Client events must resolve to a current
tenant-owned queue, task, lead, or suggestion reference. Server timestamps and
idempotency keys own the persisted event.

`CONFIRMED_ORDER` and `PAID` are never admitted from conversation extraction,
model output, owner UI telemetry, or a lead stage. They require the provider
admission boundary in `VELOR_TRUSTED_OUTCOME_CONTRACT.md`. Until a real provider
adapter is connected, financial metrics are `null` with status
`not_connected`; unknown is not zero.
