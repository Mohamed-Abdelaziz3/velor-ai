# VELOR Phase 4 — Outbox and Delivery Reliability

Date: 2026-07-22

Baseline / rollback checkpoint: `6b5b48b7a0dd450781ecad3b575d354277d41596` (`refactor: isolate canonical V2 turn use case`)

Focused commit: recorded after verification below.

## Scope contract

This phase covers only the bounded delivery-reliability layer around the active V2 path: durable delivery intent, External API delivery acknowledgement, idempotent status transitions, bounded retry/recovery semantics, explicit `pending`/`sent`/`failed` states, and provider-failure observability.

Allowed files/modules:

- `backend/services/message_delivery.py` — shared monotonic delivery transition authority;
- `backend/services/delivery_reliability.py` — External API ACK contract and bounded delivery helper;
- the V2 atomic outbound event in `backend/services/public_chat_turn_service.py`;
- `backend/main.py` — External API ACK route and response contract, plus existing ACK failure metadata;
- `backend/database.py` — existing pending sweeper, restricted to outgoing rows and documented failure reasons;
- the existing Meta delivery update seam in `backend/routers/webhook.py`;
- focused Phase 4 tests, this report, and the documentation index.

Expected changes were limited to reusing the existing outbound `Message` row as the durable delivery intent, tagging its canonical V2 event with channel metadata, exposing an authenticated External API ACK endpoint, making failure transitions reasoned and observable, and proving retry/idempotency behavior.

Out of scope: microservices, Kafka, new infrastructure, UI, Meta onboarding, QR authentication or gateway behavior, V1, broad schema redesign, database migration, outbox replacement, and Phase 5.

Risks were limited to shared delivery-state semantics: a provider failure could regress a delivered row, a cross-tenant ACK could mutate another tenant, or the stale sweeper could hide the reason for failure. The implementation addresses these with compare-and-set transitions, tenant/API-key scoping, monotonic state rules, an explicit channel marker, and durable `delivery.failed` events.

## Current flow traced before editing

```text
V2 decision
  -> persist_v2_public_turn_atomic
       -> outgoing Message row
          delivery_status = pending for QR / Meta / External API
          delivery_status = sent for Web HTTP delivery boundary
       -> MessageEvent + SystemEvent
  -> channel delivery adapter
       QR: Baileys sendAndAck -> /api/whatsapp/webhook/ack
       Meta: Graph send -> provider status webhook
       External API: synchronous response, no caller ACK contract
  -> generic fail_pending_messages after five minutes
```

Existing `Message.delivery_status` and `MessageEvent` already formed a durable outbox-like intent. `services.message_delivery.apply_message_delivery_update` already supplied monotonic compare-and-set transitions and provider-id collision protection. The unresolved gap was External API caller acknowledgement, and the stale sweeper changed `pending` to `failed` without a durable reason. No separate outbox table or migration was justified for this bounded fix.

## Implemented reliability boundary

### Durable intent and explicit state

The V2 atomic persistence path still creates one linked outgoing `Message` row before provider delivery for QR, Meta, and External API. Its event payload now includes the channel (`EXTERNAL_API`, `WHATSAPP_QR`, `WHATSAPP_META`, or `VELOR_WEB_CHAT`) so a caller ACK can be scoped to a canonical V2 intent without guessing from message order. The initial External API response explicitly returns `delivery_status: "pending"` and an ACK contract; it is never reported as delivered by the decision path.

### External API acknowledgement

`POST /api/external/delivery/ack` is authenticated with the tenant's `X-API-Key`. It accepts `internal_message_id`, `status` (`sent`, `delivered`, or `failed`), an optional bounded `failure_reason`, and an optional timestamp. The endpoint only accepts an outgoing assistant row whose canonical creation event is tagged `EXTERNAL_API`; missing or cross-tenant rows do not mutate state.

The V2 `/chat` response advertises:

```json
{
  "delivery_status": "pending",
  "delivery_ack": {
    "endpoint": "/api/external/delivery/ack",
    "method": "POST",
    "statuses": ["sent", "delivered", "failed"],
    "initial_status": "pending"
  }
}
```

### Idempotency and retry

ACKs reuse the existing monotonic state machine: duplicate ACKs are no-ops, `delivered`/`read` truth cannot regress to `failed`, and a failed message may recover to `sent` or `delivered` on a legitimate retry. Repeating `/chat` with the same `external_message_id` reuses the linked response instead of running V2 again; the response exposes `redeliver_existing_reply` and the current delivery state. This is the bounded retry contract—no second decision and no duplicate outbound row.

### Provider failure and stale recovery

Every transition to `failed` now records a bounded reason and source in both the `message.updated` payload and a durable `delivery.failed` `SystemEvent`. The QR ACK and Meta delivery seams supply provider sources; External API ACKs supply `external_api_ack`; takeover delivery supplies `takeover_delivery`.

The pending sweeper now targets outgoing rows only, uses a conditional `pending` update so a concurrent ACK wins, and records `stale_pending_timeout:<minutes>m` with source `pending_sweeper`. Re-running the sweep does not create another transition. Conversation, lead, commercial, claim, and analytics state is not rewritten by a provider failure; only delivery state and its operational evidence change.

## Verification evidence

Commands and results:

- `python -m pytest -q tests/test_phase4_delivery_reliability.py tests/test_whatsapp_v2_runtime.py tests/test_webhook_processing_claim.py tests/test_webhook_retry_idempotency.py tests/test_auto_reply_control.py` — **76 passed**, 5 existing warnings.
- `python -m pytest -q tests/test_phase4_delivery_reliability.py` — **3 passed**, 1 existing warning.
- `python -m pytest -q` from `backend` — **1944 passed**, 161 existing warnings, 0 failed, in 241.05 seconds.
- `node --check whatsapp_gate.js` — passed.
- `node --test --test-reporter=tap tests/whatsapp_gate_auth.test.js` — **2 passed**, 0 failed.
- `python -m py_compile backend/main.py backend/database.py backend/services/message_delivery.py backend/services/delivery_reliability.py backend/services/public_chat_turn_service.py backend/tests/test_phase4_delivery_reliability.py` — passed.
- `git diff --check` — passed before staging and is rerun before commit.

The focused tests prove: unauthenticated External API ACK rejection; durable `pending` intent; authenticated failure ACK with reason; no conversation-state corruption; same-id retry without regeneration; failed-to-sent recovery; duplicate/stale ACK suppression; delivered-state protection; and stale-pending recovery with an explicit reason. QR behavioral authentication remains **2/2** from the existing Phase 3A gate and was not changed.

No migration was necessary. Frontend tests were not run because no frontend file was affected.

## V1 and channel preservation

- V1 implementation and selectors were not changed.
- Web remains the HTTP delivery boundary and retains its existing `sent` semantics.
- QR and Meta continue to persist `pending` before provider delivery and use the existing ACK/status adapters; only failure reason/source observability was added.
- External API now has an explicit caller ACK contract while retaining the same V2 decision and canonical persistence path.

## Status classification

### Implemented

YES — durable V2 delivery intent is explicit, External API ACK is authenticated and channel-scoped, transitions are idempotent/monotonic, retries reuse the canonical reply, and provider/stale failures have durable reasons.

### Tested

YES — focused reliability tests, existing delivery/retry suites, full backend suite, QR tests, Python compile, Node syntax, and `git diff --check` passed.

### Demonstrated

YES, locally with mocked providers and an isolated test database — External API pending/ACK/failure/retry transitions and QR authentication behavior were exercised. No live provider, deployed caller, network proxy, or production retry worker was demonstrated.

### Production-ready

NO — deployment, real provider receipts, operational alerting, retention, and a live External API client contract remain unverified. This phase does not claim launch readiness.

### Market evidence

None produced. No customer, revenue, adoption, retention, or market outcome is inferred.

## Rollback

The exact pre-edit rollback checkpoint is `6b5b48b7a0dd450781ecad3b575d354277d41596`. Reverting the focused Phase 4 commit restores that source state. No sessions, databases, logs, user data, V1 code, or QR gateway files were deleted or moved.

**Stop condition:** Phase 4 ends with this bounded reliability layer and report. No Phase 5 work was started.
