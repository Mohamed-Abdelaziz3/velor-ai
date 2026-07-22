# Phase report — Phase 0: Discovery, security hygiene, and baseline

Audit date: 2026-07-22  
Repository inspected: `<REPOSITORY_ROOT>`
Authority: current working-tree evidence only. This report does not replace later phase decisions.

## Outcome

- Status: COMPLETE
- Scope respected: YES
- Workstreams touched: A — Repository and security hygiene; B — Runtime reproducibility and operations
- Product behavior changed: NO
- Phase boundary: Phase 1 was not started.

Phase 0 established a current, evidence-backed inventory and baseline. The product source was not refactored, runtime data was not deleted, credentials were not printed or validated against external services, and no production-readiness claim is made.

## Discovery

### Inspected

- Repository boundary, Git state, ignore rules, release-candidate file manifest, and local ignored artifacts.
- Root, backend, frontend, and gateway dependency manifests and documented setup commands.
- FastAPI composition root, registered routers, React route surface, Baileys QR gateway, scheduler, RQ/Sheets path, migrations, tests, and current audit/release documentation.
- Customer-message entry points and their engine, persistence, delivery, retry, and fallback branches.
- Environment-file key state with all values redacted.
- High-confidence token patterns in release-candidate files, with matching values kept redacted.
- Existing Python/Node runtime state and repeatable backend/frontend verification gates.

No `AGENTS.md` or additional repository instruction file was found in the repository, `.agents`, or `.codex` roots.

### Repository and rollback baseline

| Item | Observed state |
|---|---|
| Inner repository | `adam_ai_v4_FINAL/.git` exists |
| Branch | `main` |
| HEAD | None; Git reports `No commits yet on main` |
| Indexed/tracked files | 0 |
| Release-candidate files before this report | 320 |
| Baseline manifest SHA-256 | `703ddd54ff40bf4367182ea1e4ba4fd88b7adbf59ff045527638c7ee9c6721e5` |
| Working-tree state | All release-candidate source is untracked; ignored runtime artifacts are present |
| Current porcelain entries after this report | 9,064; 8,735 are under an unignored `.venv-legacy-broken-old` directory |
| Outer workspace `.git` | Present as a OneDrive directory but not recognized as a repository from the outer workspace |

The manifest fingerprint was calculated from sorted relative path plus SHA-256 pairs for files returned by `rg --files`; ignored `.env`, databases, logs, sessions, virtual environments, dependencies, and build output were excluded. It is evidence of the pre-report source snapshot, not a substitute for a recoverable commit.

The raw Git inventory is much larger than the release-candidate manifest because `.venv-legacy-broken-old/` is not covered by the current ignore rule. It contains 14,484 filesystem files totaling 379,555,138 bytes; 8,735 paths appear in Git porcelain after nested ignore rules are applied. `backend/.pytest_tmp/` also returned access denied to both recursive inspection and Git, so its contents are explicitly unknown and are not included in the counts above.

### Repository inventory

| Area | Current evidence |
|---|---|
| Release-candidate files | 320 before this report |
| Python files | 191 |
| Backend test modules | 73 |
| Frontend contract-test modules | 6 |
| Alembic revisions | 32; one head, `f9a8b7c6d5e4` |
| Backend service modules | 43 |
| Backend router modules | 8 |
| Frontend page modules | 22 |
| Large composition modules | `main.py` 4,170 lines; `brain.py` 2,049; `velor_chat_v2.py` 3,351; `database.py` 1,644 |

The intended release repository is a FastAPI modular monolith with a React/Vite frontend and an optional Node/Baileys QR gateway. The current source has meaningful service boundaries, but the largest runtime responsibilities remain concentrated in `main.py`, `brain.py`, `database.py`, and `services/velor_chat_v2.py`.

### Runtime inventory

| Runtime/process | Entry point | Current role | Evidence status |
|---|---|---|---|
| FastAPI | `backend/main.py:app` | HTTP API, auth, public chat, external/QR chat adapter, owner operations, SSE, scheduler lifecycle | Imported and exercised by the full test suite |
| React/Vite | `frontend/src/main.jsx` -> `App.jsx` | Landing, auth, public chat, dashboard, inbox, customer workspace, analytics, automations, settings, billing | Contract tests, lint, and production build passed |
| QR gateway | `backend/whatsapp_gate.js` | Baileys sessions, QR/status stream, inbound forwarding, outbound delivery and ACK | Syntax passed; no live device/session test |
| APScheduler | `backend/scheduler.py` | Token/audit cleanup, stuck-message failure, webhook-inbox recovery, follow-up sweep | Started by FastAPI lifespan; unit/integration behavior covered, live multi-process run not demonstrated |
| RQ Sheets worker | `backend/workers/rq_client.py` and `sheets_worker.py` | Optional Sheets export queue; skips unless enabled/callable | Not started or externally tested |
| Legacy intelligence worker | `backend/workers/intelligence_worker.py` | Advisory LLM snapshot writer | Disabled by default by `ENABLE_LEGACY_INTELLIGENCE_WORKER=false`; direct test/manual call path remains |
| Memory rebuild task | `backend/engine/memory.py` | LLM-derived lead-memory rebuild for rollback/manual paths | Still reachable from V1 processing and manual rebuild endpoint; separate from bounded V2 turn updates |

The local backend environment currently resolves to SQLite at `backend/fresh_db_4d5b1aab.db`. A read-only runtime summary reported the database reachable, at Alembic revision/head `f9a8b7c6d5e4`, with no missing tables or columns. SQLite remains a local-development runtime; release configuration requires PostgreSQL.

### Current product surface

The active frontend exposes landing, login, signup, terms, privacy, public Web Chat, onboarding, dashboard, inbox, customer workspace, analytics, automations, settings, and billing. Compatibility redirects point old customer and bot/business-intelligence paths toward the current surfaces. The core merchant loop is visible in the inbox/workspace/catalog-policy paths, but billing and automation breadth is still present despite there being no connected self-service payment lifecycle.

### Current customer-message path map

#### 1. Public Web Chat — default V2

```text
POST /api/public/chat
  -> visitor JWT and tenant resolution
  -> IP / visitor / tenant rate limits
  -> web-chat company and lead resolution
  -> idempotent inbound processing claim
  -> get_v2_ai_response
     -> catalog/policy and bounded history context
     -> capability/action planning
     -> model writer or bounded fallback
     -> grounding/style/claim validation and trace
  -> persist_v2_public_turn_atomic
     -> inbound projection, evidence, lead update
     -> linked outbound message and message events
     -> commercial decision/projection and telemetry
     -> processing-claim completion in one transaction
  -> HTTP response returned to the customer
```

`PUBLIC_WEB_CHAT_RESPONSE_ENGINE` defaults to `v2`. `v1` remains an explicit rollback path through `brain.get_ai_response`. The broad test fixture sets Web Chat to V1 by default, while dedicated V2 tests override the setting; therefore the full-suite count must not be interpreted as exclusively exercising the release-default path.

#### 2. WhatsApp QR — default V2, partial decision/delivery separation

```text
Baileys messages.upsert
  -> POST /chat with X-Internal-Secret and X-Company-ID
  -> tenant resolution and idempotent claim
  -> _chat_v2 -> get_v2_ai_response
  -> persist_v2_public_turn_atomic(delivery_status=pending)
  -> reply returned to QR gateway
  -> Baileys sendMessage
  -> POST /api/whatsapp/webhook/ack
  -> monotonic Message delivery-state update
```

The V1 rollback remains selectable. V2 separates persisted decision from the gateway send, but there is no durable outbound outbox/worker queue; the gateway performs delivery from the synchronous response and uses retry/circuit-breaker logic in memory.

#### 3. Meta WhatsApp — durable ingress, coupled decision and delivery worker

```text
Signed POST /api/whatsapp/webhook
  -> feature flag and HMAC validation
  -> durable WebhookInbox insert before HTTP 200
  -> background inbox item claim/recovery
  -> tenant mapping and idempotent message claim
  -> get_v2_ai_response
  -> atomic decision/reply persistence as pending
  -> Graph API send in the same background processing flow
  -> monotonic sent/failed/delivered/read updates
```

Duplicate completed items reuse the linked persisted reply rather than regenerating it. This is stronger than direct inline handling, but the decision and external send still share one worker function rather than a distinct durable outbox. Meta is disabled by default and was not tested against external Meta services.

#### 4. External API — shared `/chat` adapter

API-key requests to `/chat` default to the same V2 generation and atomic persistence path. The shared executor persists outbound status as `pending`, but the external API has no demonstrated provider ACK path comparable to QR. Whether an HTTP response constitutes `sent`, `handed_off`, or intentionally `pending` needs an explicit Phase 2 contract; otherwise the one-minute scheduler can eventually classify the returned reply as failed.

#### 5. Non-customer AI paths

- `/api/v1/copilot/chat` and `/api/v1/copilot/chat/lead/{lead_id}` use `services.velor_chat_service.ask_velor`; they are merchant-assistant paths, not the customer reply authority.
- Workspace suggested replies use their own bounded generation/persistence service and are owner drafts, not automatic delivery.
- V1 `brain.get_ai_response`, LLM memory rebuild, and the disabled legacy intelligence snapshot worker remain compatibility/advisory paths. They should not be called the canonical release decision path.

### Important findings

#### P0-SEC-01 — unauthenticated QR gateway control and delivery routes (HIGH)

`backend/whatsapp_gate.js` applies `requireInternalSecret` to takeover and debug routes, but not to:

- `GET /api/whatsapp/stream/:company_id`
- `GET /api/whatsapp/status/:company_id`
- `POST /api/whatsapp/start/:company_id`
- `POST /api/whatsapp/send/:company_id`

The default bind host is `127.0.0.1`, which limits immediate exposure on the documented configuration. `NODE_HOST` is configurable, however, and no route-level control prevents QR disclosure, session boot, status enumeration, or message sending if the gateway is exposed through a network bind, proxy, tunnel, or container port. CORS is not an authorization control. No test currently asserts authentication for these routes.

Required future action: protect all non-health gateway routes with the internal secret or another explicit authenticated proxy contract, update every caller, and add negative/positive tests before any non-loopback deployment.

#### P0-SEC-02 — secrets, sessions, logs, and databases are inside a OneDrive-synced working tree (HIGH)

The following ignored local state exists:

| Artifact class | Count/size evidence |
|---|---|
| WhatsApp session state | 4 tenant directories, 1,704 files, 335,810 bytes |
| SQLite DB/WAL/SHM artifacts | 29 files, 50,971,248 bytes |
| Log artifacts | 57 files, 764,557 bytes |
| Local environment files | Root, backend, and frontend `.env` files are present |

`backend/.env` has redacted-but-set values for `JWT_SECRET`, `NODE_INTERNAL_SECRET`, `GROQ_API_KEY`, and `VELOR_META_VERIFY_TOKEN`; `META_GRAPH_API_TOKEN` is placeholder-like. No value was printed or externally tested. `.gitignore` correctly excludes these paths from a future Git commit, but it does not exclude them from OneDrive sync, local backup, endpoint indexing, or accidental folder sharing. Database and log contents were not opened because they may contain customer data.

Required owner decision: determine whether this OneDrive folder has ever been shared or synchronized to an untrusted device/account. If yes or uncertain, revoke the four QR sessions and rotate all configured secrets/tokens. Even if it has not, move runtime secrets, sessions, databases, and logs outside the source tree before a pilot.

#### P0-REPO-01 — no recoverable source checkpoint (HIGH)

The inner repository has no commit and tracks no file. All 320 pre-report release-candidate files are untracked. There is no Git history to inspect for earlier secret exposure, no reviewable baseline, and no reliable source rollback. The outer `.git` directory is not a usable repository from the workspace root.

In addition, `.venv-legacy-broken-old/` is a 379,555,138-byte local environment not matched by `.gitignore`, producing 8,735 porcelain entries and creating a substantial accidental-first-commit risk. `backend/.pytest_tmp/` could not be enumerated because of its current permissions, so it must be treated as an unresolved local artifact until its ownership and contents are safely verified.

Required future action: decide the canonical repository root, run a dedicated secret scan, select visibility/license, then create an intentional first commit. Do not commit any ignored runtime artifact.

#### P0-OPS-01 — local toolchain is not reproducible as checked out (MEDIUM)

- `.venv/Scripts/python.exe` cannot start because its recorded base Python path no longer exists.
- `node` and `npm` are not available on the current PATH.
- The backend uses bounded requirement ranges but has no fully resolved Python lock file.
- Frontend and gateway npm lockfiles exist.
- Verification succeeded only by combining the bundled Python 3.12.13 runtime with the existing `.venv/Lib/site-packages` and by invoking the bundled Node 24.14 runtime directly against existing `node_modules`.

This proves the current source against already-installed dependencies. It does not prove `clone -> install -> run` reproducibility.

#### P0-ARCH-01 — one release-default V2 path, with bounded but material parallel paths (MEDIUM)

V2 is the default for Web Chat, WhatsApp, and external API and release configuration rejects V1. However:

- V1 remains active as an explicit rollback and dominates the broad test fixture defaults.
- `main.py`, `brain.py`, and `velor_chat_v2.py` remain very large orchestration modules.
- External API delivery status semantics are unresolved.
- Web Chat, QR, and Meta have different delivery boundaries.
- The legacy intelligence worker is disabled by default, but the separate LLM memory rebuild path remains reachable.
- Merchant copilot and workspace-draft generation are separate AI flows and must stay clearly outside customer reply authority.

Phase 2 should make the canonical call graph and ownership contract explicit before removals or a modular refactor.

#### P0-EVIDENCE-01 — local tests are strong, but external and clean-install evidence is absent (MEDIUM)

The full local suites pass, including dedicated V2, tenant, migration, claim, delivery, evidence, and failure-path tests. The tests use mocks/fixtures for external providers and the common `conftest.py` deliberately sets all three customer engines to V1 unless a test overrides them. No live Groq, Redis, PostgreSQL, Meta, QR device, public browser, backup/restore, or clean dependency installation was executed in this phase.

#### Token-pattern scan result

A high-confidence filename-only pattern scan found token-shaped strings in three backend test modules. Redacted context confirms they are assigned through `monkeypatch.setenv` in mocked provider tests; no production/config file matched. They should still be replaced with unmistakably synthetic non-secret fixtures if a dedicated scanner flags them before the first commit. Because there is no Git history and no external validation, this result is `NO HIGH-CONFIDENCE PRODUCTION SECRET FOUND IN RELEASE-CANDIDATE FILES`, not proof that every local credential is safe.

### Assumptions

- With no assigned phase in the invocation, the mandatory roadmap begins at Phase 0.
- The inner `adam_ai_v4_FINAL` directory is the intended repository because it contains the source and initialized Git metadata.
- Existing local databases, logs, sessions, environments, dependencies, and unrelated working files belong to the user and must be preserved.
- Network/provider calls are out of scope for Phase 0 unless explicitly authorized; none were made.
- The configured local database is development evidence only, not production data-readiness evidence.

## Scope contract

- Assigned phase: Phase 0 — Discovery, security hygiene, and baseline
- Objective: inventory repository/runtime/security state, map current conversation paths, record baseline verification, and propose safe cleanup
- Allowed files/modules: read-only inspection across the repository; this Phase 0 report under `docs/audits/`
- Expected files to change: `docs/audits/VELOR_PHASE_0_DISCOVERY_SECURITY_BASELINE_2026-07-22.md` only
- Out-of-scope files/modules: all product source, migrations, schemas, databases, logs, sessions, environment files, dependencies, and existing audit/history documents
- Behavioral changes allowed: none
- Behavioral changes prohibited: route/auth changes, refactors, UI changes, data cleanup, migration execution against production, provider calls, credential rotation, and Phase 1 work
- Data/schema impact: none
- External services affected: none
- Scope changes and reasons: none

## Changes

- Implemented: this evidence-backed Phase 0 report only
- Files/modules changed: `docs/audits/VELOR_PHASE_0_DISCOVERY_SECURITY_BASELINE_2026-07-22.md`
- Data/schema impact: none
- External services affected: none
- Verification side effects: frontend build output and test caches/temp files may have been regenerated; they are ignored and are not release-candidate source

### Proposed safe cleanup plan — not executed

1. **Checkpoint first:** choose `adam_ai_v4_FINAL` as the canonical root or deliberately relocate it; verify the inaccessible pytest temp path; explicitly ignore or archive `.venv-legacy-broken-old/`; run a dedicated secret scan; create the first reviewed commit only after sensitive-artifact checks.
2. **Move runtime state:** configure secrets, WhatsApp sessions, databases, uploads, and logs under a non-synced runtime directory. Preserve an encrypted backup until the active database/session set is confirmed.
3. **Rotate/revoke conditionally:** if OneDrive sharing/sync exposure is possible, rotate JWT, Node, AI, and Meta secrets and revoke all saved QR sessions before copying or publishing source.
4. **Close the QR gateway boundary:** authenticate stream/status/start/send, update callers, and add tests while retaining default loopback binding.
5. **Rebuild the toolchain:** recreate `.venv` from a supported installed Python, provide a documented Node/npm/pnpm path, and add a reproducible Python resolution/lock strategy.
6. **Prove a clean setup:** in an isolated clean directory, install from manifests, migrate a fresh database, seed the supported demo, run backend/frontend/gateway checks, and start the supported services.
7. **Quarantine, then remove:** only after reference searches and a recoverable checkpoint, move obsolete databases/logs/repair scripts to a dated non-repository archive. Do not bulk-delete from the current OneDrive tree.
8. **Refresh truth claims:** update README and launch-audit counts after the clean baseline; keep live-provider, browser, PostgreSQL/Redis, WhatsApp, and market claims explicitly unverified until demonstrated.

## Verification

### Commands/procedures and results

| Check | Repeatable command/procedure | Result |
|---|---|---|
| Git state | `git -c safe.directory=<repo> -C adam_ai_v4_FINAL status --short --branch`, full porcelain grouping, and `rev-parse HEAD` | `main`, no commits/HEAD; 9,064 current entries including this report; 8,735 under the unignored legacy environment |
| Source baseline fingerprint | SHA-256 of sorted `rg --files` path/hash manifest | 320 files; `703ddd54ff40bf4367182ea1e4ba4fd88b7adbf59ff045527638c7ee9c6721e5` before this report |
| Alembic head | Bundled Python with existing site-packages: `python -m alembic heads` | `f9a8b7c6d5e4 (head)` |
| Local DB compatibility | `database.get_database_runtime_summary(require_migration_head=True)` | Reachable SQLite; revision=head; schema compatible; no missing tables/columns |
| Backend full suite | Bundled Python 3.12.13 plus existing `.venv/Lib/site-packages`: `python -m pytest -q` | PASS: 1,940 passed, 0 failed, 161 warnings in 293.93 s |
| Frontend contracts | Bundled Node 24.14 direct equivalent of package test script | PASS: 47 passed, 0 failed, 0 skipped |
| Frontend lint | Bundled Node direct invocation of ESLint | PASS: exit 0, no reported errors |
| Frontend production build | Bundled Node: `node scripts/vite-build.mjs` | PASS: Vite 5.4.21, 2,283 modules transformed |
| QR gateway syntax | Bundled Node: `node --check whatsapp_gate.js` | PASS |
| Sensitive-artifact inventory | Filename/size/key-state inspection only; values and contents suppressed | Completed; counts and redacted state recorded above |
| High-confidence secret pattern scan | Filename-only custom pattern scan, then redacted context review | Test-fixture matches only; no production/config release-candidate match found |

The initial `npm` wrapper attempt failed because the bundled runtime did not expose the assumed npm CLI path. The exact frontend script bodies were then run directly with the bundled Node executable and passed. This environmental invocation failure is not counted as a source-test failure.

### Known limitations / not run

- Clean clone/install/start path: NOT RUN
- `npm ci` for frontend or gateway: NOT RUN
- Fully resolved Python dependency/lock recreation and `pip check` in a valid project virtual environment: NOT RUN
- Dedicated Gitleaks/TruffleHog/detect-secrets scan: NOT AVAILABLE in the local toolchain
- PostgreSQL 16 migration/isolation CI job: NOT RUN locally
- Redis/distributed rate limiting and RQ worker: NOT RUN
- Authenticated browser QA and screenshots: NOT RUN
- Live AI-provider campaign, latency, token cost, and model quality: NOT RUN
- Real Meta webhook/Graph delivery or QR device session: NOT RUN
- Backup/restore and rollback drill: NOT RUN
- Full endpoint-by-endpoint authorization audit: NOT RUN; the confirmed QR boundary finding is not an exhaustive security assessment
- Git-history secret scan: NOT POSSIBLE because no commit history exists
- `backend/.pytest_tmp/` contents: NOT INSPECTED because the current filesystem permissions denied access

## Status distinctions

- Implemented: Phase 0 inventory/report is implemented. Existing runtime paths described above exist in current source.
- Tested: Backend, frontend contract/lint/build, gateway syntax, Alembic head, and local schema compatibility checks passed as recorded.
- Demonstrated: Local automated behavior and buildability against existing dependencies are repeatable. No current browser, external provider, or device demonstration was produced in this phase.
- Production-ready: NO. Confirmed security, source-control, runtime-state, reproducibility, infrastructure, provider, account, payment, legal/support, and channel-onboarding gates remain.
- Market evidence: EXTERNAL EVIDENCE REQUIRED. No interview, pilot, willingness-to-pay, conversion, retention, or business-outcome claim was created or verified.

## Risks and unresolved work

### High-risk items

- QR gateway control/delivery routes lack route-level authentication.
- Four persisted WhatsApp session directories and configured secrets reside under OneDrive.
- There is no commit/HEAD or reliable source rollback.
- Runtime databases/logs may contain customer or operational data and remain inside the synced working tree.
- An unignored 379,555,138-byte legacy virtual environment creates accidental-commit risk, and the inaccessible pytest temp directory remains an inventory blind spot.

### Follow-ups for a future phase

- Phase 1: establish the intentional repository boundary, dedicated secret scan, first checkpoint, safe runtime-state location, authenticated gateway boundary, valid toolchain, and clean setup proof.
- Phase 2: publish the full canonical call graph and resolve external API delivery status, V1 retirement criteria, outbox boundaries, and ownership of memory/copilot/draft projections.
- Later phases: only after their gates, perform bounded modular refactors, durable outbox work, tenant hardening, governed evaluation, UI simplification, public documentation, and pilot instrumentation.

### Items requiring user or external evidence

- Whether the OneDrive tree has been shared or synchronized beyond trusted devices/accounts.
- Whether to revoke the four stored QR sessions now or preserve them for a controlled local pilot.
- Rotation and ownership of JWT, Node, Groq, and Meta credentials.
- Canonical repository root, visibility, remote, and license.
- Valid AI provider/model/budget and live evaluation results.
- Production domain, hosting, PostgreSQL, Redis, monitoring, backup owner, and support/legal identity.
- Merchant interviews, real pilot usage, willingness to pay, payment, retention, and measured outcomes: `EXTERNAL EVIDENCE REQUIRED`.

## Checkpoint and rollback

- Baseline checkpoint: no Git commit exists. Pre-report source manifest: 320 files, SHA-256 `703ddd54ff40bf4367182ea1e4ba4fd88b7adbf59ff045527638c7ee9c6721e5`.
- Current checkpoint/commit: none; the repository still has no HEAD.
- Rollback procedure: remove only this report to return the release-candidate source manifest to the recorded pre-report state. Ignored frontend build output and test caches can be regenerated and are not source rollback points. Do not use `git reset` or `git checkout` because no commit exists.
- Rollback tested: NO

## Next allowed action

- The next phase is NOT started automatically.
- The next eligible phase is Phase 1 — Reproducible setup and public-repository hygiene, after explicit user authorization for a new phase/session.
