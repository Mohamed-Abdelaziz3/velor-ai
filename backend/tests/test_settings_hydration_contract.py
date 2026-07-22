import json

from jose import jwt

from database import Company, CompanyKnowledge, hash_api_key


JWT_SECRET = "super-secret-test-key-32-chars-long"


def _token(company_id, role="tenant"):
    return jwt.encode(
        {"company_id": company_id, "role": role, "token_type": "access"},
        JWT_SECRET,
        algorithm="HS256",
    )


def _seed_company(db, company_id, *, knowledge_base="", products_data="[]"):
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
            products_data=products_data,
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
        "company_name": "Hydrated Company",
        "industry": "Workspace furniture",
        "tone": "friendly",
        "welcome_message": "Welcome back",
        "system_prompt": "Use only configured facts.",
        "products_data": json.dumps(
            [
                {"name": "Arvena Ergo One", "price": 6900},
                {"name": "Arvena Ergo Pro", "price": 10900},
            ]
        ),
        "language": "Arabic",
        "lead_collection": True,
    }
    payload.update(overrides)
    return payload


def _get_settings(client, company_id):
    response = client.get("/whatsapp/settings", cookies={"access_token": _token(company_id)})
    assert response.status_code == 200
    return response.json()["knowledge"]


def test_persisted_settings_round_trip(client, db):
    company_id = _seed_company(db, "settings_hydration_roundtrip")

    save = client.post(
        "/whatsapp/settings/update",
        json=_settings_payload(),
        cookies={"access_token": _token(company_id)},
    )

    assert save.status_code == 200
    knowledge = _get_settings(client, company_id)
    assert knowledge["company_name"] == "Hydrated Company"
    assert knowledge["industry"] == "Workspace furniture"
    assert knowledge["tone"] == "friendly"
    assert knowledge["welcome_message"] == "Welcome back"
    assert knowledge["system_prompt"] == "Use only configured facts."
    assert json.loads(knowledge["products_data"]) == [
        {"name": "Arvena Ergo One", "price": 6900},
        {"name": "Arvena Ergo Pro", "price": 10900},
    ]


def test_get_settings_reports_existing_knowledge_without_raw_text(client, db):
    company_id = _seed_company(db, "settings_hydration_has_kb", knowledge_base="Private catalog data")

    knowledge = _get_settings(client, company_id)

    assert knowledge["has_knowledge"] is True
    assert knowledge["knowledge_size"] == len("Private catalog data")
    assert "knowledge_base" not in knowledge


def test_get_settings_reports_no_knowledge(client, db):
    company_id = _seed_company(db, "settings_hydration_no_kb", knowledge_base="")

    knowledge = _get_settings(client, company_id)

    assert knowledge["has_knowledge"] is False
    assert knowledge["knowledge_size"] == 0
    assert "knowledge_base" not in knowledge


def test_settings_update_preserves_previous_p0_knowledge_sentinel(client, db):
    company_id = _seed_company(
        db,
        "settings_hydration_preserve_p0",
        knowledge_base="ARVENA_CATALOG_SENTINEL_6900",
    )

    save = client.post(
        "/whatsapp/settings/update",
        json=_settings_payload(tone="sales"),
        cookies={"access_token": _token(company_id)},
    )
    knowledge = _get_settings(client, company_id)
    db_row = db.query(CompanyKnowledge).filter(CompanyKnowledge.company_id == company_id).one()

    assert save.status_code == 200
    assert knowledge["has_knowledge"] is True
    assert db_row.knowledge_base == "ARVENA_CATALOG_SENTINEL_6900"


def test_get_settings_is_company_scoped(client, db):
    company_a = _seed_company(
        db,
        "settings_hydration_company_a",
        knowledge_base="Company A knowledge",
        products_data='[{"name":"A Product","price":100}]',
    )
    company_b = _seed_company(
        db,
        "settings_hydration_company_b",
        knowledge_base="Company B knowledge",
        products_data='[{"name":"B Product","price":200}]',
    )

    update_a = client.post(
        "/whatsapp/settings/update",
        json=_settings_payload(company_name="Company A Updated", tone="sales"),
        cookies={"access_token": _token(company_a)},
    )
    update_b = client.post(
        "/whatsapp/settings/update",
        json=_settings_payload(company_name="Company B Updated", tone="luxury"),
        cookies={"access_token": _token(company_b)},
    )

    assert update_a.status_code == 200
    assert update_b.status_code == 200
    settings_a = _get_settings(client, company_a)
    settings_b = _get_settings(client, company_b)
    assert settings_a["company_name"] == "Company A Updated"
    assert settings_a["tone"] == "sales"
    assert settings_a["has_knowledge"] is True
    assert settings_b["company_name"] == "Company B Updated"
    assert settings_b["tone"] == "luxury"
    assert settings_b["has_knowledge"] is True


def test_arabic_settings_round_trip(client, db):
    company_id = _seed_company(db, "settings_hydration_arabic")
    system_prompt = "التزم ببيانات الكتالوج فقط.\nلا تخترع أسعار أو خصومات."

    save = client.post(
        "/whatsapp/settings/update",
        json=_settings_payload(
            company_name="أرفينا لمساحات العمل",
            industry="تجهيز المكاتب ومساحات العمل",
            welcome_message="أهلًا بيك، أقدر أساعدك تختار المنتج المناسب.",
            system_prompt=system_prompt,
            tone="professional",
        ),
        cookies={"access_token": _token(company_id)},
    )

    assert save.status_code == 200
    knowledge = _get_settings(client, company_id)
    assert knowledge["company_name"] == "أرفينا لمساحات العمل"
    assert knowledge["industry"] == "تجهيز المكاتب ومساحات العمل"
    assert knowledge["welcome_message"] == "أهلًا بيك، أقدر أساعدك تختار المنتج المناسب."
    assert knowledge["system_prompt"] == system_prompt
    assert knowledge["tone"] == "professional"


def test_products_hydration_preserves_multiple_products(client, db):
    company_id = _seed_company(db, "settings_hydration_products")
    products = [
        {"name": "Arvena Ergo One", "price": 6900},
        {"name": "Arvena Ergo Pro", "price": 10900},
    ]

    save = client.post(
        "/whatsapp/settings/update",
        json=_settings_payload(products_data=json.dumps(products)),
        cookies={"access_token": _token(company_id)},
    )

    assert save.status_code == 200
    knowledge = _get_settings(client, company_id)
    assert json.loads(knowledge["products_data"]) == products


def test_repeated_save_reload_uses_latest_values_and_preserves_knowledge(client, db):
    company_id = _seed_company(
        db,
        "settings_hydration_repeated",
        knowledge_base="Arvena Ergo One | 6900 EGP",
    )

    first = client.post(
        "/whatsapp/settings/update",
        json=_settings_payload(company_name="Config A", tone="friendly"),
        cookies={"access_token": _token(company_id)},
    )
    first_get = _get_settings(client, company_id)
    second = client.post(
        "/whatsapp/settings/update",
        json=_settings_payload(company_name="Config B", tone="sales"),
        cookies={"access_token": _token(company_id)},
    )
    second_get = _get_settings(client, company_id)
    db_row = db.query(CompanyKnowledge).filter(CompanyKnowledge.company_id == company_id).one()

    assert first.status_code == 200
    assert second.status_code == 200
    assert first_get["company_name"] == "Config A"
    assert first_get["tone"] == "friendly"
    assert second_get["company_name"] == "Config B"
    assert second_get["tone"] == "sales"
    assert second_get["has_knowledge"] is True
    assert db_row.knowledge_base == "Arvena Ergo One | 6900 EGP"
