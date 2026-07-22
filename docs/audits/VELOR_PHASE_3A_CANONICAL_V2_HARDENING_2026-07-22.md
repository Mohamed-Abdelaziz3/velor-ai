# VELOR Phase 3A — Canonical V2 Hardening

**Date:** 2026-07-22
**Pre-edit source baseline required by the phase:** `4b48b2ec2408fe60704e6768ed3ec1a8432dcd69`
**Pre-edit checkpoint created:** `8e6ccaec5d235cc90f57679891bbf76e929bb3aa` (`docs: record Phase 2 canonical path decision`)
**Phase status:** Complete. This is a narrow QR gateway hardening change; it does not refactor the product, alter V1, migrate data, or redesign delivery.

## Inputs read first

- [Phase 0 discovery/security baseline](VELOR_PHASE_0_DISCOVERY_SECURITY_BASELINE_2026-07-22.md)
- [Phase 1 setup/hygiene report](VELOR_PHASE_1_REPRODUCIBLE_SETUP_PUBLIC_REPOSITORY_HYGIENE_2026-07-22.md)
- [Phase 1 completion report](VELOR_PHASE_1_COMPLETION_GIT_INITIALIZATION_2026-07-22.md)
- [Phase 2 canonical-path decision](VELOR_PHASE_2_CANONICAL_CONVERSATION_PATH_DECISION_2026-07-22.md)

## Scope contract

Allowed changes were QR gateway authentication behaviour/tests, the QR-to-V2
routing and persistence boundary, narrowly related tests, and this focused
report. No V1 code or selector changed. No database migration, UI, Meta
integration, External API delivery redesign, directory rewrite, session/data
deletion, or Phase 4 work occurred.

## Implemented hardening

### 1. QR control routes: one tested authentication boundary

`backend/whatsapp_gate.js` already installs
`app.use('/api/whatsapp', requireInternalSecret)` immediately before the QR
control routes. Phase 3A makes its runtime behaviour demonstrable with a Node
HTTP test rather than treating static Express prefix semantics as proof.

| Route | Unauthorized result proved | Authorized result proved | Route result used in test |
| --- | --- | --- | --- |
| `GET /api/whatsapp/stream/:company_id` | `401` | `200`, SSE content type | Stream opens and returns current state. |
| `GET /api/whatsapp/status/:company_id` | `401` | `200` | Connected status is returned. |
| `POST /api/whatsapp/start/:company_id` | `401` | `200` | Existing, validated gateway session returns `already_running`. |
| `POST /api/whatsapp/send/:company_id` | `401` | `200` | A controlled fake session sends and the internal ACK is accepted. |

The new `backend/tests/whatsapp_gate_auth.test.js` starts the Express app on a
loopback ephemeral port, provides a loopback fake FastAPI responder only for
the company-validation and ACK calls, and uses a test-only in-memory socket.
It never reads or sends through a real QR session or external service. The
test sets a synthetic process-only secret and asserts the same `[401, 401, 401,
401]` and `[200, 200, 200, 200]` status sequences across the four routes.

To make that behavioural test possible without starting a real gateway at
module import, the gateway now exports its Express app/state and starts its
listener/signal handlers only when executed as its main module. Running
`node whatsapp_gate.js` retains the existing listening and auto-boot behaviour.

### 2. QR customer-reply boundary: V2 stays authoritative

Phase 2 identified two gateway-local automatic reply paths that bypassed V2
persistence: the over-800-character response and the early backend-failure
technical response. Both direct `sock.sendMessage` branches were removed.

- A long inbound text is now logged by size and forwarded to `/chat`; it is no
  longer answered locally. For accepted V2 input, the normal V2 processing
  claim, response decision, and atomic persistence execute before delivery.
- If the backend fails before it returns a reply, the gateway records an
  in-memory `backend_unavailable_no_local_reply` delivery attempt and sends no
  customer text. This deliberately contains the failure rather than creating
  an unpersisted answer or a second decision authority.
- If the backend did return a persisted reply but Baileys send fails, the
  existing duplicate-suppression behaviour remains: no local fallback is sent.
- The remaining gateway `sock.sendMessage` call is inside `sendAndAck`, the
  delivery adapter used only after a backend response is returned. It then
  posts the internal message/provider-id acknowledgement to FastAPI.

This does not invent an outage-reply persistence design. A request rejected by
the backend (including an input beyond backend validation) now receives no
gateway-local automatic response; recovery remains a caller retry or future
authorised delivery/recovery work. That is the safe contained behaviour within
this phase's scope.

### 3. Canonical V2 selection is unchanged

Source inspection after the edit confirms the existing selectors remain the
authority:

| Channel | Selector/default | Canonical V2 path preserved |
| --- | --- | --- |
| Web Chat | `PUBLIC_WEB_CHAT_RESPONSE_ENGINE=v2` | public route uses `get_v2_ai_response` then `persist_v2_public_turn_atomic`. |
| QR | `WHATSAPP_RESPONSE_ENGINE=v2` | `/chat` selects `_chat_v2`; the gateway only sends its returned persisted reply. |
| Meta | `WHATSAPP_RESPONSE_ENGINE=v2` | webhook worker remains unchanged and calls the same V2 decision/persistence functions. |
| External API | `EXTERNAL_API_RESPONSE_ENGINE=v2` | API-key `/chat` requests remain on `_chat_v2`. |

V1 feature flags and implementation were not changed and remain explicit
rollback paths.

### 4. External API delivery-ACK gap — documented, not redesigned

External API V2 persists an outbound row as `pending` and returns the reply in
the synchronous HTTP response. This repository has no caller ACK endpoint or
delivery-receipt protocol; the generic scheduler can mark stale pending rows
failed. Phase 3A changes neither state nor schema nor delivery architecture.
The gap remains a future explicit contract/outbox decision and is not evidence
of customer delivery.

## Verification

All commands below were run from the stated repository/working directory using
the bundled runtimes recorded by Phase 1. No real credentials were supplied.

| Command | Result |
| --- | --- |
| `<LOCAL_RUNTIME_EXECUTABLE> --check whatsapp_gate.js` from `backend` | PASS — gateway syntax valid. |
| `<LOCAL_RUNTIME_EXECUTABLE> --test --test-reporter=tap tests/whatsapp_gate_auth.test.js` from `backend` | PASS — 2 tests, 0 failures; each of stream/status/start/send rejected unauthorized requests and accepted authorized requests. |
| `PYTHONPATH=<repo>\.venv\Lib\site-packages <LOCAL_RUNTIME_EXECUTABLE> -m pytest -q --junitxml=<temp>\velor-phase3a-backend\pytest.junit.xml` from `backend` | PASS — 1,940 tests, 0 failures, 0 errors, 0 skipped; JUnit duration 237.906 seconds. |
| `<LOCAL_RUNTIME_EXECUTABLE> --test tests/vite-proxy-config.test.mjs tests/ui-contracts.test.mjs tests/settings-contracts.test.mjs tests/workspace-contracts.test.mjs tests/analytics-contracts.test.mjs tests/landing-page-contract.test.mjs` from `frontend` | PASS — 47 tests, 0 failures. |
| Static route/selector trace and `git diff --check` | PASS — all four QR routes remain below the same `/api/whatsapp` middleware; Web/QR/Meta/External V2 selectors remain present; no whitespace errors. |

There is no configured gateway linter in `backend/package.json`; the available
gateway syntax check was run. The behavioural test is the new gateway-specific
quality gate.

## Limits and follow-up boundary

- The new test proves local loopback Express authentication behaviour, not a
  reverse proxy, tunnel, network policy, or real QR device.
- QR delivery still has no durable outbox; Phase 3A did not add one.
- Meta remains disabled by default and unchanged.
- External API acknowledgement semantics remain unresolved as documented above.
- V1 remains intact for rollback.

## Status, deliberately separated

- **Implemented:** YES — QR control-route authentication is behaviourally
  tested; QR long-message and early-backend-failure local reply bypasses are
  removed/contained; testable gateway startup boundary is added.
- **Tested:** YES — new Node behavioural tests, gateway syntax, full backend
  suite, and frontend suite passed as recorded.
- **Demonstrated:** YES, locally — loopback HTTP tests demonstrate consistent
  authorized/unauthorized handling across all four QR control routes. No real
  device, external provider, or proxy was demonstrated.
- **Production-ready:** NO — no deployed proxy/device proof, no QR outbox, no
  External API delivery ACK contract, and other launch/operating controls are
  outside this phase.
- **Market evidence:** EXTERNAL EVIDENCE REQUIRED — no customer, payment,
  retention, conversion, or market result was collected or inferred.

## Rollback

The pre-edit documentation checkpoint is `8e6ccaec5d235cc90f57679891bbf76e929bb3aa`.
The focused Phase 3A commit can be reverted to return to that checkpoint. No
sessions, databases, logs, or user data were deleted, moved, or used as
rollback inputs.

**Stop condition:** Phase 3A ends with this focused hardening report and its
commit. No Phase 4 work was started.
