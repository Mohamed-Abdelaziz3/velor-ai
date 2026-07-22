import os
import json
import pytest
from jose import jwt
from fastapi.testclient import TestClient

from main import app
from database import Company, CompanyKnowledge, hash_api_key

JWT_SECRET = "super-secret-test-key-32-chars-long"

FIXTURE_PATH = os.path.join(
    os.path.dirname(__file__), "fixtures", "ARVENA_Upload_Ready_Catalog.csv"
)


def _token(company_id, role="tenant"):
    return jwt.encode(
        {"company_id": company_id, "role": role, "token_type": "access"},
        JWT_SECRET,
        algorithm="HS256",
    )


def _seed_company(db, company_id):
    db.query(CompanyKnowledge).filter(CompanyKnowledge.company_id == company_id).delete()
    db.query(Company).filter(Company.company_id == company_id).delete()
    db.commit()

    company = Company(
        company_id=company_id,
        company_name=f"{company_id} Company",
        email=f"{company_id}@example.com",
        password="hashed",
        api_key_hash=hash_api_key(f"{company_id}-api-key"),
        plan="FREE",
    )
    db.add(company)
    db.commit()


def get_arvena_rich_catalog_json():
    from services.catalog_parser_service import parse_catalog_csv
    from services.catalog_merge_service import merge_catalogs

    with open(FIXTURE_PATH, "rb") as f:
        file_bytes = f.read()

    parse_result = parse_catalog_csv(file_bytes)
    src = {"source_type": "upload", "source_id": "arvena_fixture"}
    merged = merge_catalogs([], parse_result.records, src)
    return json.dumps(merged.records, ensure_ascii=False)


def assert_unsafe_catalog_replacement(res):
    assert res.status_code == 400
    data = res.json()
    msg = data.get("message") or data.get("detail")
    code = msg.get("code") if isinstance(msg, dict) else msg
    assert code == "UNSAFE_CATALOG_REPLACEMENT"


@pytest.fixture
def test_setup(db):
    company_id = "test_preservation_co"
    _seed_company(db, company_id)

    client = TestClient(app)
    client.cookies.set("access_token", _token(company_id))

    yield {"client": client, "db": db, "company_id": company_id}

    db.query(CompanyKnowledge).filter(CompanyKnowledge.company_id == company_id).delete()
    db.query(Company).filter(Company.company_id == company_id).delete()
    db.commit()


def test_omitted_products_preserve_raw_products_data_exactly(test_setup):
    db = test_setup["db"]
    client = test_setup["client"]
    company_id = test_setup["company_id"]

    arvena_json = get_arvena_rich_catalog_json()
    k = CompanyKnowledge(
        company_id=company_id,
        system_prompt="Initial Prompt",
        products_data=arvena_json,
        knowledge_base="KB Data",
        tone="professional"
    )
    db.add(k)
    db.commit()

    raw_before = db.query(CompanyKnowledge).filter(CompanyKnowledge.company_id == company_id).first().products_data

    res = client.post("/whatsapp/settings/update", json={
        "tone": "friendly",
        "company_name": "New Preservation Corp Name"
    })
    assert res.status_code == 200
    assert res.json()["success"] is True

    raw_after = db.query(CompanyKnowledge).filter(CompanyKnowledge.company_id == company_id).first().products_data
    assert raw_before == raw_after


def test_tone_only_save_preserves_rich_arvena_catalog(test_setup):
    db = test_setup["db"]
    client = test_setup["client"]
    company_id = test_setup["company_id"]

    arvena_json = get_arvena_rich_catalog_json()
    k = CompanyKnowledge(
        company_id=company_id,
        system_prompt="Initial Prompt",
        products_data=arvena_json,
        tone="professional"
    )
    db.add(k)
    db.commit()

    res = client.post("/whatsapp/settings/update", json={"tone": "casual"})
    assert res.status_code == 200

    updated_k = db.query(CompanyKnowledge).filter(CompanyKnowledge.company_id == company_id).first()
    assert updated_k.tone == "casual"
    assert updated_k.products_data == arvena_json


def test_company_name_only_save_preserves_rich_arvena_catalog(test_setup):
    db = test_setup["db"]
    client = test_setup["client"]
    company_id = test_setup["company_id"]

    arvena_json = get_arvena_rich_catalog_json()
    k = CompanyKnowledge(
        company_id=company_id,
        system_prompt="Initial Prompt",
        products_data=arvena_json,
        tone="professional"
    )
    db.add(k)
    db.commit()

    res = client.post("/whatsapp/settings/update", json={"company_name": "Arvena Furniture Co"})
    assert res.status_code == 200

    updated_k = db.query(CompanyKnowledge).filter(CompanyKnowledge.company_id == company_id).first()
    assert updated_k.products_data == arvena_json


def test_system_prompt_only_save_preserves_rich_arvena_catalog(test_setup):
    db = test_setup["db"]
    client = test_setup["client"]
    company_id = test_setup["company_id"]

    arvena_json = get_arvena_rich_catalog_json()
    k = CompanyKnowledge(
        company_id=company_id,
        system_prompt="Initial Prompt",
        products_data=arvena_json
    )
    db.add(k)
    db.commit()

    new_prompt = "New System Prompt for Arvena AI"
    res = client.post("/whatsapp/settings/update", json={"system_prompt": new_prompt})
    assert res.status_code == 200

    updated_k = db.query(CompanyKnowledge).filter(CompanyKnowledge.company_id == company_id).first()
    assert updated_k.system_prompt == new_prompt
    assert updated_k.products_data == arvena_json


def test_welcome_message_only_save_preserves_rich_arvena_catalog(test_setup):
    db = test_setup["db"]
    client = test_setup["client"]
    company_id = test_setup["company_id"]

    arvena_json = get_arvena_rich_catalog_json()
    k = CompanyKnowledge(
        company_id=company_id,
        system_prompt="Initial Prompt",
        products_data=arvena_json
    )
    db.add(k)
    db.commit()

    res = client.post("/whatsapp/settings/update", json={"welcome_message": "Welcome to Arvena!"})
    assert res.status_code == 200

    updated_k = db.query(CompanyKnowledge).filter(CompanyKnowledge.company_id == company_id).first()
    assert updated_k.welcome_message == "Welcome to Arvena!"
    assert updated_k.products_data == arvena_json


def test_arvena_rich_fields_survive_unrelated_save(test_setup):
    db = test_setup["db"]
    client = test_setup["client"]
    company_id = test_setup["company_id"]

    arvena_json = get_arvena_rich_catalog_json()
    k = CompanyKnowledge(
        company_id=company_id,
        system_prompt="Initial Prompt",
        products_data=arvena_json
    )
    db.add(k)
    db.commit()

    res = client.post("/whatsapp/settings/update", json={"tone": "enthusiastic"})
    assert res.status_code == 200

    raw_after = db.query(CompanyKnowledge).filter(CompanyKnowledge.company_id == company_id).first().products_data
    records = json.loads(raw_after)

    assert len(records) == 14
    products = [r for r in records if r.get("record_type") == "product"]
    bundles = [r for r in records if r.get("record_type") == "bundle"]
    assert len(products) == 11
    assert len(bundles) == 3

    by_name = {r["name"]: r for r in records}
    
    # Arvena Ergo One assertions
    ergo_one = by_name["Arvena Ergo One"]
    assert ergo_one["sku"] == "AR-CHR-001"
    assert ergo_one["price"] == 6900
    assert ergo_one["currency"] == "EGP"
    assert ergo_one["stock"] == 18
    assert ergo_one["warranty"] == "24 شهر"
    assert ergo_one["colors"] == ["أسود", "رمادي"]
    assert len(ergo_one["quantity_discounts"]) == 3
    assert ergo_one["provenance"] is not None

    # Arvena Ergo Pro assertions
    ergo_pro = by_name["Arvena Ergo Pro"]
    assert ergo_pro["price"] == 10900

    # FocusDesk 120 assertions
    desk_120 = by_name["FocusDesk 120"]
    assert desk_120["price"] == 8500


def test_shallow_replacement_against_rich_catalog_fails_closed(test_setup):
    db = test_setup["db"]
    client = test_setup["client"]
    company_id = test_setup["company_id"]

    arvena_json = get_arvena_rich_catalog_json()
    k = CompanyKnowledge(
        company_id=company_id,
        system_prompt="Initial Prompt",
        products_data=arvena_json,
        tone="professional"
    )
    db.add(k)
    db.commit()

    shallow_payload = json.dumps([{"name": "Arvena Ergo One", "price": 6900}])
    res = client.post("/whatsapp/settings/update", json={
        "tone": "enthusiastic",
        "products_data": shallow_payload
    })

    assert_unsafe_catalog_replacement(res)

    updated_k = db.query(CompanyKnowledge).filter(CompanyKnowledge.company_id == company_id).first()
    assert updated_k.tone == "professional"
    assert updated_k.products_data == arvena_json


def test_matching_14_shallow_rows_still_cannot_strip_rich_catalog(test_setup):
    db = test_setup["db"]
    client = test_setup["client"]
    company_id = test_setup["company_id"]

    arvena_json = get_arvena_rich_catalog_json()
    k = CompanyKnowledge(
        company_id=company_id,
        system_prompt="Initial Prompt",
        products_data=arvena_json
    )
    db.add(k)
    db.commit()

    records = json.loads(arvena_json)
    shallow_14 = [{"name": r["name"], "price": r["price"]} for r in records]
    shallow_payload = json.dumps(shallow_14)

    res = client.post("/whatsapp/settings/update", json={
        "products_data": shallow_payload
    })
    assert_unsafe_catalog_replacement(res)


def test_empty_list_cannot_silently_clear_rich_catalog(test_setup):
    db = test_setup["db"]
    client = test_setup["client"]
    company_id = test_setup["company_id"]

    arvena_json = get_arvena_rich_catalog_json()
    k = CompanyKnowledge(
        company_id=company_id,
        system_prompt="Initial Prompt",
        products_data=arvena_json
    )
    db.add(k)
    db.commit()

    res = client.post("/whatsapp/settings/update", json={
        "products_data": "[]"
    })
    assert_unsafe_catalog_replacement(res)


def test_unsafe_replacement_is_atomic(test_setup):
    db = test_setup["db"]
    client = test_setup["client"]
    company_id = test_setup["company_id"]

    arvena_json = get_arvena_rich_catalog_json()
    k = CompanyKnowledge(
        company_id=company_id,
        system_prompt="Old Prompt",
        welcome_message="Old Welcome",
        products_data=arvena_json,
        tone="professional"
    )
    db.add(k)
    db.commit()

    res = client.post("/whatsapp/settings/update", json={
        "tone": "excited",
        "system_prompt": "New Prompt",
        "welcome_message": "New Welcome",
        "company_name": "New Name",
        "products_data": "[{\"name\": \"Fake Product\", \"price\": 100}]"
    })
    assert_unsafe_catalog_replacement(res)

    updated_k = db.query(CompanyKnowledge).filter(CompanyKnowledge.company_id == company_id).first()
    assert updated_k.tone == "professional"
    assert updated_k.system_prompt == "Old Prompt"
    assert updated_k.welcome_message == "Old Welcome"
    assert updated_k.products_data == arvena_json


def test_legacy_simple_catalog_explicit_edit_still_works(test_setup):
    db = test_setup["db"]
    client = test_setup["client"]
    company_id = test_setup["company_id"]

    legacy_simple = json.dumps([
        {"name": "Chair", "price": 5000},
        {"name": "Desk", "price": 8000}
    ])
    k = CompanyKnowledge(
        company_id=company_id,
        system_prompt="Initial Prompt",
        products_data=legacy_simple,
        tone="professional"
    )
    db.add(k)
    db.commit()

    new_simple = json.dumps([
        {"name": "Ergo Chair", "price": 5500},
        {"name": "Standing Desk", "price": 12000}
    ])

    res = client.post("/whatsapp/settings/update", json={
        "tone": "casual",
        "products_data": new_simple
    })
    assert res.status_code == 200
    assert res.json()["success"] is True

    updated_k = db.query(CompanyKnowledge).filter(CompanyKnowledge.company_id == company_id).first()
    assert updated_k.tone == "casual"
    assert updated_k.products_data == new_simple


def test_omitted_vs_null_vs_empty_are_distinguished_safely(test_setup):
    db = test_setup["db"]
    client = test_setup["client"]
    company_id = test_setup["company_id"]

    arvena_json = get_arvena_rich_catalog_json()
    k = CompanyKnowledge(
        company_id=company_id,
        system_prompt="Initial Prompt",
        products_data=arvena_json
    )
    db.add(k)
    db.commit()

    # Omitted -> Preserved
    res1 = client.post("/whatsapp/settings/update", json={"tone": "formal"})
    assert res1.status_code == 200
    assert db.query(CompanyKnowledge).filter(CompanyKnowledge.company_id == company_id).first().products_data == arvena_json

    # Null -> Preserved
    res2 = client.post("/whatsapp/settings/update", json={"tone": "friendly", "products_data": None})
    assert res2.status_code == 200
    assert db.query(CompanyKnowledge).filter(CompanyKnowledge.company_id == company_id).first().products_data == arvena_json

    # Empty -> Rejected against rich catalog
    res3 = client.post("/whatsapp/settings/update", json={"products_data": "[]"})
    assert_unsafe_catalog_replacement(res3)


def test_knowledge_base_preservation_regression(test_setup):
    db = test_setup["db"]
    client = test_setup["client"]
    company_id = test_setup["company_id"]

    arvena_json = get_arvena_rich_catalog_json()
    k = CompanyKnowledge(
        company_id=company_id,
        system_prompt="Initial Prompt",
        products_data=arvena_json,
        knowledge_base="CRITICAL_UNTOUCHED_KNOWLEDGE_BASE_DATA"
    )
    db.add(k)
    db.commit()

    res = client.post("/whatsapp/settings/update", json={"tone": "cheerful"})
    assert res.status_code == 200

    updated_k = db.query(CompanyKnowledge).filter(CompanyKnowledge.company_id == company_id).first()
    assert updated_k.knowledge_base == "CRITICAL_UNTOUCHED_KNOWLEDGE_BASE_DATA"
    assert updated_k.products_data == arvena_json


def test_long_system_prompt_preservation_with_rich_catalog(test_setup):
    db = test_setup["db"]
    client = test_setup["client"]
    company_id = test_setup["company_id"]

    arvena_json = get_arvena_rich_catalog_json()
    long_prompt = "A" * 2500 + "SENTINEL_END_OF_PROMPT"
    k = CompanyKnowledge(
        company_id=company_id,
        system_prompt=long_prompt,
        products_data=arvena_json
    )
    db.add(k)
    db.commit()

    res = client.post("/whatsapp/settings/update", json={"welcome_message": "Hello!"})
    assert res.status_code == 200

    updated_k = db.query(CompanyKnowledge).filter(CompanyKnowledge.company_id == company_id).first()
    assert updated_k.system_prompt == long_prompt
    assert updated_k.products_data == arvena_json


def test_two_tenant_isolation(test_setup):
    db = test_setup["db"]
    client_a = test_setup["client"]
    company_a = test_setup["company_id"]

    company_b = "test_tenant_b_co"
    _seed_company(db, company_b)

    arvena_json = get_arvena_rich_catalog_json()
    simple_b_json = json.dumps([{"name": "Basic Item", "price": 100}])

    db.add(CompanyKnowledge(company_id=company_a, system_prompt="Prompt A", products_data=arvena_json, tone="tone_a"))
    db.add(CompanyKnowledge(company_id=company_b, system_prompt="Prompt B", products_data=simple_b_json, tone="tone_b"))
    db.commit()

    client_b = TestClient(app)
    client_b.cookies.set("access_token", _token(company_b))

    res_b = client_b.post("/whatsapp/settings/update", json={"tone": "updated_tone_b"})
    assert res_b.status_code == 200

    res_a = client_a.post("/whatsapp/settings/update", json={"tone": "updated_tone_a"})
    assert res_a.status_code == 200

    ka = db.query(CompanyKnowledge).filter(CompanyKnowledge.company_id == company_a).first()
    kb = db.query(CompanyKnowledge).filter(CompanyKnowledge.company_id == company_b).first()

    assert ka.tone == "updated_tone_a"
    assert ka.products_data == arvena_json

    assert kb.tone == "updated_tone_b"
    assert kb.products_data == simple_b_json

    db.query(CompanyKnowledge).filter(CompanyKnowledge.company_id == company_b).delete()
    db.query(Company).filter(Company.company_id == company_b).delete()
    db.commit()


def test_malformed_existing_products_data_unrelated_save_preserves_raw_value(test_setup):
    db = test_setup["db"]
    client = test_setup["client"]
    company_id = test_setup["company_id"]

    malformed_raw = "{this is not valid json raw products_data string!"
    k = CompanyKnowledge(
        company_id=company_id,
        system_prompt="Initial Prompt",
        products_data=malformed_raw,
        tone="professional"
    )
    db.add(k)
    db.commit()

    res = client.post("/whatsapp/settings/update", json={"tone": "friendly"})
    assert res.status_code == 200

    updated_k = db.query(CompanyKnowledge).filter(CompanyKnowledge.company_id == company_id).first()
    assert updated_k.tone == "friendly"
    assert updated_k.products_data == malformed_raw



# ─────────────────────────────────────────────────────────────────────────────
# MANDATORY ADVERSARIAL REGRESSION CASES (V1 MUTATION LOCK)
# ─────────────────────────────────────────────────────────────────────────────

def _assert_arvena_unmodified(db, company_id, original_json):
    k = db.query(CompanyKnowledge).filter(CompanyKnowledge.company_id == company_id).first()
    assert k.products_data == original_json
    records = json.loads(k.products_data)
    assert len(records) == 14
    products = [r for r in records if r.get("record_type") == "product"]
    bundles = [r for r in records if r.get("record_type") == "bundle"]
    assert len(products) == 11
    assert len(bundles) == 3
    by_name = {r["name"]: r for r in records}
    ergo_one = by_name["Arvena Ergo One"]
    assert ergo_one["sku"] == "AR-CHR-001"
    assert ergo_one["price"] == 6900
    assert ergo_one["currency"] == "EGP"
    assert ergo_one["stock"] == 18
    assert ergo_one["warranty"] == "24 شهر"
    assert ergo_one["colors"] == ["أسود", "رمادي"]
    assert len(ergo_one["quantity_discounts"]) == 3
    assert ergo_one["provenance"] is not None


def test_protected_arvena_rejects_sku_only_replacement(test_setup):
    db, client, cid = test_setup["db"], test_setup["client"], test_setup["company_id"]
    arvena_json = get_arvena_rich_catalog_json()
    db.add(CompanyKnowledge(company_id=cid, products_data=arvena_json))
    db.commit()

    payload = json.dumps([{"sku": "AR-CHR-001", "name": "Arvena Ergo One", "price": 6900}])
    res = client.post("/whatsapp/settings/update", json={"products_data": payload})
    assert_unsafe_catalog_replacement(res)
    _assert_arvena_unmodified(db, cid, arvena_json)


def test_protected_arvena_rejects_record_type_only_replacement(test_setup):
    db, client, cid = test_setup["db"], test_setup["client"], test_setup["company_id"]
    arvena_json = get_arvena_rich_catalog_json()
    db.add(CompanyKnowledge(company_id=cid, products_data=arvena_json))
    db.commit()

    payload = json.dumps([{"record_type": "product", "name": "Arvena Ergo One", "price": 6900}])
    res = client.post("/whatsapp/settings/update", json={"products_data": payload})
    assert_unsafe_catalog_replacement(res)
    _assert_arvena_unmodified(db, cid, arvena_json)


def test_protected_arvena_rejects_single_marker_colors(test_setup):
    db, client, cid = test_setup["db"], test_setup["client"], test_setup["company_id"]
    arvena_json = get_arvena_rich_catalog_json()
    db.add(CompanyKnowledge(company_id=cid, products_data=arvena_json))
    db.commit()

    payload = json.dumps([{"colors": ["أسود"], "name": "Arvena Ergo One", "price": 6900}])
    res = client.post("/whatsapp/settings/update", json={"products_data": payload})
    assert_unsafe_catalog_replacement(res)
    _assert_arvena_unmodified(db, cid, arvena_json)


def test_protected_arvena_rejects_single_marker_warranty(test_setup):
    db, client, cid = test_setup["db"], test_setup["client"], test_setup["company_id"]
    arvena_json = get_arvena_rich_catalog_json()
    db.add(CompanyKnowledge(company_id=cid, products_data=arvena_json))
    db.commit()

    payload = json.dumps([{"warranty": "24 شهر", "name": "Arvena Ergo One", "price": 6900}])
    res = client.post("/whatsapp/settings/update", json={"products_data": payload})
    assert_unsafe_catalog_replacement(res)
    _assert_arvena_unmodified(db, cid, arvena_json)


def test_protected_arvena_rejects_single_marker_aliases(test_setup):
    db, client, cid = test_setup["db"], test_setup["client"], test_setup["company_id"]
    arvena_json = get_arvena_rich_catalog_json()
    db.add(CompanyKnowledge(company_id=cid, products_data=arvena_json))
    db.commit()

    payload = json.dumps([{"aliases": ["Ergo 1"], "name": "Arvena Ergo One", "price": 6900}])
    res = client.post("/whatsapp/settings/update", json={"products_data": payload})
    assert_unsafe_catalog_replacement(res)
    _assert_arvena_unmodified(db, cid, arvena_json)


def test_protected_arvena_rejects_single_marker_extra_fields(test_setup):
    db, client, cid = test_setup["db"], test_setup["client"], test_setup["company_id"]
    arvena_json = get_arvena_rich_catalog_json()
    db.add(CompanyKnowledge(company_id=cid, products_data=arvena_json))
    db.commit()

    payload = json.dumps([{"extra_fields": {"material": "mesh"}, "name": "Arvena Ergo One", "price": 6900}])
    res = client.post("/whatsapp/settings/update", json={"products_data": payload})
    assert_unsafe_catalog_replacement(res)
    _assert_arvena_unmodified(db, cid, arvena_json)


def test_protected_arvena_rejects_single_marker_quantity_discounts(test_setup):
    db, client, cid = test_setup["db"], test_setup["client"], test_setup["company_id"]
    arvena_json = get_arvena_rich_catalog_json()
    db.add(CompanyKnowledge(company_id=cid, products_data=arvena_json))
    db.commit()

    payload = json.dumps([{"quantity_discounts": [{"min_qty": 3, "discount_pct": 5}], "name": "Arvena Ergo One", "price": 6900}])
    res = client.post("/whatsapp/settings/update", json={"products_data": payload})
    assert_unsafe_catalog_replacement(res)
    _assert_arvena_unmodified(db, cid, arvena_json)


def test_protected_arvena_rejects_provenance_looking_payload(test_setup):
    db, client, cid = test_setup["db"], test_setup["client"], test_setup["company_id"]
    arvena_json = get_arvena_rich_catalog_json()
    db.add(CompanyKnowledge(company_id=cid, products_data=arvena_json))
    db.commit()

    payload = json.dumps([{"provenance": {"sources": []}, "name": "Arvena Ergo One", "price": 6900}])
    res = client.post("/whatsapp/settings/update", json={"products_data": payload})
    assert_unsafe_catalog_replacement(res)
    _assert_arvena_unmodified(db, cid, arvena_json)


def test_protected_arvena_rejects_components_text_marker(test_setup):
    db, client, cid = test_setup["db"], test_setup["client"], test_setup["company_id"]
    arvena_json = get_arvena_rich_catalog_json()
    db.add(CompanyKnowledge(company_id=cid, products_data=arvena_json))
    db.commit()

    payload = json.dumps([{"components_text": "Chair + Desk", "name": "Workstation Bundle", "price": 15000}])
    res = client.post("/whatsapp/settings/update", json={"products_data": payload})
    assert_unsafe_catalog_replacement(res)
    _assert_arvena_unmodified(db, cid, arvena_json)


def test_protected_arvena_rejects_matching_14_row_degradation(test_setup):
    db, client, cid = test_setup["db"], test_setup["client"], test_setup["company_id"]
    arvena_json = get_arvena_rich_catalog_json()
    db.add(CompanyKnowledge(company_id=cid, products_data=arvena_json))
    db.commit()

    records = json.loads(arvena_json)
    degraded = [{"name": r["name"], "price": r["price"], "sku": r.get("sku")} for r in records]
    res = client.post("/whatsapp/settings/update", json={"products_data": json.dumps(degraded)})
    assert_unsafe_catalog_replacement(res)
    _assert_arvena_unmodified(db, cid, arvena_json)


def test_protected_arvena_rejects_partial_metadata_retention(test_setup):
    db, client, cid = test_setup["db"], test_setup["client"], test_setup["company_id"]
    arvena_json = get_arvena_rich_catalog_json()
    db.add(CompanyKnowledge(company_id=cid, products_data=arvena_json))
    db.commit()

    records = json.loads(arvena_json)
    partial = []
    for r in records:
        partial.append({
            "record_type": r.get("record_type"),
            "sku": r.get("sku"),
            "name": r.get("name"),
            "price": r.get("price"),
            "currency": r.get("currency"),
            "colors": r.get("colors")
        })
    res = client.post("/whatsapp/settings/update", json={"products_data": json.dumps(partial)})
    assert_unsafe_catalog_replacement(res)
    _assert_arvena_unmodified(db, cid, arvena_json)


def test_protected_arvena_rejects_full_rich_payload_too(test_setup):
    db, client, cid = test_setup["db"], test_setup["client"], test_setup["company_id"]
    arvena_json = get_arvena_rich_catalog_json()
    db.add(CompanyKnowledge(company_id=cid, products_data=arvena_json))
    db.commit()

    res = client.post("/whatsapp/settings/update", json={"products_data": arvena_json})
    assert_unsafe_catalog_replacement(res)
    _assert_arvena_unmodified(db, cid, arvena_json)


def test_protected_arvena_rejects_identical_explicit_payload(test_setup):
    db, client, cid = test_setup["db"], test_setup["client"], test_setup["company_id"]
    arvena_json = get_arvena_rich_catalog_json()
    db.add(CompanyKnowledge(company_id=cid, products_data=arvena_json))
    db.commit()

    res = client.post("/whatsapp/settings/update", json={"products_data": arvena_json})
    assert_unsafe_catalog_replacement(res)
    _assert_arvena_unmodified(db, cid, arvena_json)


def test_protected_arvena_rejects_bundle_degradation(test_setup):
    db, client, cid = test_setup["db"], test_setup["client"], test_setup["company_id"]
    arvena_json = get_arvena_rich_catalog_json()
    db.add(CompanyKnowledge(company_id=cid, products_data=arvena_json))
    db.commit()

    records = json.loads(arvena_json)
    # Convert bundles to simple products
    degraded = [{"name": r["name"], "price": r["price"]} for r in records]
    res = client.post("/whatsapp/settings/update", json={"products_data": json.dumps(degraded)})
    assert_unsafe_catalog_replacement(res)
    _assert_arvena_unmodified(db, cid, arvena_json)


def test_protected_arvena_rejects_extra_fields_loss(test_setup):
    db, client, cid = test_setup["db"], test_setup["client"], test_setup["company_id"]
    arvena_json = get_arvena_rich_catalog_json()
    db.add(CompanyKnowledge(company_id=cid, products_data=arvena_json))
    db.commit()

    records = json.loads(arvena_json)
    for r in records:
        r.pop("extra_fields", None)
    res = client.post("/whatsapp/settings/update", json={"products_data": json.dumps(records)})
    assert_unsafe_catalog_replacement(res)
    _assert_arvena_unmodified(db, cid, arvena_json)


def test_protected_arvena_rejects_discount_loss(test_setup):
    db, client, cid = test_setup["db"], test_setup["client"], test_setup["company_id"]
    arvena_json = get_arvena_rich_catalog_json()
    db.add(CompanyKnowledge(company_id=cid, products_data=arvena_json))
    db.commit()

    records = json.loads(arvena_json)
    for r in records:
        r.pop("quantity_discounts", None)
    res = client.post("/whatsapp/settings/update", json={"products_data": json.dumps(records)})
    assert_unsafe_catalog_replacement(res)
    _assert_arvena_unmodified(db, cid, arvena_json)


def test_protected_catalog_explicit_empty_list_rejected(test_setup):
    db, client, cid = test_setup["db"], test_setup["client"], test_setup["company_id"]
    arvena_json = get_arvena_rich_catalog_json()
    db.add(CompanyKnowledge(company_id=cid, products_data=arvena_json))
    db.commit()

    res = client.post("/whatsapp/settings/update", json={"products_data": []})
    assert_unsafe_catalog_replacement(res)
    _assert_arvena_unmodified(db, cid, arvena_json)


def test_protected_catalog_explicit_string_empty_list_rejected(test_setup):
    db, client, cid = test_setup["db"], test_setup["client"], test_setup["company_id"]
    arvena_json = get_arvena_rich_catalog_json()
    db.add(CompanyKnowledge(company_id=cid, products_data=arvena_json))
    db.commit()

    res = client.post("/whatsapp/settings/update", json={"products_data": "[]"})
    assert_unsafe_catalog_replacement(res)
    _assert_arvena_unmodified(db, cid, arvena_json)


def test_protected_catalog_null_is_noop(test_setup):
    db, client, cid = test_setup["db"], test_setup["client"], test_setup["company_id"]
    arvena_json = get_arvena_rich_catalog_json()
    db.add(CompanyKnowledge(company_id=cid, products_data=arvena_json, tone="formal"))
    db.commit()

    res = client.post("/whatsapp/settings/update", json={"tone": "casual", "products_data": None})
    assert res.status_code == 200
    _assert_arvena_unmodified(db, cid, arvena_json)


def test_protected_catalog_omitted_products_preserves_raw_exactly(test_setup):
    db, client, cid = test_setup["db"], test_setup["client"], test_setup["company_id"]
    arvena_json = get_arvena_rich_catalog_json()
    db.add(CompanyKnowledge(company_id=cid, products_data=arvena_json))
    db.commit()

    res = client.post("/whatsapp/settings/update", json={"welcome_message": "Hello ARVENA!"})
    assert res.status_code == 200
    _assert_arvena_unmodified(db, cid, arvena_json)


def test_protected_catalog_rejection_is_atomic(test_setup):
    db, client, cid = test_setup["db"], test_setup["client"], test_setup["company_id"]
    arvena_json = get_arvena_rich_catalog_json()
    db.add(CompanyKnowledge(company_id=cid, tone="formal", system_prompt="Old Prompt", products_data=arvena_json))
    db.commit()

    res = client.post("/whatsapp/settings/update", json={
        "tone": "aggressive",
        "system_prompt": "New Prompt",
        "products_data": json.dumps([{"name": "Attempt", "price": 10}])
    })
    assert_unsafe_catalog_replacement(res)

    k = db.query(CompanyKnowledge).filter(CompanyKnowledge.company_id == cid).first()
    assert k.tone == "formal"
    assert k.system_prompt == "Old Prompt"
    _assert_arvena_unmodified(db, cid, arvena_json)


def test_protected_catalog_unknown_metadata_is_locked(test_setup):
    db, client, cid = test_setup["db"], test_setup["client"], test_setup["company_id"]
    custom_catalog = json.dumps([{"name": "Chair", "price": 5000, "custom_supplier_code": "ABC"}])
    db.add(CompanyKnowledge(company_id=cid, products_data=custom_catalog))
    db.commit()

    res = client.post("/whatsapp/settings/update", json={
        "products_data": json.dumps([{"name": "Chair", "price": 5000}])
    })
    assert_unsafe_catalog_replacement(res)


def test_protected_catalog_sku_metadata_is_locked(test_setup):
    db, client, cid = test_setup["db"], test_setup["client"], test_setup["company_id"]
    sku_catalog = json.dumps([{"sku": "CHAIR-1", "name": "Chair", "price": 5000}])
    db.add(CompanyKnowledge(company_id=cid, products_data=sku_catalog))
    db.commit()

    res = client.post("/whatsapp/settings/update", json={
        "products_data": json.dumps([{"name": "Chair", "price": 5000}])
    })
    assert_unsafe_catalog_replacement(res)


def test_malformed_existing_catalog_omitted_save_preserves_raw(test_setup):
    db, client, cid = test_setup["db"], test_setup["client"], test_setup["company_id"]
    malformed_raw = "{raw malformed content"
    db.add(CompanyKnowledge(company_id=cid, products_data=malformed_raw, tone="formal"))
    db.commit()

    res = client.post("/whatsapp/settings/update", json={"tone": "casual"})
    assert res.status_code == 200

    k = db.query(CompanyKnowledge).filter(CompanyKnowledge.company_id == cid).first()
    assert k.tone == "casual"
    assert k.products_data == malformed_raw


def test_malformed_existing_catalog_explicit_mutation_fails_closed(test_setup):
    db, client, cid = test_setup["db"], test_setup["client"], test_setup["company_id"]
    malformed_raw = "{raw malformed content"
    db.add(CompanyKnowledge(company_id=cid, products_data=malformed_raw))
    db.commit()

    res = client.post("/whatsapp/settings/update", json={
        "products_data": json.dumps([{"name": "New Item", "price": 100}])
    })
    assert_unsafe_catalog_replacement(res)
    k = db.query(CompanyKnowledge).filter(CompanyKnowledge.company_id == cid).first()
    assert k.products_data == malformed_raw


# ─────────────────────────────────────────────────────────────────────────────
# LEGACY COMPATIBILITY TESTS
# ─────────────────────────────────────────────────────────────────────────────

def test_legacy_shallow_catalog_explicit_price_edit_works(test_setup):
    db, client, cid = test_setup["db"], test_setup["client"], test_setup["company_id"]
    legacy = json.dumps([{"name": "Desk", "price": 1000}])
    db.add(CompanyKnowledge(company_id=cid, products_data=legacy))
    db.commit()

    updated = json.dumps([{"name": "Desk", "price": 1200}])
    res = client.post("/whatsapp/settings/update", json={"products_data": updated})
    assert res.status_code == 200
    k = db.query(CompanyKnowledge).filter(CompanyKnowledge.company_id == cid).first()
    assert k.products_data == updated


def test_legacy_shallow_catalog_name_edit_works(test_setup):
    db, client, cid = test_setup["db"], test_setup["client"], test_setup["company_id"]
    legacy = json.dumps([{"name": "Desk", "price": 1000}])
    db.add(CompanyKnowledge(company_id=cid, products_data=legacy))
    db.commit()

    updated = json.dumps([{"name": "Executive Desk", "price": 1000}])
    res = client.post("/whatsapp/settings/update", json={"products_data": updated})
    assert res.status_code == 200
    k = db.query(CompanyKnowledge).filter(CompanyKnowledge.company_id == cid).first()
    assert k.products_data == updated


def test_legacy_shallow_catalog_add_product_works(test_setup):
    db, client, cid = test_setup["db"], test_setup["client"], test_setup["company_id"]
    legacy = json.dumps([{"name": "Desk", "price": 1000}])
    db.add(CompanyKnowledge(company_id=cid, products_data=legacy))
    db.commit()

    updated = json.dumps([{"name": "Desk", "price": 1000}, {"name": "Chair", "price": 500}])
    res = client.post("/whatsapp/settings/update", json={"products_data": updated})
    assert res.status_code == 200
    k = db.query(CompanyKnowledge).filter(CompanyKnowledge.company_id == cid).first()
    assert k.products_data == updated


def test_legacy_shallow_catalog_remove_product_works(test_setup):
    db, client, cid = test_setup["db"], test_setup["client"], test_setup["company_id"]
    legacy = json.dumps([{"name": "Desk", "price": 1000}, {"name": "Chair", "price": 500}])
    db.add(CompanyKnowledge(company_id=cid, products_data=legacy))
    db.commit()

    updated = json.dumps([{"name": "Desk", "price": 1000}])
    res = client.post("/whatsapp/settings/update", json={"products_data": updated})
    assert res.status_code == 200
    k = db.query(CompanyKnowledge).filter(CompanyKnowledge.company_id == cid).first()
    assert k.products_data == updated


def test_legacy_shallow_catalog_empty_list_behavior(test_setup):
    db, client, cid = test_setup["db"], test_setup["client"], test_setup["company_id"]
    legacy = json.dumps([{"name": "Desk", "price": 1000}])
    db.add(CompanyKnowledge(company_id=cid, products_data=legacy))
    db.commit()

    res = client.post("/whatsapp/settings/update", json={"products_data": "[]"})
    assert res.status_code == 200
    k = db.query(CompanyKnowledge).filter(CompanyKnowledge.company_id == cid).first()
    assert k.products_data == "[]"


# ─────────────────────────────────────────────────────────────────────────────
# PROTECTION DETECTION TESTS
# ─────────────────────────────────────────────────────────────────────────────

def test_protected_detection_classification():
    from services.settings_preservation import is_protected_record, is_protected_catalog

    # A. pure legacy shallow record -> UNPROTECTED
    assert is_protected_record({"name": "Chair", "price": 5000}) is False
    assert is_protected_record({"name": "Chair", "price": 5000, "id": "persisted-0"}) is False
    assert is_protected_record("Chair") is False

    # B. shallow + SKU -> PROTECTED
    assert is_protected_record({"sku": "CHAIR-1", "name": "Chair", "price": 5000}) is True

    # C. shallow + record_type -> PROTECTED
    assert is_protected_record({"record_type": "product", "name": "Chair", "price": 5000}) is True

    # D. shallow + unknown custom field -> PROTECTED
    assert is_protected_record({"name": "Chair", "price": 5000, "custom_supplier_code": "ABC"}) is True

    # E. shallow + nested metadata -> PROTECTED
    assert is_protected_record({"name": "Chair", "price": 5000, "extra": {"a": 1}}) is True

    # F. malformed record -> PROTECTED
    assert is_protected_record(12345) is True

    # G. ARVENA canonical record -> PROTECTED
    arvena_record = {
        "name": "Arvena Ergo One",
        "sku": "AR-CHR-001",
        "record_type": "product",
        "price": 6900,
        "currency": "EGP",
        "provenance": {"source_type": "upload"}
    }
    assert is_protected_record(arvena_record) is True

    # H. ARVENA bundle -> PROTECTED
    arvena_bundle = {
        "name": "Executive Suite Bundle",
        "record_type": "bundle",
        "components_text": "Desk + Chair"
    }
    assert is_protected_record(arvena_bundle) is True

