"""Mandatory Phase 4.3 fixtures through the real V2 response entry point."""

import json

import pytest

from database import CompanyKnowledge
from services.velor_chat_v2 import get_v2_ai_response
from tests.test_velor_chat_mvp import _seed_company, _seed_lead, _seed_message


PRODUCTS = json.dumps([
    {
        "name": "Arvena Ergo One",
        "category": "كراسي مكتبية",
        "price": 6900,
        "currency": "EGP",
        "description": "كرسي بظهر شبكي ودعم قطني ومساند ذراع قابلة للتعديل",
    }
], ensure_ascii=False)


@pytest.fixture
def fulfillment_seed(db):
    company = _seed_company(db, products_data=PRODUCTS)
    company.is_web_chat_enabled = True
    knowledge = db.query(CompanyKnowledge).filter(CompanyKnowledge.company_id == company.company_id).first()
    knowledge.knowledge_base = ""
    db.commit()
    lead = _seed_lead(db, company.company_id, phone="wc_v_fulfillment")
    return company, lead


@pytest.mark.asyncio
async def test_mandatory_semantic_fulfillment_fixtures(db, fulfillment_seed, monkeypatch):
    company, lead = fulfillment_seed
    monkeypatch.setenv("GROQ_API_KEY", "broken")

    async def turn(text):
        message = _seed_message(db, company.company_id, lead, text, sender="user")
        result = await get_v2_ai_response(db, message, company, lead)
        assert result["trace"]["fulfillment_verifier"]["passed"] is True
        return result

    color = await turn("الوان الكرسي ايه؟")
    assert "ألوان" in color["answer_text"] and "مش مسجلة" in color["answer_text"]

    support = await turn("معايا مشكلة في الكرسي")
    assert "المشكلة" in support["answer_text"]
    assert "تختار موديل" not in support["answer_text"]

    recency = await turn("اخر موديل ايه؟")
    assert "أحدث موديل" in recency["answer_text"] and "ترتيب موثق" in recency["answer_text"]

    _seed_message(db, company.company_id, lead, "سعر Arvena Ergo One هو 6900 EGP", sender="assistant")
    correction = await turn("مش غالي")
    assert "السعر مناسب" in correction["answer_text"]

    no_contact = await turn("مش عايز اكلم حد")
    assert "من غير تحويل" in no_contact["answer_text"]

    delivery = await turn("وصلني الطلب؟")
    assert "رقم الطلب" in delivery["answer_text"]

    payment = await turn("ادفع ازاي واطلب؟")
    assert "لإتمام الطلب" in payment["answer_text"]

    installments = await turn("فيه تقسيط؟")
    assert "تقسيط" in installments["answer_text"]

    lead.pending_question = json.dumps({
        "conversation_scope": {"company_id": company.company_id, "visitor_id": lead.phone, "channel": "VELOR_WEB_CHAT"},
        "offered_action": {"type": "REQUEST_OWNER_VERIFICATION", "status": "offered"},
    })
    db.commit()
    accepted = await turn("اسأل الفريق")
    assert "سجلت طلب التأكيد" in accepted["answer_text"]
    assert accepted["trace"]["conversation_action"]["type"] == "ACCEPT_OWNER_VERIFICATION"

    handoff = await turn("وصلني بخدمة العملاء")
    assert "سجلت طلبك للتواصل" in handoff["answer_text"]
    assert handoff["trace"]["conversation_action"]["type"] == "START_HUMAN_HANDOFF"
