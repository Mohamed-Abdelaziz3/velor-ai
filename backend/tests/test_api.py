def test_app_import():
    from main import app

    assert app is not None
    assert app.title == "VELOR API"


def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_login_missing_fields(client):
    response = client.post("/login", json={"email": "missing-password@test.com"})
    assert response.status_code in [401, 422]


def test_unauthorized_dashboard_access(client):
    response = client.get("/stats")
    # Should block access without token
    assert response.status_code == 403 or response.status_code == 401


def test_unauthorized_engine_access(client):
    response = client.get("/api/engine/priorities")
    assert response.status_code == 403 or response.status_code == 401


def test_unauthorized_whatsapp_status(client):
    response = client.get("/whatsapp/status")
    assert response.status_code == 403 or response.status_code == 401


def test_internal_company_exists_endpoint(client, db):
    from database import Company, hash_api_key

    company = Company(
        company_id="existing_company",
        company_name="Existing Company",
        email="existing@example.com",
        password="hashed",
        api_key_hash=hash_api_key("existing-api-key"),
        plan="PRO",
    )
    db.add(company)
    db.commit()

    headers = {"X-Internal-Secret": "secret"}
    found = client.get("/api/internal/companies/existing_company/exists", headers=headers)
    missing = client.get("/api/internal/companies/missing_company/exists", headers=headers)

    assert found.status_code == 200
    assert found.json()["exists"] is True
    assert missing.status_code == 404


def test_update_company_daily_target(client, db):
    from jose import jwt

    from database import Company, SessionLocal, hash_api_key

    company = Company(
        company_id="target_company",
        company_name="Target Company",
        email="target@example.com",
        password="hashed",
        api_key_hash=hash_api_key("target-api-key"),
        plan="PRO",
    )
    db.add(company)
    db.commit()

    token = jwt.encode(
        {"company_id": company.company_id, "role": "tenant", "token_type": "access"},
        "super-secret-test-key-32-chars-long",
        algorithm="HS256",
    )

    response = client.put("/api/company/target", json={"target": 12}, cookies={"access_token": token})

    assert response.status_code == 200
    assert response.json() == {"success": True, "daily_target": 12}

    check_db = SessionLocal()
    try:
        saved_company = check_db.query(Company).filter(Company.company_id == "target_company").first()
        assert saved_company.daily_sales_target == 12
    finally:
        check_db.close()

    stats_response = client.get("/stats", cookies={"access_token": token})
    assert stats_response.status_code == 200
    assert stats_response.json()["daily_target"] == 12
