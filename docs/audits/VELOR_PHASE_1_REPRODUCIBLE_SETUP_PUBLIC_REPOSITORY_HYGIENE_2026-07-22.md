# Phase report — Phase 1: Reproducible Setup and Public Repository Hygiene

**Date:** 2026-07-22  
**Repository:** `adam_ai_v4_FINAL`  
**Governing inputs:** `VELOR_GPT_5_6_SOL_MASTER_EXECUTION_PROMPT.md` and the Phase 0 discovery/security baseline

## Outcome

- **Status:** PARTIAL
- **Scope respected:** YES
- **Workstreams touched:** A — repository/security hygiene; B — runtime reproducibility; bounded Phase-1-required setup and contribution documentation from F.
- **Reason the phase is not marked COMPLETE:** the technical source export is reproducible and reaches the seeded demo, but the Git repository has no `HEAD`, no remote, and no configured author identity. All 340 pre-report source candidates are untracked, so a literal `git clone` cannot yet be tested. No public license has been selected. Those owner-controlled publication decisions were not fabricated or bypassed.

## Discovery

- **Inspected:** the Phase 0 report; master execution protocol; root/backend/frontend ignore files; four safe environment examples; Python and npm manifests/locks; CI workflow; README, security, contribution, and PR documentation; Git state; migration and trusted-demo scripts; test/startup contracts; local tool availability; and aggregate local artifact state.
- **Important findings:**
  - Runtime secrets, databases, logs, WhatsApp session state, virtual environments, caches, and Node installs existed beside source. They were local-only and not moved or deleted.
  - Safe `*.env.*.example` files were accidentally ignored, while an old virtual-environment directory and `.pytest_tmp` were not covered consistently.
  - Python manifests expressed version ranges but had no exact transitive lock. Both npm applications already had v3 lockfiles.
  - The verification environment example selected SQLite while `ENV=verification` requires PostgreSQL, so copying it could not satisfy its own runtime contract.
  - The frontend full development dependency audit reports two vulnerable packages: one moderate and one high. Clearing them requires a Vite major upgrade. The production-only frontend audit is clean.
  - The backend Node lock initially reported six advisories. A non-breaking lock-only refresh within declared manifest ranges cleared them.
  - Git is on branch `main` but has no commit, remote, author name, or author email. A public license remains intentionally unselected.
- **Assumptions:** SQLite is the supported isolated local-development verification target; `ENV=verification` remains PostgreSQL-only. Existing local artifacts may contain sensitive or user data and therefore remain untouched. Dependency registries may be used only to download/audit declared packages, without product-service credentials.

## Scope contract

- **Allowed files/modules:** repository ignore and text-normalization configuration; safe environment examples; Python/npm locks; root install wrapper; CI and PR gates; setup/security/contribution documentation; source-only secret/artifact inventory scripts; this phase report.
- **Out-of-scope files/modules:** application behavior; QR authorization; API contracts; models and migrations; architecture; UI/product flows; existing sessions, databases, logs, uploads, caches, and user data; Phase 2 analysis or refactoring.
- **Scope changes and reasons:** none. Existing migrations were executed only against a newly created isolated SQLite file to verify setup; no migration file or existing database was changed.
- **Behavioral changes allowed:** none.
- **Behavioral changes prohibited:** all product, API, schema, authorization, conversation-path, and UI behavior changes.

## Changes

- **Implemented:**
  - Hardened `.gitignore` coverage for environment variants, SQLite companions, all `.venv*` directories, `.pytest_tmp`, and local runtime/checkpoint folders while explicitly allowing safe environment examples.
  - Added `.gitattributes`, `.python-version` (`3.12`), and `.nvmrc` (`20`).
  - Added exact Python runtime and development locks. The optional POSIX `uvloop` pin is platform-gated; its selected `0.22.1` release was cross-checked against [PyPI](https://pypi.org/project/uvloop/).
  - Pointed the root Python wrapper and CI installs at exact locks, and added exact installed-version verification.
  - Corrected safe verification examples: PostgreSQL for `ENV=verification`, empty credential fields, fail-closed feature flags, explicit V2 engines, and a valid loopback frontend origin.
  - Added a stdlib-only repository hygiene gate that scans every Git source candidate, suppresses matched values, validates ignore/example/lock contracts, and optionally inventories local artifacts by aggregate count and bytes only.
  - Added an exact Python lock-parity gate.
  - Refreshed only `backend/package-lock.json` within existing semver ranges; npm audit changed from six findings to zero without a manifest change.
  - Added CI secret/artifact checks, exact-lock checks, backend/gateway dependency audits, and a frontend production-dependency audit.
  - Added reproducible setup, backup-first local-artifact handling, contributor, security, README, PR, and documentation-index guidance.
- **Files/modules changed:**
  - Added before this report: `.gitattributes`, `.nvmrc`, `.python-version`, `backend/requirements.lock`, `backend/requirements-dev.lock`, `docs/setup/LOCAL_SETUP.md`, `docs/security/LOCAL_ARTIFACT_HANDLING.md`, `tools/check_repository_hygiene.py`, and `tools/verify_locked_python.py`.
  - Modified: `.gitignore`, `backend/.gitignore`, `backend/.env.verification.example`, `frontend/.env.verification.example`, `requirements.txt`, `backend/package-lock.json`, `.github/workflows/ci.yml`, `.github/pull_request_template.md`, `README.md`, `CONTRIBUTING.md`, `SECURITY.md`, and `docs/README.md`.
  - Added by the final reporting step: this report.
- **Data/schema impact:** NONE on existing data. One new SQLite database was created outside the repository in the isolated verification workspace, migrated to `f9a8b7c6d5e4`, and seeded only with the repository's synthetic ARVENA fixture. No existing database, session, log, or user record was read for content, moved, altered, or deleted.
- **External services affected:** PyPI/npm registry access was used for dependency installation and advisory checks. No AI, Meta, WhatsApp, Redis, database, email, payment, or other product integration credentials were used. Redis/provider absence was exercised through the documented degraded local fallback.

## Verification

- **Commands/procedures:**

  | Check | Repeatable command/procedure | Result |
  |---|---|---|
  | Source hygiene and local inventory | `python tools/check_repository_hygiene.py --inventory-local` | PASS. Final report-inclusive rerun: 341 source candidates; 8 digest-allowlisted synthetic fixture matches; no value printed. |
  | Scanner negative control | Inserted a temporary synthetic provider-token probe, captured output, asserted exit `1`, asserted `value suppressed`, asserted the value was absent, then removed the probe | PASS. `HYGIENE_NEGATIVE_TEST=PASS`. |
  | Clean Python install | New Python 3.12 venv outside source; `python -m pip install -r backend/requirements-dev.lock` | PASS. Exact lock resolved and installed. |
  | Python environment | `python -m pip check`; `python tools/verify_locked_python.py` | PASS. No broken requirements; 87 active exact pins matched. |
  | Backend suite | From the clean install: `python -m pytest -q` | PASS. `1940 passed`, `161 warnings`, `252.75s`. Warnings are documented deprecations, not test failures. |
  | Frontend clean install | From the source-only export: `npm ci` | PASS. 353 packages added; lock accepted without rewrite. |
  | Frontend contracts | `npm test` | PASS. `47/47`. |
  | Frontend lint/build | `npm run lint`; `npm run build` | PASS. ESLint exit `0`; Vite transformed `2283` modules. |
  | Frontend dependency boundary | `npm audit --omit=dev --audit-level=high` | PASS. Zero production dependency findings. |
  | Frontend full development audit | `npm audit --json` | PASS WITH KNOWN LIMITATION. Two vulnerable packages remain: one moderate and one high, in Vite/esbuild development tooling; the offered fix is a Vite major upgrade. |
  | Gateway clean install/audit | `npm ci --ignore-scripts`; `npm audit --audit-level=high` | PASS after reviewed lock-only refresh. 201 packages added; zero findings. |
  | Gateway syntax | `node --check whatsapp_gate.js` | PASS. |
  | CI/config structure | YAML parse; JSON parse and manifest/lock parity inside hygiene gate | PASS. |
  | Fresh schema and seed | Set isolated local environment; `python -m alembic upgrade head`; gated `python scripts/seed_trusted_demo_tenant.py` | PASS. Head `f9a8b7c6d5e4`; synthetic company `velor_demo_arvena`; slug `arvena-demo`; owner access disabled. |
  | Application/demo startup smoke | FastAPI `TestClient` startup against the isolated seeded DB; GET `/health`, GET `/ready`, POST `/api/public/companies/arvena-demo/session` | PASS. HTTP `200` for all; database compatible; engine V2; fallback available; visitor assigned. The session token was deliberately not printed. |
  | Source-only recovery checkpoints | Copy each source candidate outside the repository, compare SHA-256 per file, then hash the sorted manifest | PASS. Both baseline and implementation checkpoint copies were hash-verified. |

- **Results:** the bounded technical path `source-only export → configure runtime-only secrets/placeholders → exact installs → migrate isolated DB → seed synthetic demo → start application → reach public demo session → run checks` is repeatable and passed.
- **Known limitations:**
  - The literal `git clone` step is NOT DEMONSTRATED because the repository has no commit. The source-only export is a substitute verification, not evidence of a clone.
  - GitHub Actions, Linux Python 3.11/3.12, and the PostgreSQL 16 service job were configured but NOT RUN in this local session.
  - Windows Python 3.12 was the clean local Python runtime. The POSIX-only `uvloop` marker was not installed locally.
  - The frontend development audit is not clean; production dependency audit is clean.
  - Aggregate local inventory found one unreadable test-cache location. Its contents remain an explicit blind spot.
  - Secret scanning covered current Git source candidates. With no remote/history, it cannot prove that another copy or future public history is clean.

## Status distinctions

- **Implemented:** YES — exact locks, safe examples, ignore rules, hygiene/lock gates, CI baseline, setup and artifact-handling documentation, and a seeded path exist in the inspected source.
- **Tested:** YES, WITH KNOWN LIMITATIONS — clean installs, backend/frontend suites, lint/build, audits, migration, startup, and scanner controls passed locally; GitHub/Linux/PostgreSQL CI did not run.
- **Demonstrated:** YES, WITH KNOWN LIMITATION — a reviewer can reproduce the documented source-export flow and reach the isolated `arvena-demo` session. A literal clone is not demonstrated.
- **Production-ready:** NO — local reproducibility does not prove deployment security, operations, backups, monitoring, provider readiness, compliance, support, or public-release governance.
- **Market evidence:** EXTERNAL EVIDENCE REQUIRED. No interviews, pilot usage, payment, retention, or business outcome was inferred from this phase.

## Risks and unresolved work

- **High-risk items:**
  - Real local environment values identified in Phase 0 remain outside Git but inside a OneDrive-synced tree. Ignore rules do not stop cloud sync or revoke credentials.
  - Local runtime inventory currently includes 4 non-example environment files (1,582 bytes), 47 database artifacts (111,723,120 bytes), 76 logs (1,008,998 bytes), 1,704 session files (335,810 bytes), 30,016 virtual-environment files (770,339,160 bytes), and 5 test-cache files (28,402 bytes). One test-cache read error remains. Counts are aggregate; names and contents were suppressed.
  - The frontend development server/toolchain has a high-severity advisory path and must not be treated as a trusted exposed service. The compatible fix offered by npm is a major Vite upgrade and was not taken without product compatibility work.
  - There is no Git commit, remote, selected public license, or configured author identity. Publication is not authorized or demonstrated.
- **Follow-ups for a future bounded Phase 1 closure session:**
  - The owner selects a license and Git author identity, reviews the 341 report-inclusive source candidates, creates the initial commit, and runs a real clean clone verification.
  - Run the committed GitHub Actions matrix, including PostgreSQL 16 and both Python versions.
  - Evaluate the Vite major upgrade with frontend compatibility tests before changing the manifest.
  - Decide whether local runtime artifacts should move out of OneDrive; if authorized, follow the documented copy-first, hash-verify, restore-test procedure before removing originals.
  - Enable host-side repository secret scanning/dependency alerts after a remote exists, and complete any provider-side credential rotation identified from Phase 0.
- **Items requiring user or external evidence:** public license choice, Git identity/remote ownership, approved secure storage/retention destination, provider-side rotation confirmation, and all market evidence.

## Checkpoint and rollback

- **Baseline checkpoint:** `<RECOVERABLE_CHECKPOINT>`; 331 safe checkpoint files including metadata; aggregate SHA-256 `6923fb1d328dec01cb7da0bafadb5483d939f8dcba9cb9bc3df69dbc76a743dd`.
- **Current checkpoint/commit:** no Git commit exists. The final implementation-only source checkpoint is `<RECOVERABLE_CHECKPOINT>`; 340 source files, excluding this report by design; aggregate SHA-256 `76ae1307bee96be7f3f685e33374999f52696c6fe73d7d2aacbba0d629e9514a`.
- **Rollback procedure:** do not reset Git or touch runtime artifacts. Review the 12 modified source files against the verified baseline checkpoint, restore only the selected source files, and remove the 9 Phase 1 source additions plus this report only if explicitly authorized. Re-run hygiene and all relevant checks. Existing sessions, databases, logs, environment files, and user data are not rollback targets.
- **Rollback tested:** NO. Checkpoint creation and per-file copy hashes were tested; an actual restoration was not performed because it would undo the requested implementation.

## Next allowed action

- STOP. Phase 2 is NOT started automatically. The only next work implied by this report is a separately authorized bounded Phase 1 closure for owner-controlled Git/publication decisions or another phase explicitly assigned by the user.
