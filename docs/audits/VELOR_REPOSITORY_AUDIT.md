# VELOR Repository, Architecture and Product Reality Audit

> **Historical snapshot — superseded.** This document describes the repository as inspected on 2026-07-11, before the canonical V2 conversation, route, reliability, and UI consolidation work. It is retained for engineering traceability and must not be used as the current launch verdict. See [`../release/VELOR_LAUNCH_READINESS_AUDIT.md`](../release/VELOR_LAUNCH_READINESS_AUDIT.md).

Audit date: 2026-07-11. This audit inspected active source, configuration examples, tests, package scripts, route decorators and available local runtime state. It did not modify production code, schemas, migrations, tests, prompts or dependencies. All conclusions label confidence explicitly.

## 1. Executive verdict

**What VELOR is today (CONFIRMED):** a substantial multi-tenant conversational-sales codebase whose public web chat and WhatsApp ingress share `brain.get_ai_response`, with evidence/product guardrails and a newer deterministic commercial-intelligence layer. It is not yet demonstrably one coherent owner product: legacy ADAM AI monolith behavior, newer VELOR commercial services, LLM-generated intelligence snapshots and multiple workspace/copilot/engine APIs coexist.

**Genuinely coherent:** inbound public chat identity/idempotency, evidence extraction, product/pricing enforcement and many deterministic commercial contracts have focused source and extensive targeted tests. Public web chat has a defined visitor-token and processing-claim path.

**Fragmented:** commercial state/action/attention projections, owner transport/takeover APIs, dashboard/copilot/CRM route families, catalog serialization and terminology/documentation.

**One canonical brain?** No. The automated reply dispatcher is centralized in `brain.get_ai_response`, but state/action intelligence also originates in dedicated services, a standalone LLM intelligence worker, legacy engine code, customer interpreter and copilot paths.

**Owner product internally consistent?** **RUNTIME-UNVERIFIED; static evidence indicates likely inconsistency.** Multiple writers/readers serialize the same concepts and browser comparison was impossible without a running stack.

**Repository understandable enough for safe continued development?** Partially. The active source is traceable, but monolith size, historical artifacts, duplicate route families and multiple databases create material ambiguity.

**Ready for Product Reality remediation?** Yes, only after a stabilization/discovery phase—not UI redesign or features. First stabilize the canonical source-of-truth and reproducible isolated runtime.

## 2. Confirmed active architecture

See [VELOR_SYSTEM_MAP.md](VELOR_SYSTEM_MAP.md). Evidence: `backend/main.py:127–174` lifecycle/router inclusion; `database.py:77–107` engine selection; `brain.py:get_ai_response`; `frontend/src/App.jsx:42–62`; `backend/whatsapp_gate.js`; `backend/scheduler.py`; `backend/workers/`.

README architecture materially mismatches implementation: it is headed “Adam AI,” portrays a WhatsApp/lead-capture core, omits public VELOR chat/commercial lineage, CRM/intelligence/copilot routers, Meta webhook path, deterministic commercial events and the standalone intelligence worker.

## 3. Product capability map

| Capability | Status | Evidence / caveat |
|---|---|---|
| Public web chat identity, resume and idempotency | Exists | `main.py:1206–1490`, `PublicChat.jsx`, `test_velor_web_chat_channel.py`; browser unverified. |
| Grounded product/pricing response enforcement | Exists | product/evidence services; `test_trusted_product_pricing_enforcement.py`, `test_evidence_bound_answer_contract.py`. |
| Commercial objective/strategy/next move/lineage | Exists | commercial service and migrations/models; commercial-capability tests. |
| Customer memory, objection, sales-state and recommendation | Exists but duplicated | separate services plus lead/snapshot/interpreter stores. |
| Owner attention and suggested reply | Partially exists / duplicated | owner attention, priority actions, workspace suggestions, legacy engine and LLM snapshot. |
| Owner manual reply/takeover | Exists but duplicated | CRM and main endpoint families; transport runtime unverified. |
| Ask VELOR customer/business | Exists but partially split | main/copilot/interpreter/commercial service; runtime UX unverified. |
| Business intelligence | Exists | deterministic commercial events aggregation; older analytics/copotilot coexist. |
| WhatsApp | Exists but runtime-unverified | Baileys and disabled-by-default Meta webhook are distinct ingress paths. |
| Responsive/accessibility/empty product states | Runtime-unverified | source has loading/error/disabled UI, but no browser validation. |
| Landing/acquisition | Legacy/frozen | brief says frozen; README/labels retain old product narrative. |

## 4. Critical journeys

### Public Web Chat

Confirmed: visitor session -> company slug/visitor JWT -> `Lead(channel_type="VELOR_WEB_CHAT")` -> public chat rate limits -> processing claim -> `brain.get_ai_response` -> message/evidence and commercial projections -> returned reply and polling resume. Failure behavior includes 429, 400, 404, 504 and 500 paths (`main.py:1314–1490`). Tests cover idempotency, token tampering, rate limiting, takeovers, catalog answers and cross-tenant isolation.

### WhatsApp inbound

Confirmed divergent ingress: `whatsapp_gate.js` posts legacy `/chat`; `routers/webhook.py` handles optional Meta webhook. Both call `brain.get_ai_response`, but only Meta is feature-flagged and each has separate retry/delivery semantics. Runtime transport delivery is unverified.

### Owner reply and intervention

Confirmed: CRM `/chat/send` and main `/api/agent/outbound/send` both participate in manual send; takeover/pause controls are split. Expected contract is one scoped customer identity, one persisted owner message and one channel delivery lifecycle. Cross-surface browser proof is missing.

### Ask VELOR and business intelligence

Confirmed deterministic customer classification and business-event aggregation exist. Tests show intended bounded behavior (including insufficient samples and no fabricated sales/revenue); frontend rendering, evidence deduplication and prioritization are runtime-unverified.

## 5. Canonical source-of-truth findings

The strongest factual source is `Message` plus `LeadEvidence` linked to source message identity. Product/policy authority is `CompanyKnowledge` JSON and knowledge fields, guarded by product/evidence services. Commercial lineage/events are projections of a turn, not actual commercial outcomes. Memory, suggestions, intelligence snapshot, tasks and dashboard fields are derived projections.

The source-of-truth problem is not absence of guardrails; it is that state/action/attention concepts are recalculated and persisted by multiple layers without one documented freshness/invalidation policy. See [VELOR_SYSTEM_MAP.md](VELOR_SYSTEM_MAP.md) and [VELOR_ROUTE_AND_DATA_CONTRACTS.md](VELOR_ROUTE_AND_DATA_CONTRACTS.md).

## 6. Architectural duplication and god modules

`main.py` is an HTTP composition root and a god module. `brain.py` is the main response orchestrator and a legacy business module. Both contain naming/comments for ADAM AI. Routing is split across `main.py`, CRM/intelligence/knowledge/stream/webhook routers and a copilot router, while routes that serve similar owner decisions remain in multiple families.

Important duplication: legacy `/chat` versus `/api/public/chat`; Baileys versus Meta webhook; CRM manual send versus `/api/agent/outbound/send`; dashboard engine versus priority/attention services; LLM `LeadIntelligenceSnapshot` versus deterministic commercial/action projections.

## 7. Product/UX disconnects

Static source shows thoughtful public-chat states: local pending/failed bubble state, retry, token resume, polling, latency indicator and mobile-oriented height classes. However, those are not product-reality proof. `PublicChat.jsx` has two exhaustive-deps warnings around polling/session fetches. The owner workspace combines customer sidebar, briefing, execution dock, timeline, chat, command center and copilot interfaces; static composition alone cannot prove a single decision hierarchy.

The dashboard has unused `topActions`, `moneyExposed` and multiple imports according to lint. This is evidence that the source may contain overlapping product narratives, not proof of a visible defect. Runtime screenshots and same-customer cross-surface comparisons remain required.

## 8. Security and reliability findings

| Priority | Finding |
|---|---|
| P1 | Separate LLM worker can independently write priority/risk/action/execution text, undermining a single evidence-bound projection unless its active call path is proven fenced. |
| P1 | Runtime/browser verification impossible on requested targets; no proof of auth, SSE, takeover or isolation behavior in running product. |
| P2 | Mixed route families/resolvers mean universal company/customer scoping is not proven by selected unit tests. No IDOR was confirmed. |
| P2 | Knowledge ingestion/document parsing and prompt-injection boundary needs dedicated static/runtime security testing. |
| P2 | SQLite default and CWD-dependent database selection, with many old DBs, risk operating on an unintended state. |
| P2 | Full test execution exceeded 124 seconds without a result, weakening a release evidence claim. |

Confirmed protections include a minimum JWT-secret guard, httpOnly-cookie helper path, internal-secret checks, public visitor JWT, slowapi rate limiter with in-memory fallback, processing claims and selected tenant-isolation tests. They do not establish universal endpoint safety.

## 9. Testing reality

`pytest --collect-only -q` collected **668 tests** in **0.65 s**, with one Starlette/httpx deprecation warning and 13 SlowAPI coroutine deprecation warnings. Full `pytest` was executed exactly as configured (`..\\.venv\\Scripts\\python.exe -m pytest`) but timed out at **124.044 s**, exit **124**, before emitting a final count. Therefore no full-suite pass count is claimed.

Coverage is strongest for product/pricing/evidence, web-chat claims/idempotency, catalog parsing/merge and targeted business semantics. It is partial for authentication/isolation and owner transport; absent or runtime-only for visual hierarchy, responsive UX, accessibility, real external delivery, live SSE, actual browser empty states and full cross-surface consistency. Many transport/pipeline tests use mocks/monkeypatching by design; that validates contracts but not a deployed provider/browser path.

Frontend: `npm.cmd run lint` passed with **21 warnings, 0 errors**. `npm.cmd run build` failed: esbuild reported access denied reading `../../../..` and could not resolve the absolute `frontend/vite.config.js`; no build output was validated.

## 10. Repository and documentation drift

### Inventory classification

| Classification | Inventory |
|---|---|
| Active production source | `backend/main.py`, `brain.py`, `database.py`, `routers/`, `services/`, `workers/`, `scheduler.py`, `whatsapp_gate.js`, `frontend/src/`, configs/package definitions/migrations. |
| Active development tooling | Alembic, pytest config, Vite/ESLint config, scripts required by package commands. |
| Test-only | `backend/tests/`, `backend/tests_archive/`, fixtures, `puppeteer_test/` (unconfirmed active). |
| Demo/fixture | demo seed scripts, `ARVENA_Upload_Ready_Catalog.csv`, sales knowledge JSON, existing screenshots (not proof). |
| Historical documentation | README, `AUDIT_REPORT.md`, `STRICT_AUDIT_REPORT_2026-07-02.md`, architecture/sprint reports, DB audit output. |
| Repair artifact | root/backend `fix_*.py`, `patch_backend.py`, `refactor_components.py`, scratch/check/search scripts. |
| Generated/runtime artifact | logs, cached test dirs, `frontend/dist`, screenshots, search outputs, reports, multiple SQLite DB/WAL/SHM files. |
| Legacy/probably dead | `jwt.py` (1 byte), empty `extracted_code.txt`, README-described obsolete `migrate_v2.py` absent, old reports/scripts; exact references not all proven. |
| Uncertain | `.agents`, `.codex-remote-attachments`, `puppeteer_test`, root `K.html`, runtime session/DB files. |

Prominent drift: ADAM AI persists in README, headers, loggers, API-key prefix, default Sheets title; Cashora persists in frontend visual class names; README is WhatsApp-first and omits most current VELOR commercial architecture.

## 11. Top root causes

1. Canonical concepts were added as layers rather than governed by a single ownership/freshness contract.
2. Legacy monolith endpoints and newer router/service architecture were retained in parallel.
3. The repository retains repair/output/runtime artifacts beside active source and many possible databases.
4. The real Alembic migration contract has drifted from the active ORM while pytest bypasses it with `create_all`, so a clean runtime cannot seed the approved fixture.

## 12. Recommended remediation sequence

1. **Establish an isolated, seeded runtime baseline.** Explicit database URL, migration head, service startup ownership, safe test tenant and browser access are prerequisites for all UX claims.
2. **Publish and enforce a source-of-truth/freshness contract.** Start with customer identity, messages/evidence, catalog/policy, sales state, next action and owner attention. Classify every other field as projection/cache and define invalidation.
3. **Choose one commercial decision projection pipeline.** Reconcile/fence the LLM intelligence worker, legacy engine and newer deterministic lineage/action services before changing owner UI.
4. **Unify route/transport contracts.** One manual-send/takeover contract, explicit ingress adapters for Baileys/Meta, and a documented message identity/delivery lifecycle.
5. **Run cross-surface product reality acceptance.** Same customer across public chat, workspace, dashboard, Ask VELOR, Intelligence Center and lineage; then address confirmed UX hierarchy/content issues.
6. **Perform documentation/repository cleanup after code-path decisions.** Archive rather than delete historical artifacts; update README/terminology after canonical paths are settled.

## 13. Explicit non-recommendations

- Do not start landing-page/acquisition or visual redesign work.
- Do not add another AI/copotilot/insight surface.
- Do not expand channels or introduce new LLM behaviors.
- Do not refactor `main.py`/`brain.py` cosmetically before mapping ownership and callers.
- Do not delete old databases, scripts or reports until retained runtime/deployment references are proven absent.

## 14. Remaining uncertainty

- The isolated stack verified health, frontend root/login and public unavailable-state rendering, but public chat, owner login, workspace, mobile, delivery, SSE, business cards and prescribed message scenarios remain runtime-unverified because the approved seed fails on the migrated schema.
- Actual production/deployed environment, secrets, migration revision, database contents, Redis, Groq, Google and WhatsApp connectivity were not inspected.
- Full pytest passes in the isolated copy, but it uses ORM `create_all` and therefore does not prove Alembic-schema parity.
- The intelligence worker has confirmed reachable callers, although no qualifying task could run in the empty isolated database.
- Route response serialization and all authorization dependencies need OpenAPI/runtime snapshots in the isolated environment.

See the consolidated findings in [VELOR_DEFECT_AND_DRIFT_LEDGER.md](VELOR_DEFECT_AND_DRIFT_LEDGER.md).

## Audit-completion addendum — 2026-07-11

### Isolated runtime and database evidence

An isolated source copy was created at `C:\tmp\velor-audit-runtime` with `.git`, `.venv`, `node_modules`, build output, caches, sessions, logs and existing databases excluded. The source has no usable Git metadata (`git rev-parse HEAD` reports not a repository), so the copy is identified by source path and audit timestamp rather than commit hash. The original repository was not changed.

The explicit runtime database was `sqlite:///C:/tmp/velor-audit-runtime/runtime/velor_audit.db`. `alembic upgrade head`, `alembic current`, and `alembic heads` all reported `d4f6a8b0c2e4 (head)`. This is **not sufficient runtime correctness evidence**: immediately afterwards `scripts/seed_trusted_demo_tenant.py` failed with `sqlite3.OperationalError: no such column: company_knowledge.google_sheet_webhook_url`. The active `CompanyKnowledge` ORM query selects that column, but the head schema does not contain it. The deterministic ARVENA seed therefore did not create a tenant, customer, catalog or business-intelligence fixture.

This confirms a migration/model contract defect, rather than a OneDrive-only build issue. The standard pytest fixture in `backend/tests/conftest.py` instead calls `Base.metadata.create_all()` on a fresh temp database; it does not apply Alembic. Thus the full passing suite cannot prove that a database created by the real migration chain can run current ORM code.

### Runtime topology verdict

The minimum runtime was started with the explicit audit `DATABASE_URL`: FastAPI (`python -m uvicorn main:app --host 127.0.0.1 --port 8000`) and Vite (`npm.cmd run dev -- --host 127.0.0.1 --port 5173`). FastAPI logged scheduler registration/start and `GET /health` returned `200 {"status":"ok","version":"3.0.0"}`. The runtime created WAL/SHM files beside the audit database while the original `backend/adam_ai.db` timestamp remained unchanged, providing runtime evidence that the server used the isolated database.

Redis was not running; FastAPI logged a timeout and fell back to the in-memory SlowAPI store. No RQ worker, Google integration, Baileys gateway or Meta webhook was started. The scheduler is **REQUIRED by the current FastAPI lifespan**, but its work is not required for the attempted health/root/login checks. Meta webhook is **BETA/disabled by default** (`ENABLE_META_WEBHOOK`); RQ/Sheets and the Baileys gateway are **OPTIONAL/RUNTIME-UNVERIFIED** for public web chat.

### Browser audit verdict

Browser verification against the isolated runtime confirmed the frontend root and `/login` render. The public route `/c/arvena-demo` calls the backend session endpoint, receives 404, and renders the intended “conversation unavailable” state; this is a correct consequence of the blocked fixture seed, not a public-chat journey pass. The root landing page presents VELOR branding and claims grounded commercial intelligence. The actual login page visibly renders `ADAM // SYSTEM`, `ADAM // AUTH`, and English ADAM-era “Executive Intelligence” copy. This is **CONFIRMED runtime terminology/product-surface drift**, not merely a source-class-name observation.

Scenarios A–H, owner authentication, workspace, dashboard, Ask VELOR, mobile comparison, takeover, delivery and business-intelligence verification remain blocked by the migration-safe seed failure. No customer/visitor messages were sent, preventing evidence contamination.

### Full verification results

From the isolated copy using the existing project virtual environment: `python -m pytest -q` completed with **668 passed, 125 warnings in 118.16 seconds** (successful completion/exit 0). Warnings include one Starlette/httpx deprecation, 13 SlowAPI coroutine deprecations, and 111 per-request TestClient cookie deprecations across named suites.

After `npm.cmd ci --offline` installed the lock-file-pinned frontend dependencies (473 packages, 0 vulnerabilities), `npm.cmd run lint` exited 0 with **21 warnings, 0 errors**. `npm.cmd run build` completed successfully in **14.25 seconds**: Vite 5.4.21 generated a 714.06 kB JS bundle (216.24 kB gzip). Node was v24.14.1, npm 11.11.0 and esbuild 0.21.5. The earlier build error is therefore classified as a sandbox/filesystem-permission interaction, not a source, dependency, Vite-config, Node-version or esbuild-binary failure.

### LLM intelligence-worker verdict

**ACTIVE LEGACY OVERLAP.** `workers/intelligence_worker.py:rebuild_lead_intelligence_task` is reachable from `brain.py` through `engine.memory.rebuild_lead_memory_task` after qualifying customer turns, from `POST /api/leads/{id}/memory/rebuild`, and directly from `POST /api/v1/crm/customers/{id}/action` (`routers/crm.py:640–642`). It makes a Groq call and upserts `LeadIntelligenceSnapshot` fields including `priority_score`, `lost_risk_score`, `why_*`, `next_best_action`, `expected_outcome` and `execution_sequence`, then emits a `SystemEvent` live brief. It is not evidence-bound: its prompt reads lead fields, memory and activity logs, with no evidence pack or lineage validation.

The worker did not run in the empty isolated runtime because no authenticated owner action or qualifying customer turn could be made. It is nevertheless an active reachable path, not dead code. It conflicts with two other snapshot writers: the deterministic legacy follow-up engine (`brain.py:2016–2036` -> `engine/scorer.py:325–424`) and the scheduler, which increases snapshot lost-risk in place (`scheduler.py:56–98`). No conflict-resolution rule compares these outputs to `CommercialDecisionLineage`.

### Canonical authority verdict and first remediation phase

The confirmed first remediation phase is **B. Runtime/Data Foundation Stabilization**. It must first own migration/model parity, explicit database selection, reproducible seed/migration validation, and a documented authority/freshness contract. Until the migrated schema can seed and run the deterministic fixture, Canonical Commercial Authority Consolidation cannot be accepted with runtime evidence; UI remediation would only conceal broken/ambiguous data.

During this phase, `LeadIntelligenceSnapshot`, workspace live-brief fallbacks, legacy engine scores, LLM intelligence worker output, scheduled risk changes and suggested replies must be explicitly classified as projections, caches or authorities with defined invalidation. Do not change UI, prompts, channels, catalog features or perform cosmetic monolith refactors yet. Acceptance evidence: Alembic-created database equals ORM schema; ARVENA seed succeeds; backend/frontend start against the same DB; and Scenario E/F consistency matrix demonstrates one named authority per concept with defined conflict behavior.
