# VELOR Phase 3B — Bounded Modular Monolith Refactor

Date: 2026-07-22
Baseline / rollback checkpoint: `2c689b630aad147daf0e3aee03b19466700cb645` (`test: harden QR gateway V2 boundary`)

## Scope contract

This phase changes one capability only: accepting an already-claimed inbound V2 turn through the canonical decision and atomic-persistence boundary.

Allowed files/modules:

- `backend/services/v2_turn_use_case.py` — the new application-level use case;
- the existing V2 call sites in `backend/main.py` and `backend/routers/webhook.py`;
- one focused application-boundary test;
- this phase report and the documentation index.

Expected changes were limited to replacing duplicated V2 decision-plus-persistence wiring with the use case. Route validation, tenant resolution, claims, timeout policy, channel adapters, delivery, and late auto-reply guards remain in their existing callers.

Explicitly out of scope: V1 (`backend/brain.py` and V1 callers), QR gateway authentication, provider behavior, selectors, UI, Meta ingress behavior, database/schema/migrations, outbox or delivery acknowledgements, billing, mass moves/renames, and Phase 4 work.

Allowed behavior change: none to the external contract; only the internal call boundary changed. Prohibited behavior changes included changing the selected engine, provider/fallback policy, claim semantics, response envelope, persistence transaction, delivery status, or guard behavior.

Verification commands were defined as the focused boundary tests, existing QR gateway tests and syntax check, the backend suite, `git diff --check`, selector checks for Web/QR/Meta/External API, and a V1 diff check. The baseline commit above is the exact rollback checkpoint; no user data, sessions, databases, logs, or generated artifacts are deleted.

## Trace before extraction

The Phase 2 canonical path and Phase 3A hardening leave four entry paths selecting V2:

| Path | Entry and route-owned work | Previously duplicated application work | Delivery / response |
| --- | --- | --- | --- |
| Web Chat | `public_chat_send` validates the request, resolves tenant/lead, claims the inbound message, and applies timeout/late-guard policy. | Calls `get_v2_ai_response`, maps its trace, and calls `persist_v2_public_turn_atomic`. | HTTP response from `public_chat_send`. |
| QR | `_chat_v2` validates gateway/API credentials and tenant, claims the inbound message, and owns timeout policy. | Calls `get_v2_ai_response`, maps its trace, and calls `persist_v2_public_turn_atomic`. | QR gateway / HTTP response from `/chat`. |
| Meta | `_process_meta_message_v2` receives the provider webhook, resolves/claims the tenant conversation, and handles cached-reply and skip branches. | Calls `get_v2_ai_response`, maps its trace, and calls `persist_v2_public_turn_atomic`. | Meta adapter dispatches the answer after persistence. |
| External API | `/chat` authenticates the API key, resolves tenant and channel, and reuses `_chat_v2` for the claimed turn. | Same `_chat_v2` V2 decision/persistence sequence as QR. | External API response with pending delivery status. |

In every path, the decision authority was `services.velor_chat_v2.get_v2_ai_response` and the write authority was `services.public_chat_turn_service.persist_v2_public_turn_atomic`; the risk was duplicated orchestration around those authorities.

## Smallest safe extraction

`backend/services/v2_turn_use_case.py::execute_v2_turn` is the single application boundary. It accepts the already-resolved company, lead, source message, claim identifiers, channel metadata, and delivery telemetry; calls the existing V2 engine; maps its trace; and invokes the existing atomic V2 persistence service. It returns the engine result, trace, response envelope, and persistence result to the caller.

The service imports the two existing service modules rather than copying or re-exporting functions. Existing monkeypatch seams therefore remain valid. It does not own authentication, tenant resolution, claims, retries, timeout/cancellation, delivery, or late guards.

## Trace after extraction

```text
route/webhook validation + tenant/claim ownership
    -> execute_v2_turn (application use case)
        -> velor_chat_v2.get_v2_ai_response (decision, validation, fallback)
        -> public_chat_turn_service.persist_v2_public_turn_atomic (canonical transaction)
    -> existing caller guard / provider adapter / HTTP response
```

The same use case is used by Web Chat, QR/External API through `_chat_v2`, and Meta. V2 remains the only active decision and persistence path selected by the existing flags. No V1 code was changed.

## Files changed

- `backend/services/v2_turn_use_case.py`
- `backend/main.py`
- `backend/routers/webhook.py`
- `backend/tests/test_v2_turn_use_case.py`
- `docs/README.md`
- this report

No QR gateway file, V1 file, schema, migration, UI, or provider adapter was changed.

## Verification evidence

Commands and results for this phase:

- `python -m pytest -q tests/test_v2_turn_use_case.py tests/test_public_chat_atomic_turn.py tests/test_whatsapp_v2_runtime.py tests/test_webhook_processing_claim.py` — **57 passed**, 1 existing deprecation warning.
- `node --check whatsapp_gate.js` — passed.
- `node --test --test-reporter=tap tests/whatsapp_gate_auth.test.js` — **2 passed**, 0 failed.
- Full backend pytest suite: `python -m pytest -q` — **1941 passed**, 161 existing warnings, 0 failed, in 240.79 seconds.
- `git diff --check` — passed before final staging; rerun before commit.

Selector checks and the V1 unchanged check are recorded below. Frontend tests are not required because no frontend file is affected.

Selector evidence:

- Web Chat: `backend/main.py:1863` has `get_public_web_chat_engine() == "v2"`.
- QR / External API route: `backend/main.py:2776` has `selected_engine == "v2"`.
- Meta: `backend/routers/webhook.py:837` has `get_whatsapp_response_engine() == "v2"` (with the existing delivery guard at line 1024).
- Existing V2 release guards remain in `backend/main.py` for public web, WhatsApp, and External API; no selector was changed.

V1 evidence: `git diff --name-only` contains no `backend/brain.py` or V1 module, and the QR gateway source is unchanged. `git diff --check` is clean.

## Status classification

### Implemented

One bounded application-level use case now owns the repeated V2 incoming-turn decision-to-atomic-persistence sequence. Existing route, adapter, repository/service, selector, and guard responsibilities remain in place.

### Tested

The focused boundary test proves the use case forwards channel/route/claim metadata to the existing decision and persistence seams. The completion run must include the QR and full backend suites.

### Demonstrated

The call graph demonstrates one shared V2 application boundary for Web Chat, QR, External API, and Meta while preserving the existing V2 authorities and delivery branches.

### Production-ready

Not claimed. This is a bounded refactor with regression evidence; it is not a production-readiness or launch approval.

### Market evidence

None produced by this engineering phase. No customer, revenue, adoption, or market outcome is inferred.

## Rollback

Before editing, the worktree was clean at `2c689b630aad147daf0e3aee03b19466700cb645`. To roll back this phase, restore that checkpoint (or revert the focused Phase 3B commit once created). The Phase 3A checkpoint remains the parent, and V1 remains available as the earlier rollback path. No runtime data was removed.
