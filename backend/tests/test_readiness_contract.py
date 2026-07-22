import pytest
from jose import jwt

import main as api_main
from database import Company, hash_api_key
from main import get_public_web_chat_engine, validate_runtime_configuration
from services.conversation_engine_config import get_external_api_response_engine


def _token(company_id: str, role: str = "tenant") -> str:
    return jwt.encode(
        {"company_id": company_id, "role": role, "token_type": "access"},
        "super-secret-test-key-32-chars-long",
        algorithm="HS256",
    )


def test_health_is_liveness_only(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "3.0.0"}


def test_public_engine_has_one_control_and_v2_default(monkeypatch):
    monkeypatch.delenv("PUBLIC_WEB_CHAT_RESPONSE_ENGINE", raising=False)
    monkeypatch.setenv("ENABLE_PUBLIC_CHAT_V2", "false")
    assert get_public_web_chat_engine() == "v2"
    monkeypatch.setenv("PUBLIC_WEB_CHAT_RESPONSE_ENGINE", "v1")
    assert get_public_web_chat_engine() == "v1"
    monkeypatch.setenv("PUBLIC_WEB_CHAT_RESPONSE_ENGINE", "invalid")
    with pytest.raises(ValueError):
        validate_runtime_configuration()


def test_external_api_uses_v2_by_default_with_explicit_v1_rollback(monkeypatch):
    monkeypatch.delenv("EXTERNAL_API_RESPONSE_ENGINE", raising=False)
    assert get_external_api_response_engine() == "v2"
    monkeypatch.setenv("EXTERNAL_API_RESPONSE_ENGINE", "v1")
    assert get_external_api_response_engine() == "v1"


@pytest.mark.parametrize(
    "rollback_setting",
    [
        "PUBLIC_WEB_CHAT_RESPONSE_ENGINE",
        "WHATSAPP_RESPONSE_ENGINE",
        "EXTERNAL_API_RESPONSE_ENGINE",
    ],
)
def test_release_configuration_rejects_every_v1_rollback(monkeypatch, rollback_setting):
    monkeypatch.setattr(api_main, "ENV", "staging")
    monkeypatch.setenv("PUBLIC_WEB_CHAT_RESPONSE_ENGINE", "v2")
    monkeypatch.setenv("WHATSAPP_RESPONSE_ENGINE", "v2")
    monkeypatch.setenv("EXTERNAL_API_RESPONSE_ENGINE", "v2")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://velor:test@db/velor")
    monkeypatch.setenv("ALLOWED_HOSTS", "app.velor.example")
    monkeypatch.setenv(rollback_setting, "v1")

    with pytest.raises(ValueError, match="Release environments require"):
        validate_runtime_configuration()


def test_release_configuration_accepts_v2_with_postgres_and_explicit_host(monkeypatch):
    monkeypatch.setattr(api_main, "ENV", "staging")
    monkeypatch.setenv("PUBLIC_WEB_CHAT_RESPONSE_ENGINE", "v2")
    monkeypatch.setenv("WHATSAPP_RESPONSE_ENGINE", "v2")
    monkeypatch.setenv("EXTERNAL_API_RESPONSE_ENGINE", "v2")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://velor:test@db/velor")
    monkeypatch.setenv("ALLOWED_HOSTS", "app.velor.example,api.velor.example")
    monkeypatch.setenv("ENABLE_META_WEBHOOK", "false")

    validate_runtime_configuration()


def test_readiness_is_degraded_when_provider_is_unavailable(client, monkeypatch):
    monkeypatch.setattr(
        "database.get_database_runtime_summary",
        lambda **_: {
            "schema_compatible": True,
            "database_dialect": "sqlite",
            "current_revision": "head",
            "migration_head": "head",
        },
    )
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setenv("PUBLIC_WEB_CHAT_RESPONSE_ENGINE", "v2")

    response = client.get("/ready")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "degraded"
    assert payload["database"] == "compatible"
    assert payload["engine_version"] == "v2"
    assert payload["provider_available"] is False
    assert payload["fallback_available"] is True
    assert payload["rate_limiter_mode"] in {"redis", "local"}
    assert payload["redis_required"] is False


def test_readiness_fails_closed_when_database_is_incompatible(client, monkeypatch):
    monkeypatch.setattr(
        "database.get_database_runtime_summary",
        lambda **_: {"schema_compatible": False, "database_dialect": "sqlite"},
    )

    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["database"] == "incompatible"


def test_admin_readiness_requires_auth_and_exposes_only_sanitized_diagnostics(client, db, monkeypatch):
    company = Company(
        company_id="ready_company",
        company_name="Ready Company",
        email="ready@example.com",
        password="hashed",
        api_key_hash=hash_api_key("ready-api-key"),
        plan="PRO",
        role="super_admin",
    )
    db.add(company)
    db.commit()
    company_id = company.company_id
    monkeypatch.setattr(
        "database.get_database_runtime_summary",
        lambda **_: {
            "schema_compatible": True,
            "database_dialect": "sqlite",
            "database_target": "ready.db",
        },
    )
    monkeypatch.setenv("PUBLIC_WEB_CHAT_RESPONSE_ENGINE", "v2")
    monkeypatch.setenv("GROQ_API_KEY", "replace-with-secret")

    assert client.get("/api/v1/admin/readiness").status_code in {401, 403}
    response = client.get(
        "/api/v1/admin/readiness",
        cookies={"access_token": _token(company_id, role="super_admin")},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "degraded"
    assert payload["company_id"] == company_id
    assert payload["details"]["provider"]["fallback_active"] is True
    serialized = response.text.casefold()
    assert "replace-with-secret" not in serialized
    assert "api_key" not in serialized
    assert "prompt" not in serialized
