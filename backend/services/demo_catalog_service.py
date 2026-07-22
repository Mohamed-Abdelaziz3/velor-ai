import json
import os
import secrets
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from database import Company, CompanyKnowledge, generate_api_key, get_password_hash, hash_api_key
from services.catalog_merge_service import merge_catalogs
from services.catalog_parser_service import parse_catalog_csv


DEMO_COMPANY_ID = "velor_demo_arvena"
DEMO_PUBLIC_SLUG = "arvena-demo"
DEMO_SOURCE = {
    "source_type": "upload",
    "source_id": "repo_fixture_arvena_upload_ready_catalog",
    "source_label": "Repository ARVENA upload-ready catalog fixture",
}
FIXTURE_PATH = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "ARVENA_Upload_Ready_Catalog.csv"


def load_trusted_demo_catalog_records(fixture_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    path = fixture_path or FIXTURE_PATH
    parse_result = parse_catalog_csv(path.read_bytes())
    parse_errors = [issue for issue in parse_result.issues if issue.get("severity") == "error"]
    if parse_errors:
        raise ValueError(f"Trusted demo catalog fixture has parse errors: {parse_errors}")

    merge_result = merge_catalogs([], parse_result.records, DEMO_SOURCE)
    merge_errors = [issue for issue in merge_result.issues if issue.get("severity") == "error"]
    if merge_errors:
        raise ValueError(f"Trusted demo catalog fixture has merge errors: {merge_errors}")
    return merge_result.records


def _price_proof(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    required_names = ["Arvena Ergo One", "Arvena Ergo Pro", "FocusDesk 120", "FocusDesk 140", "LiftDesk Electric 120"]
    by_name = {record.get("name"): record for record in records}
    return {
        name: {
            "price": by_name[name].get("price"),
            "currency": by_name[name].get("currency"),
            "source_id": by_name[name]["provenance"]["field_sources"]["price"][0]["source_id"],
        }
        for name in required_names
        if name in by_name
    }


def ensure_trusted_demo_tenant(
    db: Session,
    company_id: str = DEMO_COMPANY_ID,
    slug: str = DEMO_PUBLIC_SLUG,
) -> Dict[str, Any]:
    if os.getenv("ALLOW_SYNTHETIC_DEMO_SEED", "").strip() != "1":
        raise RuntimeError(
            "Synthetic demo seeding is disabled. Set ALLOW_SYNTHETIC_DEMO_SEED=1 "
            "only for an isolated development or verification database."
        )

    slug_owner = db.query(Company).filter(Company.public_chat_slug == slug, Company.company_id != company_id).first()
    if slug_owner:
        raise ValueError(f"Public chat slug '{slug}' already belongs to company '{slug_owner.company_id}'")

    records = load_trusted_demo_catalog_records()
    disabled_password = secrets.token_urlsafe(64)
    discarded_api_key = generate_api_key()
    company = db.query(Company).filter(Company.company_id == company_id).first()
    if not company:
        company = Company(
            company_id=company_id,
            company_name="ARVENA Demo",
            email=f"{company_id}@demo.local",
            # Demo ownership is intentionally non-interactive. Credentials are
            # random, discarded, and rotated on every explicit seed run.
            password=get_password_hash(disabled_password),
            api_key_hash=hash_api_key(discarded_api_key),
            plan="FREE",
            is_web_chat_enabled=True,
            public_chat_slug=slug,
        )
        db.add(company)
        db.flush()
    else:
        company.company_name = "ARVENA Demo"
        company.password = get_password_hash(disabled_password)
        company.api_key_hash = hash_api_key(discarded_api_key)
        company.plan = "FREE"
        company.is_web_chat_enabled = True
        company.public_chat_slug = slug
        company.is_deleted = False

    knowledge = db.query(CompanyKnowledge).filter(CompanyKnowledge.company_id == company_id).first()
    if not knowledge:
        knowledge = CompanyKnowledge(company_id=company_id)
        db.add(knowledge)

    knowledge.system_prompt = (
        "You are the ARVENA demo sales assistant. Use only the structured products_data catalog for product, price, "
        "stock, warranty, installation, and bundle facts. If a fact is missing, say it needs review."
    )
    knowledge.products_data = json.dumps(records, ensure_ascii=False)
    knowledge.knowledge_base = (
        "Trusted demo tenant seeded from backend/tests/fixtures/ARVENA_Upload_Ready_Catalog.csv through the parser "
        "and catalog merge provenance contract."
    )
    knowledge.welcome_message = "أهلا بك في ARVENA. اسألني عن الكراسي، المكاتب، الباندلز، أو الأسعار."
    knowledge.suggested_questions = "\n".join(
        [
            "كم سعر Arvena Ergo One؟",
            "عندكم كراسي مكتب؟",
            "ما سعر LiftDesk Electric 120؟",
        ]
    )
    knowledge.industry = "Office furniture"
    knowledge.language = "Arabic"
    knowledge.tone = "Professional"
    knowledge.lead_collection = True

    db.commit()
    product_count = sum(1 for record in records if record.get("record_type") == "product")
    bundle_count = sum(1 for record in records if record.get("record_type") == "bundle")
    return {
        "company_id": company_id,
        "public_chat_slug": slug,
        "record_count": len(records),
        "product_count": product_count,
        "bundle_count": bundle_count,
        "owner_access": "disabled",
        "seed_status": "seeded",
        "source": DEMO_SOURCE,
        "price_proof": _price_proof(records),
    }
