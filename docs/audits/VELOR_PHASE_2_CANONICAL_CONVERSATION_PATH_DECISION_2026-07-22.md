# VELOR Phase 2 — Canonical Conversation Path Decision

**Date:** 2026-07-22
**Repository checkpoint inspected:** `4b48b2ec2408fe60704e6768ed3ec1a8432dcd69` (`chore: establish reproducible Phase 1 baseline`)
**Phase status:** Complete as an analysis and decision record only. No product code, runtime configuration, database, route, file location, or V1/V2 implementation changed.

## Scope contract

This phase traces the source at the stated checkpoint and records one conversation-decision authority for Web Chat, QR, Meta, and External API. The only changes are this analysis record and its documentation-index entry.

It does **not** change product behaviour; refactor or move files; remove V1 or V2; change the API, QR security, database, or UI; or begin Phase 3. V1 remains the rollback path. No secret values, session data, database records, or logs were opened, copied, or printed.

## Inputs read before the decision

1. [Phase 0 discovery and security baseline](VELOR_PHASE_0_DISCOVERY_SECURITY_BASELINE_2026-07-22.md).
2. [Phase 1 reproducible setup and repository hygiene](VELOR_PHASE_1_REPRODUCIBLE_SETUP_PUBLIC_REPOSITORY_HYGIENE_2026-07-22.md).
3. [Phase 1 completion / initial Git commit](VELOR_PHASE_1_COMPLETION_GIT_INITIALIZATION_2026-07-22.md).
4. The current source at the stated Git HEAD.

## Decision — one canonical conversation-decision path

**V2 is the canonical customer-conversation decision and persistence path for all four ingress adapters.** This follows source evidence, not the name “V2”. Each accepted V2 turn reaches the same two authorities:

- `services.velor_chat_v2.get_v2_ai_response`: bounded context, retrieval, deterministic plan, model writer, validation, one repair maximum, and safe fallback.
- `services.public_chat_turn_service.persist_v2_public_turn_atomic`: channel-agnostic transactional executor that fences the claim, projects messages/commercial state/telemetry, and completes the claim in one commit.

Transport remains channel-specific after that atomic turn:

```text
Web visitor JWT ─┐
QR Baileys ─────┼─ ingress authentication / tenant adapter
Meta webhook ───┤       │
External API ───┘       ▼
                       V2 claim → V2 response decision → atomic V2 turn
                                                   │
             ┌────────────────────────────────────┼────────────────────────┐
             ▼                                    ▼                        ▼
        HTTP response                       QR send + ACK            Meta Graph send + receipt
        (Web / External)                    (Baileys)                 (durable inbox)
```

This selects **conversation authority**, not identical delivery contracts or production readiness. QR has direct-gateway exceptions and External API has no provider delivery acknowledgement; both are retained and documented rather than hidden.

### Evidence-based comparison

| Criterion | V2 evidence | V1 / rollback contrast |
| --- | --- | --- |
| Common authority | Web, QR, and Meta call the same response function and atomic executor; External enters the same QR/external V2 adapter. | V1 separately calls `brain.get_ai_response` through compatibility branches. |
| Duplicate safety | Processing claim, exact-attempt fence, and `in_reply_to_message_id` replay the recorded response instead of generating again. | Compatibility lookup may select a later outgoing row when linkage is absent. |
| Grounding | Context includes bounded history, catalog, knowledge retrieval, memory, and policy; claim, fulfilment, and style checks bound the writer. | Retained rollback path, not the common bounded authority. |
| Safe degradation | Provider absence/rejection uses a deterministic contextual fallback and records its trace. | Implementation-specific legacy behaviour. |
| Atomic state | One transaction writes message lineage, safe envelope, commercial projection, trace, telemetry, and claim completion. | Older persistence is retained only for rollback. |

`validate_runtime_configuration` requires the three engine selectors to resolve to V2 in `verification`, `staging`, and `production`. This is source-level guardrail evidence; it does not prove a deployment applies it.

## Canonical V2 call graph

```text
channel entry
  → authenticate caller / provider and resolve exactly one tenant
  → normalize channel identity and require or construct idempotency key
  → acquire_inbound_processing_claim(company, user, external_message_id)
  → get_v2_ai_response(source message, company, lead, channel, route)
       → dialogue continuity; history/catalog/RAG/policy/memory context
       → deterministic response plan and escalation action
       → model writer (at most one repair) or contextual fallback
       → claim, fulfilment, and style validation; envelope and trace
  → persist_v2_public_turn_atomic(..., channel type, delivery state)
       → exact-claim fence; linked messages; commercial and analytics writes
       → claim completion and single commit
  → channel delivery adapter and receipt semantics
```

The processing claim results are acquired, already processing, completed, intentionally skipped, retryably reclaimed, or unknown unsafe. A completed claim finds its linked response; V2 stages observable side effects until the atomic executor accepts the turn.

## Route comparison

| Channel | Actual entry | Tenant authority | V2 selector | Post-persistence delivery | Principal unresolved boundary |
| --- | --- | --- | --- | --- | --- |
| Web Chat | public session, then `POST /api/public/chat` | signed visitor token; active public slug at session creation | `PUBLIC_WEB_CHAT_RESPONSE_ENGINE` | HTTP response; persisted `sent` | no live browser/deployment demonstration here |
| QR | Baileys `messages.upsert` → `POST /chat` | gateway session company; internal secret plus `X-Company-ID` | `WHATSAPP_RESPONSE_ENGINE` | Baileys send then FastAPI ACK | gateway direct replies bypass canonical persistence; Node control auth untested |
| Meta | signed webhook → durable inbox worker | Meta phone-ID map, else configured company | `WHATSAPP_RESPONSE_ENGINE` | Graph send then provider status receipt | disabled by default; no live Meta proof |
| External API | API-key branch of `POST /chat` | hashed API key selects active company | `EXTERNAL_API_RESPONSE_ENGINE` | synchronous API response only | no caller delivery ACK; stale pending row is failed by scheduler |

## Per-path trace

### 1. Web Chat

| Required stage | Current source behaviour and canonical-path result |
| --- | --- |
| Entry point | `POST /api/public/companies/{slug}/session` creates the visitor session; `POST /api/public/chat` receives a turn; the session GET returns safe history. |
| Authentication and tenant resolution | Session creation finds a non-deleted company by public slug and checks Web Chat enablement. It signs a visitor JWT with issuer/audience/role constraints. Chat validates that token and derives tenant and visitor from its claims rather than caller input; IP and tenant/visitor limits also apply. |
| Normalization and deduplication | Required `client_message_id` becomes `wc:<company_id>:<client_message_id>`. The processing claim owns the turn; active duplicates return `202`, completed duplicates return the linked reply/envelope. |
| Retrieval | V2 builds bounded prior history; retrieves knowledge chunks; normalizes catalog; resolves product continuity; and evaluates policy, memory/communication, sales, objections, recommendations, and next-best action. |
| Generation | `get_v2_ai_response` creates the plan and uses the configured writer once, with at most one validation repair, or local contextual/continuity fallback. |
| Validation | `ClaimVerifier`, answer-fulfilment checks, and writer-style validation gate model output. The public response never contains the internal trace. |
| Escalation | A handoff plan can set human-intervention/pause state. Pre- and post-persistence auto-reply guards stop output for company disablement or active takeover; skipped turns may create workspace suggestions. |
| Persistence | The shared atomic executor writes inbound projection, linked outbound row, safe response envelope, events, commercial state, trace, telemetry, and completed claim. Its default outbound state is `sent` for Web. |
| Delivery | The HTTP response returns `reply`, public id, and additive safe `response` envelope. The response is the delivery boundary; there is no external provider receipt. |
| Analytics | Atomic persistence records V2 trace and `customer_reply_generated`; Web additionally records `first_public_conversation` and may record `purchase_handoff_started`. |
| Fallback behaviour | Provider outage/rejection uses bounded contextual fallback. Timeout/error rolls back the open V2 claim and returns `504`/`500`, permitting safe same-id retry. Quota/takeover records a skip instead of generating. |
| Tests and feature flag | `PUBLIC_WEB_CHAT_RESPONSE_ENGINE`; targeted V2/atomic coverage: `test_public_chat_atomic_turn.py`, `test_public_chat_latency_resilience.py`, `test_velor_chat_v2.py`, and `test_velor_web_chat_channel.py`. The broad fixture defaults to V1, so its aggregate result is not all-V2 evidence. |

### 2. QR / Baileys WhatsApp gateway

| Required stage | Current source behaviour and canonical-path result |
| --- | --- |
| Entry point | `backend/whatsapp_gate.js` handles Baileys `messages.upsert` for non-self, non-group text and forwards ordinary accepted messages to `POST /chat`. QR bootstrap/status/control endpoints are gateway control routes, not customer-conversation ingress. |
| Authentication and tenant resolution | Gateway state owns a `companyId` session and calls `/chat` with `X-Internal-Secret` and `X-Company-ID`. FastAPI constant-time verifies the internal secret, requires the tenant identifier, and resolves a non-deleted company. The customer JID is transport identity, not an authenticated VELOR account. |
| Normalization and deduplication | The gateway has an in-memory set keyed by company/message id, capped at 2,000 entries. V2 requires `external_message_id`, claims it durably, and resolves the lead through JID/normalized WhatsApp variants. The backend claim is authoritative; gateway memory is a short-lived first filter. |
| Retrieval | Accepted turns use the same V2 context construction, with `channel_type=WHATSAPP_QR` and source route `/chat`. |
| Generation | The same `get_v2_ai_response` produces the bounded answer and trace. |
| Validation | The same fact, fulfilment, and style validation / single repair / deterministic fallback applies before persistence. |
| Escalation | Auto-reply disabled and human-takeover state are checked before model work; the V2 late guard repeats the check at persistence. Skips can create workspace suggestions. |
| Persistence | The shared executor stores `WHATSAPP_QR`, telemetry source `whatsapp_gateway`, outbound `pending`, and linked inbound/outbound messages. Completed duplicates reuse the persisted reply; a sent/delivered/read provider-linked response is not resent. |
| Delivery | The gateway receives the reply, calls Baileys `sendAndAck`, then posts provider id/status to `/api/whatsapp/webhook/ack` under the internal secret. Later Baileys sent/delivered/read updates become ACKs; FastAPI applies monotonic delivery state. |
| Analytics | The V2 trace and customer-reply event are durable. Gateway `deliveryAttempts` are process-memory diagnostics only, not durable analytics. |
| Fallback behaviour | `fetchAIWithRetry` retries gateway-to-backend calls up to three times before a reply exists. V2 has its bounded fallback. A send failure after a backend reply suppresses local fallback to avoid duplicates. A pre-reply backend failure sends `TECHNICAL_FALLBACK_REPLY` directly, without FastAPI persistence/trace. A message over 800 characters is also directly answered by the gateway and bypasses V2. |
| Tests and feature flags | `WHATSAPP_RESPONSE_ENGINE`; operational boot control `AUTO_BOOT_SESSIONS`. `test_whatsapp_v2_runtime.py` covers exactly-once, required provider id, ACK monotonicity, stale-worker state, and takeover. `test_auto_reply_control.py` covers FastAPI ACK recovery. No Node HTTP test asserts denial without `X-Internal-Secret` for gateway control routes. |

### 3. Meta WhatsApp webhook

| Required stage | Current source behaviour and canonical-path result |
| --- | --- |
| Entry point | `GET /api/whatsapp/webhook` verifies subscription. `POST /api/whatsapp/webhook` persists a durable `WebhookInbox` item, returns `200 OK`, and schedules `process_webhook_inbox_item`. |
| Authentication and tenant resolution | Disabled unless `ENABLE_META_WEBHOOK` is truthy. POST validates `X-Hub-Signature-256` and fails closed if the app secret is absent; GET compares the verify token. The worker maps provider `phone_number_id` through `META_PHONE_COMPANY_MAP`, else the configured company. Missing mapping drops the message; customer phone is normalized from the signed event. |
| Normalization and deduplication | Durable inbox deduplicates by payload hash and captures provider event ID. Batches are split into one logical message per processing claim. V2 requires the provider message id and claims it per tenant/customer. |
| Retrieval | The worker invokes the shared V2 context/retrieval path with `channel_type=WHATSAPP_META` and `/api/whatsapp/webhook`. |
| Generation | The same V2 writer/fallback authority runs after claim acquisition. |
| Validation | The same fact, answer-obligation, and style validation applies, with at most one repair and contextual fallback. |
| Escalation | Human takeover, auto-reply disablement, and quota exhaustion produce intentional skips; eligible skips can create a workspace suggestion. The late V2 guard remains active. |
| Persistence | Shared atomic persistence writes a pending outbound before dispatch, with `WHATSAPP_META` and `meta_whatsapp` telemetry. The inbox item completes only when payload processing succeeds. |
| Delivery | The worker calls Meta Graph API after persistence, attaches provider id and records `sent`; it records `failed` and re-raises on dispatch failure for inbox retry. Later provider statuses update sent/delivered/read/failed. A receipt arriving before outbound-id linkage deliberately forces durable retry. |
| Analytics | V2 trace, customer-reply event, and purchase-handoff event persist through the shared executor. Inbox status/attempt/error category are operational recovery evidence. |
| Fallback behaviour | V2 uses contextual fallback. Inbox failures become `failed` and scheduler recovery runs every minute; configured maximum attempts leads to `dead_letter`. Meta is disabled by default and not externally demonstrated. |
| Tests and feature flags | `ENABLE_META_WEBHOOK`, `WHATSAPP_RESPONSE_ENGINE`, and inbox stale/attempt controls. `test_meta_webhook_signature.py` covers fail-closed signature checks; `test_whatsapp_v2_runtime.py` covers V2 send/retry, batches, durable inbox, and receipt relinking; `test_webhook_processing_claim.py` and `test_webhook_retry_idempotency.py` cover claim/retry. These are local/mocked tests, not live Meta evidence. |

### 4. External API

| Required stage | Current source behaviour and canonical-path result |
| --- | --- |
| Entry point | `POST /chat` is shared. The External API branch is selected by `X-API-Key`; the QR branch is selected by the internal secret. This section covers the API-key branch only. |
| Authentication and tenant resolution | `X-API-Key` is required; its hash resolves an active company by `api_key_hash`. Missing credentials return `401`; unknown company returns `404`. Request `user_id` is a caller-supplied customer identity within that authenticated tenant. |
| Normalization and deduplication | V2 rejects missing `external_message_id` with `400`, then claims that id per tenant/customer. Lead lookup/creation is tenant-scoped; completed duplicates find the linked persisted reply. |
| Retrieval | Same V2 history, catalog, knowledge, policy, customer/commercial-signal context, traced with `channel_type=EXTERNAL_API` and route `/chat`. |
| Generation | Same `get_v2_ai_response` authority. |
| Validation | Same claim, fulfilment, and style checks; one repair maximum; safe envelope and deterministic fallback. |
| Escalation | Auto-reply controls and V2 persistence guard can skip for takeover/company disablement. A handoff plan can persist human-handoff state and eligible workspace suggestion. |
| Persistence | Shared executor writes full turn with `EXTERNAL_API`, telemetry source `external_api`, and outbound delivery `pending`. |
| Delivery | The API returns `reply`, internal id, safe response envelope, and pending state synchronously. No API endpoint/protocol ACKs caller delivery. The generic scheduler marks pending outbound rows failed after five minutes. This is a lifecycle mismatch, not proof of customer delivery. |
| Analytics | Shared V2 trace and customer-reply event persist under `external_api`; handoff event follows the common executor. |
| Fallback behaviour | Provider unavailable/rejected uses contextual fallback. Timeout/error rolls back V2 session and propagates failure; same external id is safe retry input. |
| Tests and feature flags | `EXTERNAL_API_RESPONSE_ENGINE`; `test_readiness_contract.py` confirms V2 default/explicit V1 rollback. `/chat` V2 delivery/claim controls are exercised in `test_whatsapp_v2_runtime.py`, `test_webhook_processing_claim.py`, and `test_resilience.py`. No dedicated caller-ACK test exists because no source contract exists. |

## QR gateway security boundary — explicit high-risk finding

Phase 0 reported these gateway controls as high-risk **unprotected** routes if they were reachable beyond the loopback default:

| Route | Sensitive consequence if unauthenticated | Current-head static observation | Security disposition in this phase |
| --- | --- | --- | --- |
| `GET /api/whatsapp/stream/:company_id` | Exposes QR/session state. | `app.use('/api/whatsapp', requireInternalSecret)` appears immediately before the routes; its middleware fails closed without a configured matching header. | **High risk — not closed.** Static prefix middleware appears to cover it, but no Node route test proves rejection/acceptance and no network deployment was exercised. |
| `GET /api/whatsapp/status/:company_id` | Enumerates tenant QR/session state. | Same prefix middleware. | **High risk — not closed.** |
| `POST /api/whatsapp/start/:company_id` | Boots or reconnects a tenant QR session. | Same prefix middleware. | **High risk — not closed.** |
| `POST /api/whatsapp/send/:company_id` | Sends from a tenant WhatsApp session. | Same prefix middleware. | **High risk — not closed.** |

This is an evidence discrepancy, not a security closure. Phase 0 says the routes lack route-level control; current HEAD contains a prefix middleware call whose normal Express semantics should apply to every descendant. The two facts do not prove runtime route ordering, proxy exposure, header forwarding, or negative behaviour. Phase 2 made no security change. Before any non-loopback/tunnel/container exposure, an authorised security phase must run Node negative/positive tests, verify the deployed proxy path, and resolve this discrepancy explicitly.

Other QR canonicality risks:

- Over-800-character and pre-backend-failure technical replies are direct Baileys sends, absent from V2 persistence and analytics.
- `AUTO_BOOT_SESSIONS` defaults to true in code, although the safe example sets it false; saved sessions remain operationally significant.
- Gateway deduplication and delivery-attempt information are in memory. The FastAPI claim and message records are the durable source of truth.

## Feature flags, rollback, and V1 preservation

| Channel | Canonical V2 selector/default | Explicit V1 rollback retained | Release-environment source guard |
| --- | --- | --- | --- |
| Web Chat | `PUBLIC_WEB_CHAT_RESPONSE_ENGINE=v2` | `PUBLIC_WEB_CHAT_RESPONSE_ENGINE=v1` reaches `brain.get_ai_response` compatibility behaviour. | Requires V2 in verification/staging/production. |
| QR | `WHATSAPP_RESPONSE_ENGINE=v2` | `WHATSAPP_RESPONSE_ENGINE=v1` retains `/chat` V1 behaviour. | Requires V2 in verification/staging/production. |
| Meta | `WHATSAPP_RESPONSE_ENGINE=v2`; `ENABLE_META_WEBHOOK=false` default | Same WhatsApp V1 selector; Meta remains feature-disabled until enabled. | Requires V2 when release configuration starts; Meta credentials are separately required when enabled. |
| External API | `EXTERNAL_API_RESPONSE_ENGINE=v2` | `EXTERNAL_API_RESPONSE_ENGINE=v1` retains its `get_ai_response` branch. | Requires V2 in verification/staging/production. |

No V1 code, flag, test, or route was removed. The broad test fixture sets all three selectors to V1 by default, so rollback regression remains available but aggregate suite results must not be presented as exclusively V2 coverage.

V1 retirement is **not authorised** by this decision. Evidence required before proposing it includes dedicated V2 coverage for each adapter, Node control-route security proof, live QR and Meta delivery proof, an explicit External API delivery-lifecycle contract, and an approved rollback/observability plan.

## Test and evidence interpretation

| Evidence | Establishes | Does not establish |
| --- | --- | --- |
| Phase 1 clean-install record: backend `1,940 passed`, frontend `47/47` | Local source build/test suites passed then. | Live provider, Meta, QR device, External API caller, proxy, PostgreSQL, or deployment behaviour. |
| Dedicated V2 source tests listed per channel | Targeted code coverage for planning, atomic persistence, claims, QR/Meta delivery logic, and signature handling. | That all tests ran in Phase 2 or that real transport/providers act identically. |
| Current static trace at `4b48…dcd69` | Ordinary accepted V2 paths converge on the two named authorities. | Runtime config selection, secret correctness, or rollout. |
| Phase 2 verification | Required reports read; stated HEAD confirmed; source, tests, flags, and delivery boundaries traced; documentation scope checked. | Behaviour test run, browser/device/provider demonstration, or penetration test. |

## Status, deliberately separated

- **Implemented:** YES — this decision record, call graph, comparison table, four path maps, rollback inventory, and QR risk reconciliation. No product implementation changed.
- **Tested:** SOURCE-REVIEWED ONLY — Phase 2 did not run behavioural tests, alter runtime state, or contact external systems. Historic Phase 1 test results and the targeted inventory are cited with their V1-fixture limitation.
- **Demonstrated:** NO — no live Web browser, QR device, Meta provider, or External API client delivery was demonstrated in this phase.
- **Production-ready:** NO — QR route proof, QR direct-fallback persistence, Meta external validation, External API delivery semantics, and deployment/operating controls remain outside scope.
- **Market evidence:** EXTERNAL EVIDENCE REQUIRED — no interview, pilot usage, payment, retention, conversion, or outcome claim was collected or inferred.

## Phase boundary and rollback

Only this report and its documentation-index entry are uncommitted Phase 2 analysis changes. The inspected product rollback checkpoint remains `4b48b2ec2408fe60704e6768ed3ec1a8432dcd69`, as recorded by Phase 1 completion. Reverting these two documentation changes returns the repository to that checkpoint; no session, database, log, artifact, V1, or V2 data should be deleted. Restoration was not performed or tested because it would remove the requested Phase 2 evidence.

**Stop condition:** Phase 2 ends with this canonical-path decision. No Phase 3 work was started.
