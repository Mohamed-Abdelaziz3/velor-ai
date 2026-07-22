import uuid

from database import Company


def _identity(prefix: str) -> tuple[str, str]:
    token = uuid.uuid4().hex[:12]
    return f"{prefix}-{token}", f"{prefix}-{token}@example.com"


def _signup_payload(name: str, email: str) -> dict:
    return {
        "company_name": name,
        "email": email,
        "password": "StrongPass123!",
        "terms_accepted": True,
    }


def test_public_signup_rejects_plan_escalation(client, db):
    name, email = _identity("plan-escalation")
    response = client.post(
        "/signup",
        json={**_signup_payload(name, email), "plan": "ENTERPRISE"},
    )

    assert response.status_code == 422
    assert db.query(Company).filter(Company.email == email).first() is None


def test_public_signup_can_only_create_free_tenant(client, db):
    name, email = _identity("free-signup")
    response = client.post(
        "/signup",
        json=_signup_payload(name, email),
    )

    assert response.status_code == 200
    company = db.query(Company).filter(Company.email == email).first()
    assert company is not None
    assert company.plan == "FREE"
    assert company.auth_provider == "password"
    assert company.google_subject is None
    assert company.terms_accepted_at is not None
    assert company.terms_version == "2026-07-15"
    assert company.privacy_version == "2026-07-15"

    login = client.post("/login", json={"email": email, "password": "StrongPass123!"})
    assert login.status_code == 200
    assert "access_token" not in login.json()
    assert client.cookies.get("access_token")
    assert client.cookies.get("refresh_token")


def test_refresh_rotates_session_and_cross_site_mutation_is_blocked(client):
    name, email = _identity("refresh-session")
    assert client.post(
        "/signup",
        json=_signup_payload(name, email),
    ).status_code == 200
    assert client.post(
        "/login", json={"email": email, "password": "StrongPass123!"}
    ).status_code == 200

    old_refresh = client.cookies.get("refresh_token")
    refreshed = client.post("/token/refresh")
    assert refreshed.status_code == 200
    assert client.cookies.get("refresh_token") != old_refresh
    assert client.get("/me").status_code == 200

    blocked = client.post("/logout", headers={"Origin": "https://attacker.invalid"})
    assert blocked.status_code == 403
    assert client.get("/me").status_code == 200


def test_tenant_cannot_read_admin_readiness(client):
    name, email = _identity("readiness-tenant")
    assert client.post(
        "/signup",
        json=_signup_payload(name, email),
    ).status_code == 200
    assert client.post(
        "/login", json={"email": email, "password": "StrongPass123!"}
    ).status_code == 200

    response = client.get("/api/v1/admin/readiness")
    assert response.status_code == 403


def test_google_login_does_not_silently_merge_password_identity(client, db, monkeypatch):
    name, email = _identity("identity-conflict")
    signup = client.post(
        "/signup",
        json=_signup_payload(name, email),
    )
    assert signup.status_code == 200

    monkeypatch.setenv("GOOGLE_CLIENT_ID", "configured-client-id")
    monkeypatch.setattr(
        "google.oauth2.id_token.verify_oauth2_token",
        lambda *_args, **_kwargs: {
            "sub": f"google-{uuid.uuid4().hex}",
            "email": email,
            "email_verified": True,
            "name": name,
        },
    )

    response = client.post(
        "/auth/google",
        json={"token": "verified-token", "terms_accepted": True},
    )

    assert response.status_code == 409
    company = db.query(Company).filter(Company.email == email).one()
    assert company.auth_provider == "password"
    assert company.google_subject is None


def test_google_signup_requires_verified_email_and_links_subject(client, db, monkeypatch):
    name, email = _identity("google-signup")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "configured-client-id")
    claims = {
        "sub": f"google-{uuid.uuid4().hex}",
        "email": email,
        "email_verified": False,
        "name": name,
    }
    monkeypatch.setattr(
        "google.oauth2.id_token.verify_oauth2_token",
        lambda *_args, **_kwargs: claims,
    )

    denied = client.post("/auth/google", json={"token": "unverified-token"})
    assert denied.status_code == 400
    assert db.query(Company).filter(Company.email == email).first() is None

    claims["email_verified"] = True
    missing_consent = client.post("/auth/google", json={"token": "verified-token"})
    assert missing_consent.status_code == 400
    assert db.query(Company).filter(Company.email == email).first() is None

    created = client.post(
        "/auth/google",
        json={"token": "verified-token", "terms_accepted": True},
    )
    assert created.status_code == 200
    assert "access_token" not in created.json()
    company = db.query(Company).filter(Company.email == email).one()
    assert company.plan == "FREE"
    assert company.auth_provider == "google"
    assert company.google_subject == claims["sub"]
    assert company.terms_accepted_at is not None
    assert company.terms_version == "2026-07-15"
    assert company.privacy_version == "2026-07-15"

    repeated = client.post("/auth/google", json={"token": "verified-token"})
    assert repeated.status_code == 200
    assert repeated.json()["is_new_user"] is False


def test_password_signup_requires_explicit_legal_consent(client, db):
    name, email = _identity("missing-consent")
    payload = _signup_payload(name, email)
    payload.pop("terms_accepted")

    missing = client.post("/signup", json=payload)
    assert missing.status_code == 422
    assert db.query(Company).filter(Company.email == email).first() is None

    payload["terms_accepted"] = False
    denied = client.post("/signup", json=payload)
    assert denied.status_code == 422
    assert db.query(Company).filter(Company.email == email).first() is None
