# VELOR Phase 5 — Authentication and Tenant Isolation

Date: 2026-07-22
Baseline: `3c40a9fa5450a3bec5a5785e39e64f50b597d3b5` (Phase 4 rollback checkpoint)
Scope: identity resolution, authorization, and tenant boundaries on the active V2 conversation and delivery paths.

## Scope contract

Allowed files were authentication helpers, the internal delivery-ACK tenant boundary, V2-adjacent background workers and customer-memory queries, focused security tests, and this report. V1 modules, the QR gateway, UI, Meta onboarding, billing, migrations, delivery redesign, and broad refactoring were explicitly out of scope. The only permitted behavior change was stricter rejection of malformed or cross-tenant identity and record access.

## Trace and threat model

| Path | Identity / tenant source | Boundary checked | Residual note |
|---|---|---|---|
| Web Chat | HttpOnly access JWT; company loaded from the signed claim and database | `_get_current_user` and `_resolve_company_id`; repository queries use resolved company | Super-admin cross-tenant query access is intentional and role-controlled by the database role. |
| QR | Internal gateway secret plus `X-Company-ID` at the V2 route; gateway control routes retain Phase 3A middleware | V2 resolves the company before persistence; ACK now requires and filters by `company_id` | Gateway code was not changed in Phase 5. |
| Meta | Verified webhook/provider mapping resolves a company before V2 selection | V2 receives the resolved company and persists company-scoped records | Live Meta onboarding was not demonstrated. |
| External API | API key hash resolves the company; no client tenant ID is trusted | V2 persistence and delivery ACK are keyed by the API-key company | Delivery ACK remains a provider acknowledgment, not a broad delivery redesign. |
| Background work | Explicit `company_id` and `lead_id` arguments | Lead, memory, activity, analytics, and intelligence lookups now join/filter through the same company | Legacy V1 memory/scoring workers remain outside this phase. |
| Admin/internal | Internal secret or authenticated user dependency, depending on endpoint | Secret checks and company-scoped queries are enforced before access | No secret values are logged or included here. |

High-risk QR control routes remain explicitly protected by the Phase 3A gateway middleware; this phase did not weaken or redesign that boundary.

## Findings addressed

1. Both JWT helpers accepted any truthy `company_id` shape and did not check an optional conflicting `sub` claim. They now require a bounded tenant identifier and reject a mismatched subject while preserving tokens that predate the standardized subject claim.
2. Internal WhatsApp ACK accepted an omitted company identifier and conditionally scoped the lookup. `company_id` is now required, validated, and always part of both internal-ID and provider-ID lookups.
3. V2-adjacent analytics, intelligence, and customer-preference memory queries could use a globally unique lead ID without reasserting the lead's company. Reads and writes now join through `Lead` and enforce company and non-deleted boundaries.
4. `engine.analytics_worker` had a stale import from a non-existent V1 helper. A local provider-JSON parser keeps the worker importable without importing V1 `brain.py`.

## Implemented

- Hardened `backend/main.py` and `backend/routers/auth.py` identity claim validation.
- Required and company-scoped internal QR delivery ACKs in `backend/main.py`.
- Added tenant joins/guards to `backend/engine/analytics_worker.py`, `backend/workers/intelligence_worker.py`, and V2 `backend/services/customer_memory_service.py`.
- Added focused tests covering malformed identity, cross-tenant conversation/catalog/policy access, delivery ACK isolation, internal-secret enforcement, background context, and V2 memory isolation.
- Preserved V1 modules and the Phase 4 delivery model unchanged.

## Tested

Commands and results:

- `python -m pytest -q tests/test_phase5_auth_tenant_isolation.py` → **5 passed**.
- `python -m pytest -q tests/test_api.py tests/test_catalog_import_routes.py tests/test_knowledge_source_security.py tests/test_phase4_delivery_reliability.py tests/test_phase4_backend_critical_slice.py tests/test_whatsapp_v2_runtime.py tests/test_auto_reply_control.py` → **57 passed**.
- `python -m pytest -q` (backend) → **1949 passed, 167 warnings**.
- `node --test tests/whatsapp_gate_auth.test.js` → **2 passed**.
- `node --check whatsapp_gate.js` → passed.
- `python -m py_compile main.py routers/auth.py engine/analytics_worker.py workers/intelligence_worker.py services/customer_memory_service.py tests/test_phase5_auth_tenant_isolation.py` → passed.
- `git diff --check` → passed.

The test runtime used the repository's locked `.venv` site-packages with the bundled Python executable; no network install was performed.

## Demonstrated

The automated evidence demonstrates authenticated tenant-only access, rejection of malformed/conflicting JWT identity, rejection of cross-tenant conversation and knowledge records, delivery/retry isolation, internal ACK secret and tenant requirements, and preservation of tenant context in the tested background workers. QR authentication behavior remains covered by the existing Phase 3A Node tests.

## Production-ready

Not claimed. This phase provides tested hardening, not a production certification. Live provider identity configuration, deployment secrets, operational monitoring, and Meta production verification remain deployment responsibilities.

## Market evidence

None produced by this engineering phase. No customer, revenue, conversion, or market-performance claim is implied.

## Residual risks and rollback

- `backend/engine/memory.py`, `backend/engine/scorer.py`, and `backend/brain.py` retain legacy/V1 lead-ID-only behavior and were deliberately not modified because V1 was explicitly out of scope. They must remain a follow-up security decision before any V1 retirement or reactivation.
- Super-admin access is intentionally broader and remains controlled by the database role, not by a client-supplied role claim.
- Live Meta and production QR deployment were not demonstrated.

Rollback is the unchanged Phase 4 checkpoint `3c40a9fa5450a3bec5a5785e39e64f50b597d3b5`. Reverting the single Phase 5 commit restores the prior code without deleting sessions, databases, logs, or user data.
