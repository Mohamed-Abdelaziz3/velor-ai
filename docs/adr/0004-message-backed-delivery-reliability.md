# ADR-0004: Use the outgoing Message as durable delivery intent

- Status: Accepted
- Date: 2026-07-22
- Scope: V2 outbound delivery reliability

## Context

The current schema already persists outgoing messages, delivery status, message events, provider identifiers, and canonical reply linkage. A separate outbox table or infrastructure layer was not required to close the bounded External API acknowledgement and failure-observability gaps.

## Decision

Use the outgoing `Message` row and its events as an outbox-like durable intent. Apply delivery updates through `apply_message_delivery_update`, with idempotent and monotonic state rules. Record bounded failure reason/source evidence. Expose an API-key-authenticated External API ACK endpoint scoped to the API-key tenant and canonical External API messages.

The stale-pending sweeper targets outgoing pending records, uses a conditional transition, and records the timeout reason.

## Consequences

- Pending, sent, delivered/read, failed, and cancellation semantics are explicit in the existing persistence model.
- Duplicate ACKs are harmless; delivered truth cannot regress to failed.
- A legitimate retry can recover a failed message without regenerating the V2 response.
- Operational recovery still depends on running the scheduler and monitoring failures.

## Evidence in the current code

- `backend/database.py::fail_pending_messages`
- `backend/services/message_delivery.py`
- `backend/services/delivery_reliability.py`
- `backend/services/public_chat_turn_service.py`
- `backend/tests/test_phase4_delivery_reliability.py`

## Not decided

This ADR does not introduce Kafka, a standalone outbox, a new database, or a universal provider-delivery guarantee.
