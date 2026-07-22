import json
import uuid

import pytest

from database import Company, CompanyKnowledge, hash_api_key
from services.demo_catalog_service import DEMO_COMPANY_ID, DEMO_SOURCE, ensure_trusted_demo_tenant, load_trusted_demo_catalog_records


def test_arvena_demo_fixture_is_trusted_catalog_truth():
    records = load_trusted_demo_catalog_records()
    by_name = {record["name"]: record for record in records}

    assert len(records) == 14
    assert by_name["Arvena Ergo One"]["price"] == 6900.0
    assert by_name["Arvena Ergo Pro"]["price"] == 10900.0
    assert by_name["FocusDesk 120"]["price"] == 8500.0
    assert by_name["FocusDesk 140"]["price"] == 10500.0
    assert by_name["LiftDesk Electric 120"]["price"] == 19900.0
    assert by_name["Arvena Ergo One"]["provenance"]["field_sources"]["price"][0]["source_id"] == DEMO_SOURCE["source_id"]


def test_demo_tenant_seed_requires_explicit_opt_in(db, monkeypatch):
    monkeypatch.delenv("ALLOW_SYNTHETIC_DEMO_SEED", raising=False)

    with pytest.raises(RuntimeError, match="Synthetic demo seeding is disabled"):
        ensure_trusted_demo_tenant(db)


def test_demo_tenant_seed_is_isolated_and_provenanced(db, monkeypatch):
    monkeypatch.setenv("ALLOW_SYNTHETIC_DEMO_SEED", "1")
    real_company_id = f"real_{uuid.uuid4().hex[:8]}"
    real = Company(
        company_id=real_company_id,
        company_name="Real Tenant",
        email=f"{real_company_id}@example.com",
        password="hashed",
        api_key_hash=hash_api_key(f"{real_company_id}-api-key"),
        plan="FREE",
        is_web_chat_enabled=False,
        public_chat_slug=f"{real_company_id}-slug",
    )
    db.add(real)
    db.add(CompanyKnowledge(company_id=real_company_id, system_prompt="Real prompt", products_data="[]"))
    db.commit()

    result = ensure_trusted_demo_tenant(db)

    assert result["company_id"] == DEMO_COMPANY_ID
    assert result["record_count"] == 14
    assert result["owner_access"] == "disabled"
    assert result["price_proof"]["Arvena Ergo One"]["price"] == 6900.0

    real_after = db.query(Company).filter(Company.company_id == real_company_id).first()
    real_knowledge = db.query(CompanyKnowledge).filter(CompanyKnowledge.company_id == real_company_id).first()
    assert real_after.is_web_chat_enabled is False
    assert real_after.public_chat_slug == f"{real_company_id}-slug"
    assert real_knowledge.products_data == "[]"

    demo_knowledge = db.query(CompanyKnowledge).filter(CompanyKnowledge.company_id == DEMO_COMPANY_ID).first()
    demo_company = db.query(Company).filter(Company.company_id == DEMO_COMPANY_ID).first()
    assert demo_company.plan == "FREE"
    assert demo_company.api_key_hash != hash_api_key(f"{DEMO_COMPANY_ID}-api-key")
    products = json.loads(demo_knowledge.products_data)
    ergo_one = next(item for item in products if item["name"] == "Arvena Ergo One")
    assert ergo_one["provenance"]["sources"][0]["source_id"] == DEMO_SOURCE["source_id"]
