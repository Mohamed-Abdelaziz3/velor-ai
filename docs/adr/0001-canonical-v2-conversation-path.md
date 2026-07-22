# ADR-0001: Use V2 as the canonical conversation path

- Status: Accepted
- Date: 2026-07-22
- Scope: Web Chat, QR, Meta, and External API automated conversations

## Context

VELOR retained V1 compatibility while a bounded V2 engine introduced evidence-aware planning, generation, validation, escalation, and atomic persistence. Selecting a path by route history or by the label “V2” would be unsafe; the decision required shared call-path evidence and explicit rollback controls.

## Decision

V2 is the default and release-required automated conversation path for all four ingress adapters. Routes authenticate, resolve the tenant, validate requests, and claim inbound messages before calling `execute_v2_turn`. That use case composes `get_v2_ai_response` with `persist_v2_public_turn_atomic`.

V1 remains reachable only through explicit `v1` engine selectors for rollback and regression coverage. Release configuration validation rejects V1 selectors.

## Consequences

- One decision/persistence authority serves the four channels.
- Channel identity, timeout, delivery, and response contracts remain adapter-specific.
- V1 cannot be retired solely because V2 is canonical; retirement needs separate evidence and authorization.
- Aggregate tests that force V1 are not evidence of exclusive V2 coverage.

## Evidence in the current code

- `backend/main.py`: public Web Chat and `/chat` engine selection and release guards.
- `backend/routers/webhook.py`: Meta V2 selection.
- `backend/services/conversation_engine_config.py`: QR/External defaults.
- `backend/services/v2_turn_use_case.py`: shared application boundary.
- `backend/.env.example`: V2 selectors and disabled Meta default.

## Not decided

This ADR does not delete V1, enable Meta, certify live providers, or change any API contract.
