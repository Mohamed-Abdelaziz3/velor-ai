# ADR-0002: Keep a bounded modular monolith

- Status: Accepted
- Date: 2026-07-22
- Scope: Backend application structure

## Context

The FastAPI application contains tightly related conversation, evidence, persistence, delivery, and owner-workspace behavior. A broad directory rewrite or premature service split would increase transaction, tenant-context, and operational risk. At the same time, repeated route-level orchestration obscured the canonical V2 boundary.

## Decision

Keep one Python deployable and improve boundaries incrementally around concrete capabilities. Route/webhook modules own transport validation and adapters; application services own orchestration; focused services own decision, persistence, evidence, and delivery transitions. The first extracted application use case is `execute_v2_turn`.

The Node QR gateway remains an optional channel adapter, not a general microservice decomposition strategy.

## Consequences

- Atomic database work and tenant context stay in-process.
- Changes remain reviewable and reversible.
- Existing large modules and compatibility code are acknowledged debt, not silently declared modular.
- A new module must represent a real responsibility; empty domain/application/repository folder structures are not part of this decision.

## Evidence in the current code

- `backend/services/v2_turn_use_case.py`
- `backend/services/velor_chat_v2.py`
- `backend/services/public_chat_turn_service.py`
- `backend/services/message_delivery.py`
- Existing call sites in `backend/main.py` and `backend/routers/webhook.py`

## Not decided

This ADR does not authorize microservices, Kafka, a big-bang refactor, mass file moves, or removal of compatibility modules.
