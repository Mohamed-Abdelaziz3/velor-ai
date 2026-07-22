# ADR-0005: Derive tenant context from authenticated boundaries

- Status: Accepted
- Date: 2026-07-22
- Scope: Active V2 conversation, knowledge, and delivery paths

## Context

Client-controlled tenant identifiers can produce cross-tenant reads or mutations when a stronger authenticated identity is already available. VELOR supports multiple ingress types, so one credential format cannot serve every adapter.

## Decision

Resolve tenant context from the strongest verified boundary:

- owner JWT claim plus database company lookup for owner routes;
- stored API-key hash for External API;
- internal secret plus validated company context for QR;
- verified Meta signature and provider mapping for Meta;
- explicit `company_id` carried into tenant-scoped background work.

Repository and service queries on the active path must include the resolved company boundary. A conflicting client tenant selector is rejected except for intentional role-controlled super-admin access.

## Consequences

- External API clients cannot select a different tenant with payload data.
- Delivery ACK, catalog/policy, conversation, evidence, and V2 memory checks remain tenant-scoped.
- Background jobs must preserve company context explicitly.
- Legacy helpers are not automatically approved for reactivation merely because active V2 paths are hardened.

## Evidence in the current code

- Authentication helpers in `backend/main.py` and `backend/routers/auth.py`
- Tenant guards in `backend/services/customer_memory_service.py`
- Background guards in `backend/engine/analytics_worker.py` and `backend/workers/intelligence_worker.py`
- `backend/tests/test_phase5_auth_tenant_isolation.py`

## Not decided

This ADR does not redesign roles, remove super-admin access, implement tenant provisioning, or certify external identity-provider configuration.
