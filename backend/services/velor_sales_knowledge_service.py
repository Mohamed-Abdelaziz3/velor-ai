import json
from pathlib import Path
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from database import CompanyKnowledge


PACK_PATH = Path(__file__).resolve().parents[1] / "knowledge_packs" / "velor_sales_knowledge.json"


def load_velor_sales_knowledge(path: Optional[Path] = None) -> Dict[str, Any]:
    pack_path = path or PACK_PATH
    return json.loads(pack_path.read_text(encoding="utf-8"))


def format_velor_sales_knowledge_for_runtime(pack: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    pack = pack or load_velor_sales_knowledge()
    capabilities = "\n".join(
        f"- {item['name']}: {item['truth']}" for item in pack.get("implemented_capabilities", [])
    )
    do_not_claim = "\n".join(f"- {item}" for item in pack.get("sales_claim_boundaries", {}).get("do_not_claim", []))
    allowed_claims = "\n".join(f"- {item}" for item in pack.get("sales_claim_boundaries", {}).get("allowed_claims", []))
    best_fit = "\n".join(f"- {item}" for item in pack.get("pilot_offer", {}).get("best_fit", []))
    not_best_fit = "\n".join(f"- {item}" for item in pack.get("pilot_offer", {}).get("not_best_fit", []))
    success_metrics = "\n".join(f"- {item}" for item in pack.get("pilot_offer", {}).get("success_metrics", []))
    mission = "\n".join(f"- {item}" for item in pack.get("mission", []))

    system_prompt = f"""You are the VELOR sales assistant.

Product identity:
- Name: {pack['identity']['product_name']}
- Category: {pack['identity']['category']}
- Positioning: {pack['identity']['positioning']}

Core mission:
{mission}

Implemented capability truth:
{capabilities}

Allowed sales claims:
{allowed_claims}

Forbidden claims:
{do_not_claim}

Fit qualification:
Best fit:
{best_fit}

Not best fit:
{not_best_fit}

Pilot success metrics:
{success_metrics}

Rules:
- Explain VELOR in value-first language.
- If a business has very low sales conversation volume, qualify honestly and do not pressure them into buying.
- Present WhatsApp QR as beta/self-hosted connectivity only.
- Do not claim official WhatsApp Business Cloud API, Instagram, Telegram, guaranteed revenue growth, case studies, customer counts, SLA, or uptime unless separately supplied as trusted facts.
- If pricing or pilot terms are not explicitly supplied, say they are not finalized in the provided source of truth.
"""

    knowledge_base = f"""# VELOR Trusted Sales Knowledge

Source of truth: {pack.get('source_of_truth')}
Version: {pack.get('version')}

{system_prompt}
"""
    return {
        "system_prompt": system_prompt,
        "knowledge_base": knowledge_base,
        "products_data": "[]",
    }


def apply_velor_sales_knowledge_to_company(db: Session, company_id: str) -> CompanyKnowledge:
    runtime = format_velor_sales_knowledge_for_runtime()
    row = db.query(CompanyKnowledge).filter(CompanyKnowledge.company_id == company_id).first()
    if not row:
        row = CompanyKnowledge(company_id=company_id)
        db.add(row)

    row.system_prompt = runtime["system_prompt"]
    row.knowledge_base = runtime["knowledge_base"]
    row.products_data = runtime["products_data"]
    row.industry = "Conversational revenue intelligence"
    row.tone = "Clear and honest"
    row.language = "Arabic/English"
    row.lead_collection = False
    db.commit()
    db.refresh(row)
    return row
