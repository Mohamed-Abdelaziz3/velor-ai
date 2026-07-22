import json
from pathlib import Path
from types import SimpleNamespace

import pytest


PACK_PATH = Path(__file__).resolve().parents[1] / "knowledge_packs" / "velor_sales_knowledge.json"


def test_velor_sales_pack_is_truth_bound():
    pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
    payload = json.dumps(pack).lower()
    prohibited = pack["sales_claim_boundaries"]["do_not_claim"]

    assert pack["identity"]["product_name"] == "VELOR"
    assert any(item["name"] == "Public Web Chat" for item in pack["implemented_capabilities"])
    assert any(item["name"] == "Owner Workspace" for item in pack["implemented_capabilities"])
    assert any(item["name"] == "Owner Attention Projection" for item in pack["implemented_capabilities"])
    assert "official whatsapp business cloud api support unless separately integrated".lower() in [
        item.lower() for item in prohibited
    ]
    assert "instagram dm support" in [item.lower() for item in prohibited]
    assert "telegram support" in [item.lower() for item in prohibited]
    assert "guaranteed revenue uplift" in [item.lower() for item in prohibited]
    assert "guaranteed conversion rate" in [item.lower() for item in prohibited]
    assert "guaranteed response-time sla" in [item.lower() for item in prohibited]
    assert "99.9%" not in payload
    assert "case study" not in payload.replace("published customer case studies", "")


def test_velor_sales_pack_formats_runtime_company_knowledge():
    from services.velor_sales_knowledge_service import format_velor_sales_knowledge_for_runtime

    runtime = format_velor_sales_knowledge_for_runtime()
    combined = f"{runtime['system_prompt']}\n{runtime['knowledge_base']}"

    assert "Prevent purchase intent" in combined
    assert "Public Web Chat" in combined
    assert "Owner Attention Projection" in combined
    assert "WhatsApp QR as beta/self-hosted connectivity only" in combined
    assert "Do not claim official WhatsApp Business Cloud API" in combined
    assert runtime["products_data"] == "[]"


@pytest.mark.asyncio
async def test_velor_sales_pack_is_consumed_by_get_ai_response_runtime(db, monkeypatch):
    import brain
    from database import Company, Lead, hash_api_key
    from services.velor_sales_knowledge_service import apply_velor_sales_knowledge_to_company

    company_id = "velor_sales_runtime"
    visitor_id = "wc_v_velor_sales_runtime"
    db.add(
        Company(
            company_id=company_id,
            company_name="VELOR",
            email="velor-sales-runtime@example.com",
            password="hashed",
            api_key_hash=hash_api_key("velor-sales-runtime-key"),
            plan="PRO",
            is_web_chat_enabled=True,
            public_chat_slug="velor-sales-runtime",
        )
    )
    db.add(
        Lead(
            company_id=company_id,
            name="Runtime Visitor",
            channel_type="VELOR_WEB_CHAT",
            external_customer_id=visitor_id,
            conversation_count=1,
        )
    )
    db.commit()
    apply_velor_sales_knowledge_to_company(db, company_id)

    captured_system_prompts = []

    async def fake_create(*args, **kwargs):
        messages = kwargs["messages"]
        system_text = "\n".join(msg["content"] for msg in messages if msg["role"] == "system")
        captured_system_prompts.append(system_text)
        user_text = messages[-1]["content"].lower()

        if "official whatsapp" in user_text:
            reply = "لا. المصدر الموثوق يدعم واتساب كيو آر بيتا فقط، وليس واجهة واتساب الرسمية."
        elif "guarantee" in user_text or "sales growth" in user_text:
            reply = "لا يوجد ضمان لزيادة المبيعات. VELOR يساعد في تقليل المتابعات الفائتة عند الإعداد والمتابعة."
        elif "5 sales conversations" in user_text:
            reply = "مع 5 محادثات بيع أسبوعيا فقط، VELOR قد لا يكون ضروريا الآن إلا لو الردود الفائتة مؤلمة."
        elif "channels" in user_text:
            reply = "القنوات الموثقة حاليا هي دردشة VELOR على الويب وواتساب كيو آر بيتا. لا ندعي إنستجرام أو تليجرام أو واجهة واتساب الرسمية."
        elif "pricing" in user_text or "pilot" in user_text:
            reply = "التسعير أو شروط البايلوت غير محددة في مصدر الحقيقة الحالي."
        else:
            reply = "VELOR يساعد أصحاب البيزنس يمنعوا نية الشراء من الضياع داخل المحادثات، ويظهر مين محتاج إجراء وليه والخطوة التالية."

        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps(
                            {
                                "reply": reply,
                                "lead": {"interest": "VELOR"},
                                "lead_score": 20,
                                "conversation_summary": "VELOR sales knowledge runtime answer",
                                "next_conversation_state": "QUALIFICATION",
                            }
                        )
                    )
                )
            ]
        )

    monkeypatch.setattr(brain.groq_client.chat.completions, "create", fake_create)
    monkeypatch.setattr(brain, "_thread_finalize_response", lambda *args, **kwargs: (False, "runtime-out", 1))

    questions = [
        "What is VELOR?",
        "Who is VELOR for if I have 5 sales conversations per week?",
        "What channels do you support?",
        "Do you have official WhatsApp API?",
        "Do you guarantee sales growth?",
        "What is the pricing or pilot?",
    ]
    replies = []
    for question in questions:
        reply, internal_id = await brain.get_ai_response(
            db,
            question,
            visitor_id,
            company_id,
            persist_incoming=False,
        )
        assert internal_id == "runtime-out"
        replies.append(reply)

    joined_prompt = "\n".join(captured_system_prompts)
    joined_replies = "\n".join(replies).lower()

    assert "VELOR sales assistant" in joined_prompt
    assert "Prevent purchase intent" in joined_prompt
    assert "Official WhatsApp Business Cloud API support unless separately integrated" in joined_prompt
    assert "Guaranteed revenue uplift" in joined_prompt
    assert "ليس واجهة واتساب الرسمية" in joined_replies
    assert "لا يوجد ضمان" in joined_replies
    assert "قد لا يكون ضروريا" in joined_replies
    assert "لا ندعي إنستجرام أو تليجرام أو واجهة واتساب الرسمية" in joined_replies
    assert "غير محددة" in joined_replies
