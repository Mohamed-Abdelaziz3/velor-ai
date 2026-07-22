# Reproducible local setup

This guide builds VELOR from source using reviewed lockfiles. It is intended for
development and controlled verification, not as a production deployment guide.

## Supported toolchain

- Python 3.11 or 3.12 (`.python-version` selects 3.12)
- Node.js 20 (`.nvmrc`)
- npm 10 or newer
- Git

Use PostgreSQL for verification environments that set `ENV=verification`.
SQLite remains the local development and automated-test default only.

## Backend

From the repository root on PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r backend\requirements-dev.lock
if (-not (Test-Path backend\.env)) { Copy-Item backend\.env.example backend\.env }
```

Generate two different values locally and place them in `JWT_SECRET` and
`NODE_INTERNAL_SECRET` in `backend/.env`:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Do not paste those values into a terminal transcript, issue, commit, or CI file.
Then create the local schema and start the API:

```powershell
Set-Location backend
python -m alembic upgrade head
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

`GET /health` checks process health. `GET /ready` may be degraded when optional
providers are intentionally unset; degraded is not proof of production readiness.

For runtime-only installs use `backend/requirements.lock`. The bounded
`requirements*.txt` files state dependency policy; the exact `*.lock` files are
the reproducible install inputs used by CI.

## Frontend

In another PowerShell session:

```powershell
Set-Location frontend
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
npm ci
npm run dev
```

Open `http://127.0.0.1:5173`. `npm ci` uses the committed npm v3 lockfile and
must not rewrite it. Keep the frontend and backend hostnames aligned so browser
cookies behave consistently.

## Optional synthetic demo in an isolated database

The seeder is fail-closed. Run it only against a disposable development or
verification database that contains no customer data. Set the gate for that one
process, seed, and clear it:

```powershell
Set-Location backend
$env:ALLOW_SYNTHETIC_DEMO_SEED = "1"
python scripts\seed_trusted_demo_tenant.py
Remove-Item Env:ALLOW_SYNTHETIC_DEMO_SEED
```

Never enable this gate in a shared or production environment.

## Quality and hygiene gates

```powershell
python tools\check_repository_hygiene.py --inventory-local
python tools\verify_locked_python.py

Set-Location backend
python -m pytest -q
node --check whatsapp_gate.js

Set-Location ..\frontend
npm test
npm run lint
npm run build
npm audit --omit=dev --audit-level=high

Set-Location ..\backend
npm audit --audit-level=high
```

The inventory prints aggregate counts and sizes only. It never prints local
artifact names or secret values.

## Lockfile update rule

Change the bounded manifest first, regenerate the corresponding lock in a clean
environment, run the full gates above, and review the dependency diff. Do not
hand-edit a version merely to make CI pass. npm manifest changes must be followed
by `npm install --package-lock-only` using the supported Node/npm toolchain.

The frontend development toolchain currently requires a Vite major upgrade to
clear all development-only audit findings. That upgrade is not performed by this
setup phase because it needs compatibility testing. Production dependency audit
is the enforced frontend CI boundary until that work is explicitly authorized.
