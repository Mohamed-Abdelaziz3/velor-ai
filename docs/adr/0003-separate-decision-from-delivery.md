# ADR-0003: Separate conversation decision from delivery

- Status: Accepted
- Date: 2026-07-22
- Scope: Active V2 turn lifecycle

## Context

A valid AI response is not proof that the customer received it. Provider calls can fail after a decision is persisted, and retrying the entire decision risks duplicate messages or divergent canonical state.

## Decision

Treat decision, atomic turn persistence, and channel delivery as distinct lifecycle steps. V2 decides and validates the response. The persistence boundary stores the canonical turn and delivery intent. The adapter then returns or sends the response and applies ACK/provider statuses independently.

Web HTTP completion is the current sent boundary. QR, Meta, and External API start with a pending outgoing record and require their channel-specific transition.

## Consequences

- A V2 decision is never reported as provider-delivered before confirmation.
- Provider failure changes delivery evidence, not the conversation decision.
- Duplicate inbound IDs reuse the linked response instead of regenerating it.
- Channel adapters retain different acknowledgement semantics without creating different decision engines.

## Evidence in the current code

- `backend/services/v2_turn_use_case.py`
- `backend/services/public_chat_turn_service.py`
- `backend/services/message_delivery.py`
- `backend/services/delivery_reliability.py`
- Delivery branches in `backend/main.py` and `backend/routers/webhook.py`

## Not decided

This ADR does not claim exactly-once provider delivery, deploy a new outbox service, or redesign Meta/QR transports.
