from jose import jwt

from database import Company, CompanyKnowledge, hash_api_key


JWT_SECRET = "super-secret-test-key-32-chars-long"


def _token(company_id, role="tenant"):
    return jwt.encode(
        {"company_id": company_id, "role": role, "token_type": "access"},
        JWT_SECRET,
        algorithm="HS256",
    )


def _seed_company(db, company_id, knowledge_base):
    company = Company(
        company_id=company_id,
        company_name=f"{company_id} Company",
        email=f"{company_id}@example.com",
        password="hashed",
        api_key_hash=hash_api_key(f"{company_id}-api-key"),
        plan="PRO",
    )
    db.add(company)
    db.add(
        CompanyKnowledge(
            company_id=company_id,
            system_prompt="Original prompt",
            products_data='[{"name":"Original Product","price":"100 EGP"}]',
            welcome_message="Original welcome",
            industry="Original industry",
            tone="professional",
            language="Arabic",
            lead_collection=True,
            knowledge_base=knowledge_base,
        )
    )
    db.commit()
    return company_id


def _settings_payload(**overrides):
    payload = {
        "company_name": "Updated Company",
        "industry": "Updated industry",
        "tone": "friendly",
        "welcome_message": "Updated welcome",
        "system_prompt": "Updated assistant prompt",
        "products_data": '[{"name":"Updated Product","price":"6900 EGP"}]',
        "language": "Arabic",
        "lead_collection": True,
    }
    payload.update(overrides)
    return payload


def test_knowledge_survives_settings_update(client, db):
    company_id = _seed_company(db, "settings_preserve_one", "ARVENA_CATALOG_SENTINEL_6900")

    response = client.post(
        "/whatsapp/settings/update",
        json=_settings_payload(),
        cookies={"access_token": _token(company_id)},
    )

    assert response.status_code == 200
    knowledge = db.query(CompanyKnowledge).filter(CompanyKnowledge.company_id == company_id).one()
    assert knowledge.knowledge_base == "ARVENA_CATALOG_SENTINEL_6900"


def test_upload_like_knowledge_survives_multiple_settings_saves(client, db):
    catalog = "Arvena Ergo One | 6900 EGP\nFocusDesk 120 | 8500 EGP"
    company_id = _seed_company(db, "settings_preserve_repeated", catalog)

    first = client.post(
        "/whatsapp/settings/update",
        json=_settings_payload(tone="luxury"),
        cookies={"access_token": _token(company_id)},
    )
    second = client.post(
        "/whatsapp/settings/update",
        json=_settings_payload(industry="Workspace furniture"),
        cookies={"access_token": _token(company_id)},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    knowledge = db.query(CompanyKnowledge).filter(CompanyKnowledge.company_id == company_id).one()
    assert knowledge.knowledge_base == catalog


def test_settings_update_preserves_cross_company_knowledge_isolation(client, db):
    company_a_id = _seed_company(db, "settings_preserve_company_a", "Company A catalog")
    company_b_id = _seed_company(db, "settings_preserve_company_b", "Company B catalog")

    response = client.post(
        "/whatsapp/settings/update",
        json=_settings_payload(company_name="Only Company A Updated"),
        cookies={"access_token": _token(company_a_id)},
    )

    assert response.status_code == 200
    knowledge_a = db.query(CompanyKnowledge).filter(CompanyKnowledge.company_id == company_a_id).one()
    knowledge_b = db.query(CompanyKnowledge).filter(CompanyKnowledge.company_id == company_b_id).one()
    assert knowledge_a.knowledge_base == "Company A catalog"
    assert knowledge_b.knowledge_base == "Company B catalog"


def test_settings_fields_still_update_while_preserving_knowledge(client, db):
    company_id = _seed_company(db, "settings_preserve_fields", "Catalog must remain")

    response = client.post(
        "/whatsapp/settings/update",
        json=_settings_payload(
            tone="sales",
            system_prompt="New strict prompt",
            products_data='[{"name":"Arvena Ergo One","price":"6900 EGP"}]',
        ),
        cookies={"access_token": _token(company_id)},
    )

    assert response.status_code == 200
    knowledge = db.query(CompanyKnowledge).filter(CompanyKnowledge.company_id == company_id).one()
    assert knowledge.knowledge_base == "Catalog must remain"
    assert knowledge.tone == "sales"
    assert knowledge.system_prompt == "New strict prompt"
    assert knowledge.products_data == '[{"name":"Arvena Ergo One","price":"6900 EGP"}]'


def test_repeated_settings_saves_do_not_create_duplicate_company_knowledge_rows(client, db):
    company_id = _seed_company(db, "settings_preserve_no_duplicates", "Single row catalog")

    for tone in ["friendly", "professional", "sales"]:
        response = client.post(
            "/whatsapp/settings/update",
            json=_settings_payload(tone=tone),
            cookies={"access_token": _token(company_id)},
        )
        assert response.status_code == 200

    rows = db.query(CompanyKnowledge).filter(CompanyKnowledge.company_id == company_id).all()
    assert len(rows) == 1
    assert rows[0].knowledge_base == "Single row catalog"
    assert rows[0].tone == "sales"


def test_knowledge_upload_path_still_updates_knowledge_base(client, db):
    company_id = _seed_company(db, "settings_preserve_upload", "Existing catalog")

    response = client.post(
        "/api/v1/knowledge/upload",
        files={"file": ("catalog.txt", b"Uploaded catalog line", "text/plain")},
        cookies={"access_token": _token(company_id)},
    )

    assert response.status_code == 200
    knowledge = db.query(CompanyKnowledge).filter(CompanyKnowledge.company_id == company_id).one()
    assert "Existing catalog" in knowledge.knowledge_base
    assert "Uploaded catalog line" in knowledge.knowledge_base
