# VELOR Route and Data Contracts

> **Historical snapshot — superseded.** Route ownership and response paths were consolidated after this 2026-07-11 inspection. Do not treat this inventory as the active routing contract. See [`../release/VELOR_LAUNCH_READINESS_AUDIT.md`](../release/VELOR_LAUNCH_READINESS_AUDIT.md).

Audit basis: decorators and call sites in `backend/main.py`, `backend/routers/`, `backend/copilot/router.py`, `frontend/src/App.jsx` and `frontend/src/services/api.js`. No live server was available; fields that depend on runtime serialization are marked **RUNTIME-UNVERIFIED**.

## Backend endpoint inventory

| Method | Path | Module / caller | Auth and scope | Side effect / notes |
|---|---|---|---|---|
| GET | `/health` | `main.health` | public | health payload. |
| POST | `/signup`, `/login`, `/auth/google`, `/token/refresh`, `/logout`, `/token/revoke` | `main.py` | public/cookie as applicable | creates/rotates/revokes token state; cookie auth. |
| GET | `/me` | `main.me` | current owner | company identity. |
| GET/PUT/PATCH | `/whatsapp/settings/alerts` | `main.py` | owner/company | reads/writes alert settings. |
| GET/POST | `/api/company/bot/auto-reply`, `/api/company/bot/web-chat` | `main.py` | `_resolve_company_id` | toggles company controls. |
| POST/GET | `/api/public/companies/{slug}/session` | `main.py` | public visitor JWT after creation | creates/resumes web-chat visitor/lead; returns history. |
| POST | `/api/public/chat` | `main.public_chat_send` | public visitor JWT + tenant | rate limit, inbound claim, message/AI/evidence/projections. Request `message`, `client_message_id`; response status/reply/id. |
| POST | `/api/wizard/generate` | `main.py` | unverified auth from decorator | Groq prompt generation. |
| GET | `/companies-list` | `main.py` | super-admin intent | company list. |
| POST | `/rotate-api-key` | `main.py` | owner | rotates API key. |
| POST | `/api/leads/{phone}/status` | `main.py` | owner/company | legacy lead status update. |
| GET | `/stats`, `/leads`, `/export-leads`, `/api/conversations` | `main.py` | owner/company | legacy dashboard/list/export surfaces. |
| PUT | `/api/company/target` | `main.py` | owner/company | daily target. |
| POST | `/chat` | `main.chat` | internal secret/API-key legacy path | gateway ingress; response calls brain. |
| POST | `/api/ai/suggestions` | `main.py` | owner/company | AI suggestion surface. |
| GET/POST | `/api/engine/priorities`, `/attention`, `/queue`, `/lost`, `/opportunity`, `/tasks/{id}/complete`, `/tasks/{id}/dismiss`, `/override` | `main.py` | owner/company | legacy engine projections/task mutation. |
| GET/POST | `/api/notifications`, `/api/notifications/{id}/read`, `/api/notifications/read-all` | `main.py` | owner/company | notification state. |
| GET | `/stream-stats`, `/api/v1/events/stream` | `main.py`, `routers/stream.py` | owner/company expected | SSE; runtime auth behavior needs live check. |
| GET/POST | `/api/internal/companies/{company_id}/exists`, `/api/whatsapp/webhook/ack` | `main.py` | internal secret | gateway/session validation and delivery ack. |
| GET/POST | `/api/whatsapp/pending/{company_id}`, `/whatsapp/start`, `/whatsapp/status`, `/whatsapp/stream`, `/api/whatsapp/leads/latest` | `main.py` | mixed owner/internal | Baileys management/status. |
| GET/POST | `/api/leads/{id}/timeline`, `/memory`, `/memory/rebuild`, `/human-takeover/toggle` | `main.py` | owner/company | customer projections/memory/takeover. |
| POST | `/api/agent/outbound/send`, `/whatsapp/agent/takeover`, `/whatsapp/agent/toggle-pause` | `main.py` | owner/company | sends/controls outbound transport. |
| GET | `/whatsapp/agent/pause-status` | `main.py` | owner/company | pause state. |
| POST | `/api/v1/copilot/chat`, `/api/v1/copilot/chat/lead/{id}` | `main.py` | owner/company | business/customer Ask VELOR answers. |
| GET/POST | `/api/whatsapp/webhook` | `routers/webhook.py` | Meta verify / feature flag | disabled unless `ENABLE_META_WEBHOOK`; durable inbound claim/delivery. |
| GET/POST/PATCH | `/customers/{id}`, `/customers/{id}/suggested-replies`, `/customers/{id}/toggle-ai`, `/customers/{id}/action`, `/chat/send`, `/leads` | `routers/crm.py` | company-scoped | workspace profile, suggestion state, owner action/send. |
| GET | `/insights`, `/business-insights` | `routers/intelligence.py` | company-scoped | intelligence and deterministic commercial aggregation. |
| POST | `/upload` | `routers/knowledge.py` | inspect handler before pilot | file/knowledge ingestion; parser security boundary. |
| GET/POST | `/brief`, `/stream`, `/timeline`, `/snapshot`, `/opportunities`, `/risks`, `/actions`, `/summary`, `/global-product-stats`, `/product-analysis` | `copilot/router.py` (router prefix must be verified in source deployment) | company-scoped expected | second copilot/dashboard contract family. |

## Frontend route inventory

| Route | Access | Page | Primary dependencies |
|---|---|---|---|
| `/` | public | `LandingPage` | static marketing. |
| `/login`, `/signup` | public | auth pages | auth context/API. |
| `/terms`, `/privacy` | public | legal pages | static. |
| `/c/:slug` | public | `PublicChat` | public session/chat Axios calls; localStorage visitor token. |
| `/chat/:slug` | public legacy | redirect component | redirects to `/c/:slug`. |
| `/dashboard` | protected | `Dashboard` | dashboard/engine services and contexts. |
| `/bot-settings` | protected | `Settings` | company/bot configuration. |
| `/business-intelligence` | protected | `IntelligenceCenter` | intelligence service/adapter. |
| `/customers`, `/customers/:id` | protected | `Customers`, `CustomerWorkspace` | CRM/profile/timeline/suggestions/outbound/Ask VELOR. |
| `/ai-reports` | protected | `AIReports` | legacy/report surface. |

## Contract and ownership notes

### Public chat contract

`POST /api/public/companies/{slug}/session` establishes a visitor token. `POST /api/public/chat` requires `Authorization: Bearer <visitor token>`, `message` (non-empty, <=1000 chars) and `client_message_id`. It constructs a channel-scoped `wa_message_id` (`wc:{company}:{client id}`), uses `acquire_inbound_processing_claim`, and returns `status`, `reply`, and optional public message `id`; duplicates can return `duplicate: true` or `202 processing`. `PublicChat.jsx` then polls the session endpoint every 2 seconds while sending and every 5 seconds otherwise.

### Owner/customer contract

The source exposes at least three overlapping customer representations: legacy `Lead` list/status endpoints, `/customers/{id}` CRM workspace profile, and engine/copilot projections. Their stable common identity is a company-scoped numeric lead id, but messages may be indexed by phone-like `user_id`, visitor id, `internal_message_id`, `public_message_id` or WhatsApp id. Frontend compatibility must not assume a single message key.

### Persistence and freshness

| Entity | Primary writer | Reader | Authority/freshness |
|---|---|---|---|
| `Message`, `MessageEvent` | public chat, `/chat`, webhook, owner send | session/timeline/workspace | factual transport record; per-turn. |
| `LeadEvidence` | evidence engine/pipeline | interpreter, action/suggestion, Ask VELOR | source-backed fact/inference; hash-deduped. |
| `LeadMemory` | memory service/rebuild | workspace/response | derived, revocable/supersedable; can lag. |
| `CommercialDecisionLineage`, `CommercialEvent` | commercial turn persistence | business intelligence/workspace | deterministic projection of a source turn, not truth of outcome. |
| `LeadIntelligenceSnapshot`, `FollowUpTask` | separate worker/scheduler | dashboard/engine | derived/LLM or scheduled; stale and parallel. |
| `CompanyKnowledge.products_data` | settings/upload/merge paths | product/evidence enforcement | current catalog JSON authority; migration/normalizer compatibility risk. |

## Confirmed mismatches and raw-value leakage risks

1. **CONTRADICTORY route families:** `main.py` holds dashboard engine, owner transport and two copilot endpoints while routers expose CRM/intelligence/copilot alternatives. This makes a frontend/API contract drift likely even where individual endpoints are tested.
2. **CONFIRMED legacy redirect:** frontend preserves `/chat/:slug`; backend preserves legacy `/chat` gateway semantics while web chat uses `/api/public/chat`.
3. **LIKELY raw enum leakage:** backend services use enum/value sets for state, strategy, action, objection, event and channel; `LeadIntelligenceSnapshot` stores free text/JSON. The UI mapping is spread across pages/components and needs runtime contract snapshots before product claims.
4. **CONFIRMED source-model ambiguity:** product/catalog truth is JSON on `CompanyKnowledge`, while evidence, product context and sales knowledge each serialize interpretations. Do not display a projection as catalog truth.
5. **RUNTIME-UNVERIFIED:** response models are mostly omitted from route decorators, so static decorators do not establish stable OpenAPI response contracts. Browser/API snapshots are required once a safe isolated runtime is supplied.

## Authentication, isolation and idempotency

`main._get_current_user` validates owner JWT; `_resolve_company_id` provides company selection/scoping for many endpoints. Public visitor JWT is created in `_create_visitor_token` and parsed by `_get_current_visitor`. Internal gateway calls require `X-Internal-Secret`. Inbound public/WhatsApp paths have processing claims; tests cover duplicate suppression and tenant isolation. Coverage does not prove every legacy route consistently uses the same resolver.

## Audit-completion runtime contracts

The isolated backend was started with the explicit audit database. Runtime-confirmed responses were `GET /health` -> `200 {"status":"ok","version":"3.0.0"}`, `GET /me` without cookie -> `401`, and `POST /api/public/companies/arvena-demo/session` -> `404 {"success":false,"message":"Company not found","status_code":404}`. The frontend root and `/login` returned 200 through Vite; browser confirmation of `/c/arvena-demo` showed the user-facing unavailable state.

This 404 is an important contract result: it was caused by the seed failure on an Alembic-head database, not by missing frontend routing. No authenticated customer/workspace response shape could be safely produced because creating a substitute tenant would violate the deterministic-fixture restriction.

### Runtime authority conflict contracts

| Surface / endpoint family | Primary source today | Fallback / conflict behavior |
|---|---|---|
| `GET /api/v1/crm/customers/{id}` | `customer_interpreter` output from messages/evidence/sales-state | `LeadIntelligenceSnapshot` fills absent `why_*`, recommendation, outcome and execution sequence; lineage is returned separately. |
| legacy `/api/engine/*` | `LeadIntelligenceSnapshot` plus lead fields | `main._lead_priority_payload` favors snapshot priority and action when it exists. |
| copilot `/api/v1/copilot/*` and daily brief | snapshot plus lead data | snapshot risk/action/reasons are consumed directly. |
| BI `/business-insights` | `CommercialEvent` deterministic aggregation | independent from snapshot unless a caller separately blends it. |
| Ask VELOR lead | interpreter/evidence path | the main endpoint separately reads `LeadIntelligenceSnapshot` recommendation as a fallback. |

The migration defect is itself an API/data contract issue: current ORM `CompanyKnowledge` includes `google_sheet_webhook_url`, but Alembic head does not. Any route that queries `CompanyKnowledge` can fail on a database created by the advertised migration procedure.

### Test contract caveat

`tests/conftest.py` sets a unique temp `DATABASE_URL`, imports app code, and executes `Base.metadata.drop_all/create_all`. This means the complete 668-pass suite proves application behavior against ORM-generated test tables, not against Alembic’s database contract. Migration tests exist but did not prevent this current seed failure.
