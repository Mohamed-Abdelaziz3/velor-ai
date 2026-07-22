## What changed?

<!-- Explain the user problem and the smallest solution implemented. -->

## How was it verified?

- [ ] Hygiene: `python tools/check_repository_hygiene.py`
- [ ] Python lock parity: `python tools/verify_locked_python.py`
- [ ] Backend: `python -m pytest -q`
- [ ] Frontend: `npm test`
- [ ] Frontend: `npm run lint`
- [ ] Frontend: `npm run build`
- [ ] Frontend production dependencies: `npm audit --omit=dev --audit-level=high`
- [ ] WhatsApp gateway (if touched): `node --check whatsapp_gate.js`
- [ ] WhatsApp gateway dependencies: `npm audit --audit-level=high`

## Release and risk check

- [ ] No secrets, `.env` files, databases, logs, or customer data are included.
- [ ] Tenant isolation and authorization were considered for backend changes.
- [ ] Metrics and UI states are sourced and not presented as fabricated facts.
- [ ] Schema changes include an Alembic migration and migration test.
- [ ] New environment variables are documented with safe empty/default examples.
- [ ] Dependency changes include reviewed lockfile updates from the supported toolchain.
- [ ] Arabic RTL, mobile, loading, empty, and error states were checked for UI changes.

## Evidence

<!-- Link the issue. Add sanitized screenshots only when the change is visual. -->
