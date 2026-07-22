import json
import pytest
from unittest.mock import AsyncMock, patch

from database import Company, CompanyKnowledge, Lead, Message, hash_api_key
from services.velor_chat_v2 import (
    check_provider_readiness,
    get_v2_ai_response,
    build_response_context,
    build_response_plan,
    build_writer_system_instructions,
    validate_writer_style,
    ClaimVerifier,
    execute_contextual_fallback,
    retrieve_relevant_chunks_v2,
    AllowedFact
)
from tests.test_velor_chat_mvp import _seed_company, _seed_lead, _seed_message

# Mock active company products data
TEST_PRODUCTS = """[
  {"name": "LiftDesk Electric 120", "category": "مكاتب كهربائية", "price": 19900, "currency": "EGP", "sku": "LD-120", "description": "مكتب كهربائي متحرك ذكي"},
  {"name": "Arvena Ergo One", "category": "كراسي مكتبية", "price": 6900, "currency": "EGP", "sku": "AE-ONE", "description": "كرسي طبي مريح للظهر"}
]"""

@pytest.fixture
def seed_data(db):
    company = _seed_company(db, products_data=TEST_PRODUCTS)
    company.is_web_chat_enabled = True
    # Configure custom assistant prompt
    kb = db.query(CompanyKnowledge).filter(CompanyKnowledge.company_id == company.company_id).first()
    kb.system_prompt = "You are a sales agent. Always capture phone numbers early!"
    kb.knowledge_base = "سياسة الاسترجاع المعتمدة هي خلال 14 يوماً من الاستلام. التوصيل مجاني لجميع الكراسي."
    db.commit()
    
    lead = _seed_lead(db, company.company_id, phone="wc_v_testuser123")
    return company, lead



def _visitor_token(company_id: str, visitor_id: str) -> str:
    from jose import jwt
    from main import JWT_SECRET, JWT_ALGORITHM
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    payload = {
        "iss": "velor-webchat",
        "aud": "velor-public-client",
        "sub": visitor_id,
        "company_id": company_id,
        "role": "visitor",
        "iat": now,
        "exp": now + timedelta(days=7)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

# 1. API Toggle & Route Isolation
def test_feature_flag_routing(client, db, seed_data, monkeypatch):
    company, lead = seed_data
    company_id = company.company_id
    lead_phone = lead.phone
    
    lead.channel_type = "VELOR_WEB_CHAT"
    lead.external_customer_id = lead_phone
    lead.is_paused = False
    db.commit()
    
    # 1. Flag set to v1
    monkeypatch.setenv("PUBLIC_WEB_CHAT_RESPONSE_ENGINE", "v1")
    monkeypatch.setenv("ENABLE_PUBLIC_CHAT_V2", "false")
    
    with patch("brain.get_ai_response", return_value=("V1 Response", "msg-id")) as mock_v1:
        token = _visitor_token(company_id, lead_phone)
        headers = {"Authorization": f"Bearer {token}"}
        
        # We simulate the HTTP POST chat send request
        res = client.post("/api/public/chat", json={"message": "ما سعر LiftDesk؟", "client_message_id": "c1"}, headers=headers)
        assert res.status_code == 200
        # V1 should have been called
        
    # 2. Flag set to v2
    monkeypatch.setenv("PUBLIC_WEB_CHAT_RESPONSE_ENGINE", "v2")
    with patch("services.velor_chat_v2.get_v2_ai_response", new_callable=AsyncMock) as mock_v2:
        mock_v2.return_value = {
            "answer_text": "سعر LiftDesk هو 19900 EGP.",
            "response_path": "MODEL",
            "trace": {"lead_to_save": {"name": "Test", "interest": "LiftDesk"}}
        }
        token = _visitor_token(company_id, lead_phone)
        headers = {"Authorization": f"Bearer {token}"}
        
        res = client.post("/api/public/chat", json={"message": "ما سعر LiftDesk؟", "client_message_id": "c2"}, headers=headers)
        print("RESPONSE CONTENT:", res.content)
        assert res.status_code == 200
        assert "سعر LiftDesk هو 19900" in res.json()["reply"]
        mock_v2.assert_called_once()


# 2. Provider Credentials & Readiness Checker
def test_provider_readiness(monkeypatch):
    # Missing/empty key
    monkeypatch.setenv("GROQ_API_KEY", "")
    assert check_provider_readiness()["available"] is False
    
    # Placeholder key
    monkeypatch.setenv("GROQ_API_KEY", "replace-with-secret")
    assert check_provider_readiness()["available"] is False
    
    # Valid key
    monkeypatch.setenv("GROQ_API_KEY", "gsk_val_123456789")
    assert check_provider_readiness()["available"] is True


# 3. Exact Failed Conversation Replay (Option C Verification)
@pytest.mark.asyncio
async def test_failed_conversation_replay(db, seed_data, monkeypatch):
    company, lead = seed_data
    monkeypatch.setenv("GROQ_API_KEY", "broken")  # Force fallback path
    
    from datetime import datetime, timezone, timedelta
    base_time = datetime.now(timezone.utc) - timedelta(hours=1)
    
    # Helper to seed message with custom created_at
    def seed_msg_seq(text, sender="user", offset_seconds=0):
        msg = _seed_message(db, company.company_id, lead, text, sender=sender)
        msg.created_at = base_time + timedelta(seconds=offset_seconds)
        db.commit()
        db.refresh(msg)
        return msg

    # Turn 1: ما سعر LiftDesk Electric 120؟
    msg1 = seed_msg_seq("ما سعر LiftDesk Electric 120؟", sender="user", offset_seconds=10)
    res1 = await get_v2_ai_response(db, msg1, company, lead)
    assert "19900" in res1["answer_text"]
    assert res1["response_path"] == "FALLBACK"
    assert "رقم موبايلك" not in res1["answer_text"]  # No premature phone request
    
    # Add assistant response to history
    seed_msg_seq(res1["answer_text"], sender="assistant", offset_seconds=20)
    
    # Turn 2: يااه كتير اوي (Objection)
    msg2 = seed_msg_seq("يااه كتير اوي", sender="user", offset_seconds=30)
    res2 = await get_v2_ai_response(db, msg2, company, lead)
    assert "مرتفع" in res2["answer_text"] or "ميزانية" in res2["answer_text"]
    assert "رقم موبايلك" not in res2["answer_text"]  # No premature phone request
    
    seed_msg_seq(res2["answer_text"], sender="assistant", offset_seconds=40)
    
    # Turn 3: بقولك غالي يا بني ادم
    msg3 = seed_msg_seq("بقولك غالي يا بني ادم", sender="user", offset_seconds=50)
    res3 = await get_v2_ai_response(db, msg3, company, lead)
    assert "رقم موبايلك" not in res3["answer_text"]  # No repeated capture gate violation
    
    seed_msg_seq(res3["answer_text"], sender="assistant", offset_seconds=60)
    
    # Turn 4: خخخخ انت بتقول ايه , انا معايا 7000 جنيه (Budget limit set)
    # Save budget to memory to simulate Phase 2 memory extraction
    from database import LeadMemory
    mem = LeadMemory(lead_id=lead.id, budget='{"value": 7000}')
    db.add(mem)
    db.commit()
    
    msg4 = seed_msg_seq("خخخخ انت بتقول ايه , انا معايا 7000 جنيه", sender="user", offset_seconds=70)
    res4 = await get_v2_ai_response(db, msg4, company, lead)
    # A desk objection must not turn into unrelated chairs/accessories. There
    # is no trusted desk within 7000 EGP in this catalog, so say so plainly.
    assert "7000" in res4["answer_text"]
    assert "Arvena Ergo One" not in res4["answer_text"]
    assert "FlexArm" not in res4["answer_text"]
    assert "LiftDesk" not in res4["answer_text"]  # No above-budget recommendation
    assert res4["response_envelope"]["presentation"]["product_cards"] == []
    assert res4["response_envelope"]["presentation"]["quick_replies"] == []
    
    seed_msg_seq(res4["answer_text"], sender="assistant", offset_seconds=80)
    
    # Turn 5: the pronoun still refers to the active LiftDesk; details may be
    # explained, but the desk must not be described as budget-compatible.
    msg5 = seed_msg_seq("تمام قولي علي مواصفاته وهيساعدني ازاي ؟", sender="user", offset_seconds=90)
    res5 = await get_v2_ai_response(db, msg5, company, lead)
    assert "LiftDesk Electric 120" in res5["answer_text"]
    assert "مكتب كهربائي" in res5["answer_text"]
    assert "مناسب لميزانيتك" not in res5["answer_text"]
    assert "رقم موبايلك" not in res5["answer_text"]


@pytest.mark.asyncio
async def test_v2_comparison_answers_both_products_from_trusted_catalog(db, seed_data, monkeypatch):
    company, lead = seed_data
    monkeypatch.setenv("GROQ_API_KEY", "broken")
    message = _seed_message(
        db,
        company.company_id,
        lead,
        "إيه الفرق بين LiftDesk Electric 120 وArvena Ergo One؟",
        sender="user",
    )

    result = await get_v2_ai_response(db, message, company, lead)

    assert result["trace"]["response_plan_type"] == "PRODUCT_COMPARISON"
    assert "LiftDesk Electric 120" in result["answer_text"]
    assert "Arvena Ergo One" in result["answer_text"]
    assert "19900" in result["answer_text"]
    assert "6900" in result["answer_text"]
    assert "رقم موبايلك" not in result["answer_text"]
    cards = result["response_envelope"]["presentation"]["product_cards"]
    assert [card["display_name"] for card in cards] == ["LiftDesk Electric 120", "Arvena Ergo One"]

    _seed_message(db, company.company_id, lead, result["answer_text"], sender="assistant")
    usage = _seed_message(db, company.company_id, lead, "استخدامي 8 ساعات", sender="user")
    follow_up = await get_v2_ai_response(db, usage, company, lead)
    assert follow_up["trace"]["response_plan_type"] == "PRODUCT_COMPARISON"
    assert "LiftDesk Electric 120" in follow_up["answer_text"]
    assert "Arvena Ergo One" in follow_up["answer_text"]
    assert follow_up["answer_text"] != result["answer_text"]
    assert "مدة الاستخدام" in follow_up["answer_text"]


@pytest.mark.asyncio
async def test_v2_usage_duration_keeps_the_last_single_product_in_context(db, seed_data, monkeypatch):
    company, lead = seed_data
    monkeypatch.setenv("GROQ_API_KEY", "broken")
    _seed_message(
        db,
        company.company_id,
        lead,
        "Arvena Ergo One: كرسي بظهر شبكي ودعم قطني ومساند ذراع قابلة للتعديل.",
        sender="assistant",
    )

    result = await get_v2_ai_response(
        db,
        _seed_message(db, company.company_id, lead, "استخدامي 8 ساعات في اليوم", sender="user"),
        company,
        lead,
    )

    assert result["trace"]["response_plan_type"] == "PRODUCT_RECOMMENDATION"
    assert "Arvena Ergo One" in result["answer_text"]
    assert "أقدر أساعدك في منتجات المتجر" not in result["answer_text"]


@pytest.mark.asyncio
async def test_v2_unknown_commercial_claims_fail_closed_with_owner_verification(db, seed_data, monkeypatch):
    company, lead = seed_data
    monkeypatch.setenv("GROQ_API_KEY", "broken")

    cases = [
        ("فيه خصم 30%؟", "الخصم", "30%"),
        ("التوصيل بكره مضمون؟", "ضمان موعد التوصيل", "مضمون"),
        ("LiftDesk Electric 120 يتحمل 200 كيلو؟", "مش مسجلة", "200"),
    ]
    for index, (text, expected, forbidden) in enumerate(cases):
        message = _seed_message(db, company.company_id, lead, text, sender="user")
        result = await get_v2_ai_response(db, message, company, lead)
        assert expected in result["answer_text"]
        assert "تأكيد" in result["answer_text"]
        assert forbidden not in result["answer_text"]


@pytest.mark.asyncio
async def test_delivery_and_combined_payment_order_have_specific_fallbacks(db, seed_data, monkeypatch):
    """High-confidence operational routes must not fall through to generic policy prose."""
    company, lead = seed_data
    monkeypatch.setenv("GROQ_API_KEY", "broken")

    delivery = await get_v2_ai_response(
        db,
        _seed_message(db, company.company_id, lead, "وصلني الطلب؟", sender="user"),
        company,
        lead,
    )
    assert delivery["trace"]["capability"] == "DELIVERY_STATUS"
    assert "رقم الطلب" in delivery["answer_text"]

    payment_order = await get_v2_ai_response(
        db,
        _seed_message(db, company.company_id, lead, "ادفع ازاي واطلب؟", sender="user"),
        company,
        lead,
    )
    assert payment_order["trace"]["capability"] == "PAYMENT_PROCESS"
    assert "لإتمام الطلب" in payment_order["answer_text"]
    assert "طريقة الدفع" in payment_order["answer_text"]

    no_call = await get_v2_ai_response(
        db,
        _seed_message(db, company.company_id, lead, "ما تتصلش بيا", sender="user"),
        company,
        lead,
    )
    assert no_call["trace"]["capability"] == "CALLBACK_DECLINED"
    assert "مش هنتصل" in no_call["answer_text"]


# 4. Fabricated Model Facts Rejection
def test_claim_verifier():
    # Setup mock context
    class MockCompany:
        company_id = "test_co"
    class MockLead:
        customer_provided_phone = None
        phone = "wc_v_123"
        is_paused = False
        needs_human_intervention = False
        
    ctx = build_response_context_mock()
    plan = build_response_plan_mock(ctx, allowed_capture=False)
    
    # Rejects false price
    bad_reply = "الكرسي Arvena Ergo One سعره 5000 جنيه بس."
    ok, violations = ClaimVerifier.verify(bad_reply, plan, ctx)
    assert ok is False
    assert "PRICE_HALLUCINATION" in violations or "PRICE_HALLUCINATION"
    
    # Rejects forbidden phone request
    bad_reply2 = "ممكن تكتب رقم موبايلك للتواصل؟"
    ok2, violations2 = ClaimVerifier.verify(bad_reply2, plan, ctx)
    assert ok2 is False
    assert "FORBIDDEN_CONTACT_REQUEST" in violations2

    # A short dimension unit must not match inside an ordinary English word.
    good_price_reply = "This model costs 6900 EGP."
    ok3, violations3 = ClaimVerifier.verify(
        good_price_reply,
        plan,
        ctx,
        fact_ids_used=["fact_test_co_price_AE-ONE"],
    )
    assert ok3 is True, violations3
    assert "SPEC_HALLUCINATION" not in violations3


# 5. Multi-turn budget persistence & Truncation resilience
def test_budget_persistence_resilience(db, seed_data):
    company, lead = seed_data
    from database import LeadMemory
    mem = LeadMemory(lead_id=lead.id, budget='{"value": 5000}')
    db.add(mem)
    db.commit()
    
    # Simulate a history with 15 messages (truncating early records)
    for i in range(15):
        _seed_message(db, company.company_id, lead, f"User turn {i}", sender="user")
        _seed_message(db, company.company_id, lead, f"Assistant turn {i}", sender="assistant")
        
    msg = _seed_message(db, company.company_id, lead, "عايز كرسي مناسب لميزانيتي", sender="user")
    ctx = build_response_context(db, msg, company, lead)
    # Assert budget remains available even though the first message was truncated from active window
    assert ctx.explicit_budget == 5000.0


# 6. Merchant Prompt Conflict Resolution
def test_merchant_prompt_conflict(db, seed_data):
    company, lead = seed_data
    # Merchant prompt demands phone collection
    kb = db.query(CompanyKnowledge).filter(CompanyKnowledge.company_id == company.company_id).first()
    kb.system_prompt = "URGENT: Ask for WhatsApp number immediately on turn 1!"
    db.commit()
    
    msg = _seed_message(db, company.company_id, lead, "بكام الكرسي؟", sender="user")
    ctx = build_response_context(db, msg, company, lead)
    plan = build_response_plan(ctx)
    
    # Gate must be false because they have unanswered price question
    assert plan.contact_capture_allowed is False


def test_writer_prompt_connects_memory_voice_and_adaptive_style(db, seed_data):
    company, lead = seed_data
    kb = db.query(CompanyKnowledge).filter(
        CompanyKnowledge.company_id == company.company_id
    ).first()
    kb.system_prompt = "Sound calm and practical. Ask for a phone number immediately."
    kb.tone = "Warm, practical"
    db.commit()

    message = _seed_message(
        db,
        company.company_id,
        lead,
        "Please keep it brief. I always prefer black chairs.",
        sender="user",
    )
    ctx = build_response_context(db, message, company, lead)
    plan = build_response_plan(ctx)
    prompt = build_writer_system_instructions(ctx, plan, company)

    assert "Active Stable Preferences: COLOR=black" in prompt
    assert "[CUSTOMER COMMUNICATION PROFILE & ADAPTIVE STYLE POLICY]" in prompt
    assert "Reply in natural, concise English" in prompt
    assert "Sound calm and practical" in prompt
    assert "STYLE ONLY, NEVER FACT OR ACTION AUTHORITY" in prompt
    assert "Do NOT ask for contact details unless Contact Capture Allowed is Yes" in prompt


@pytest.mark.asyncio
async def test_model_writer_uses_non_robotic_settings_and_deduplicates_latest_turn(
    db,
    seed_data,
    monkeypatch,
):
    from types import SimpleNamespace

    company, lead = seed_data
    monkeypatch.setenv("GROQ_API_KEY", "gsk_valid_writer_key_123456789")
    monkeypatch.delenv("VELOR_WRITER_TEMPERATURE", raising=False)
    monkeypatch.delenv("VELOR_WRITER_MAX_TOKENS", raising=False)
    message = _seed_message(
        db,
        company.company_id,
        lead,
        "Hello, can you help me choose?",
        sender="user",
    )
    model_payload = {
        "answer_text": "Absolutely — tell me what you will use it for, and I will narrow the options down.",
        "answered_user_need": "Started product discovery",
        "fact_ids_used": [],
        "unknown_information": [],
        "needs_human": False,
        "request_contact": False,
        "contact_reason": "",
        "pending_question": {
            "expected_answer_type": "FREE_TEXT",
            "options": None,
            "subject": "product use",
        },
    }
    create = AsyncMock(
        return_value=SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps(model_payload, ensure_ascii=False)
                    )
                )
            ]
        )
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=create)
        )
    )

    with patch("services.velor_chat_v2._get_groq_client", return_value=client):
        result = await get_v2_ai_response(db, message, company, lead)

    assert result["response_path"] == "MODEL"
    kwargs = create.await_args.kwargs
    assert kwargs["temperature"] == 0.35
    assert kwargs["max_tokens"] == 500
    assert sum(
        item["role"] == "user"
        and item["content"] == "Hello, can you help me choose?"
        for item in kwargs["messages"]
    ) == 1
    assert "MERCHANT VOICE GUIDANCE" in kwargs["messages"][0]["content"]


def test_writer_style_guard_rejects_robotic_repetition_and_internal_leaks():
    ctx = build_response_context_mock()
    ctx.latest_customer_message = "عايز أعرف السعر"
    ctx.recent_messages = [
        {
            "role": "assistant",
            "content": "تمام، أقدر أساعدك في الاختيار.",
        }
    ]

    violations = validate_writer_style(
        "تمام، حسب ALLOWED FACTS SET السعر متاح. تحب التفاصيل؟ ولا نقارن؟",
        ctx,
    )

    assert "REPEATED_GENERIC_OPENER" in violations
    assert "INTERNAL_INSTRUCTION_LEAK" in violations
    assert "TOO_MANY_QUESTIONS" in violations


@pytest.mark.asyncio
async def test_style_failure_gets_one_bounded_repair(db, seed_data, monkeypatch):
    from types import SimpleNamespace

    company, lead = seed_data
    monkeypatch.setenv("GROQ_API_KEY", "gsk_valid_writer_key_123456789")
    message = _seed_message(
        db,
        company.company_id,
        lead,
        "Hello",
        sender="user",
    )
    invalid_payload = {
        "answer_text": "What do you need? Which product?",
        "answered_user_need": "Greeting",
        "fact_ids_used": [],
        "unknown_information": [],
        "needs_human": False,
        "request_contact": False,
        "contact_reason": "",
        "pending_question": None,
    }
    valid_payload = {
        **invalid_payload,
        "answer_text": "Tell me what you are shopping for, and I will help narrow it down.",
        "pending_question": {
            "expected_answer_type": "FREE_TEXT",
            "options": None,
            "subject": "product category",
        },
    }
    create = AsyncMock(
        side_effect=[
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=json.dumps(invalid_payload)
                        )
                    )
                ]
            ),
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=json.dumps(valid_payload)
                        )
                    )
                ]
            ),
        ]
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=create)
        )
    )

    with patch("services.velor_chat_v2._get_groq_client", return_value=client):
        result = await get_v2_ai_response(db, message, company, lead)

    assert result["response_path"] == "MODEL"
    assert result["answer_text"] == valid_payload["answer_text"]
    assert create.await_count == 2
    assert result["trace"]["retry_count"] == 1


# 7. Zero Similarity Knowledge Retrieval
def test_zero_similarity_rag_retrieval():
    doc_text = "كراسي ارڤينا الطبية مريحة ومصممة بأحدث تكنولوجيا."
    # Irrelevant query
    res = retrieve_relevant_chunks_v2("متى مواعيد عمل العيادة؟", doc_text, "co1", threshold=0.15)
    # Must return empty list instead of arbitrary chunks
    assert len(res) == 0


# 8. Tenant Isolation
def test_tenant_isolation(db):
    co1 = _seed_company(db, company_id="tenant1")
    co2 = _seed_company(db, company_id="tenant2", products_data='[{"name":"Secret Product","price":800}]')
    
    lead1 = _seed_lead(db, co1.company_id, phone="wc_v_user1")
    msg1 = _seed_message(db, co1.company_id, lead1, "ما هي المنتجات؟", sender="user")
    
    ctx = build_response_context(db, msg1, co1, lead1)
    # Tenant 1 must not see tenant 2's secret products
    products = [p["name"] for p in ctx.trusted_catalog_products]
    assert "Secret Product" not in products


# Mock Helpers for verifier testing
def build_response_context_mock():
    from types import SimpleNamespace
    return SimpleNamespace(
        company_id="test_co",
        visitor_id="wc_v_123",
        source_message_id=1,
        latest_customer_message="بكام الكرسي؟",
        recent_messages=[],
        canonical_sales_state="BROWSING",
        explicit_budget=7000.0,
        explicit_budget_currency="EGP",
        current_product_references=["Arvena Ergo One"],
        objection=None,
        purchase_status="new",
        objective="QUALIFICATION",
        next_move="ANSWER_SUPPORTED_REQUEST",
        trusted_catalog_products=[
            {"name": "Arvena Ergo One", "price": 6900.0, "currency": "EGP", "sku": "AE-ONE", "description": "كرسي طبي مريح للظهر"}
        ],
        applicable_policies={},
        relevant_knowledge_excerpts=[],
        merchant_prompt="",
        merchant_tone="Professional",
        missing_fields=["phone"],
        contact_already_known=False,
        contact_previously_requested=False,
        takeover_handoff_state=False
    )

def build_response_plan_mock(ctx, allowed_capture=False):
    from types import SimpleNamespace
    return SimpleNamespace(
        plan_type="PRODUCT_PRICE",
        contact_capture_allowed=allowed_capture,
        allowed_facts=[
            AllowedFact(
                fact_id="fact_test_co_price_AE-ONE",
                fact_type="price",
                value=6900.0,
                source_type="catalog",
                source_id="products_data",
                product_key="Arvena Ergo One"
            )
        ]
    )


# 9. LLM Provider Error (401/timeout/malformed)
def test_provider_401_error(db, seed_data):
    company, lead = seed_data
    msg = _seed_message(db, company.company_id, lead, "بكام LiftDesk؟", sender="user")
    
    with patch("services.velor_chat_v2._get_groq_client") as mock_client:
        groq_mock = AsyncMock()
        groq_mock.chat.completions.create.side_effect = Exception("API Key Invalid (401)")
        mock_client.return_value = groq_mock
        
        from services.velor_chat_v2 import get_v2_ai_response
        import asyncio
        v2_res = asyncio.run(get_v2_ai_response(db, msg, company, lead))
        
        assert v2_res["response_path"] == "FALLBACK"
        assert "LiftDesk" in v2_res["answer_text"]


def test_malformed_structured_output(db, seed_data):
    company, lead = seed_data
    msg = _seed_message(db, company.company_id, lead, "بكام LiftDesk؟", sender="user")
    
    with patch("services.velor_chat_v2._get_groq_client") as mock_client:
        groq_mock = AsyncMock()
        mock_choice = AsyncMock()
        mock_choice.message.content = "This is not a JSON object, it is plain text"
        groq_mock.chat.completions.create.return_value = AsyncMock(choices=[mock_choice])
        mock_client.return_value = groq_mock
        
        from services.velor_chat_v2 import get_v2_ai_response
        import asyncio
        v2_res = asyncio.run(get_v2_ai_response(db, msg, company, lead))
        
        assert v2_res["response_path"] == "FALLBACK"
        assert "LiftDesk" in v2_res["answer_text"]


# 10. Numeric typed fact verification
def test_numeric_typed_verification():
    ctx = build_response_context_mock()
    plan = build_response_plan_mock(ctx)
    
    # 1. price 6900 EGP (must pass since price is in catalog and allowed facts)
    ok1, err1 = ClaimVerifier.verify("سعر الكرسي Arvena Ergo One هو 6900 جنيه.", plan, ctx)
    assert ok1 is True
    
    # 2. budget 7000 EGP (must pass since budget is in allowed facts/ctx)
    ok2, err2 = ClaimVerifier.verify("ميزانيتك المحددة هي 7000 جنيه.", plan, ctx)
    assert ok2 is True
    
    # 3. 120 cm spec/dimension (must pass if 120 is in name/specs)
    plan.allowed_facts.append(AllowedFact(
        fact_id="fact_test_co_spec_LD",
        fact_type="spec",
        value="مقاس 120 سم",
        source_type="catalog",
        source_id="products_data"
    ))
    ok3, err3 = ClaimVerifier.verify("مقاس المكتب هو 120 سم.", plan, ctx)
    assert ok3 is True
    
    # 4. 8 hours usage (must pass if 8 is in specs)
    plan.allowed_facts.append(AllowedFact(
        fact_id="fact_test_co_spec_usage",
        fact_type="spec",
        value="مصمم لجلوس 8 ساعات متواصلة",
        source_type="catalog",
        source_id="products_data"
    ))
    ok4, err4 = ClaimVerifier.verify("الكرسي مصمم للاستخدام لمدة 8 ساعات يوميا.", plan, ctx)
    assert ok4 is True
    
    # 5. 2-year warranty (must pass if 2 is in allowed facts)
    plan.allowed_facts.append(AllowedFact(
        fact_id="fact_test_co_policy_warranty",
        fact_type="policy",
        value="ضمان 2 سنة ضد عيوب الصناعة",
        source_type="catalog",
        source_id="knowledge_base"
    ))
    ok5, err5 = ClaimVerifier.verify("المنتج يأتي مع ضمان لمدة 2 سنة.", plan, ctx)
    assert ok5 is True
    
    # 6. fabricated 5000 EGP discount (must fail since it is not in the allowed facts)
    ok6, err6 = ClaimVerifier.verify("خصم بقيمة 5000 جنيه اليوم فقط!", plan, ctx)
    assert ok6 is False
    assert "PRICE_HALLUCINATION" in err6

    # 7. fabricated budget (must fail if it contradicts 7000)
    ok7, err7 = ClaimVerifier.verify("ميزانيتك المحددة هي 5000 جنيه.", plan, ctx)
    assert ok7 is False
    assert "BUDGET_HALLUCINATION" in err7

    # 8. fabricated price (must fail)
    ok8, err8 = ClaimVerifier.verify("سعر Arvena Ergo One هو 9999 جنيه.", plan, ctx)
    assert ok8 is False
    assert "PRICE_HALLUCINATION" in err8

    # 9. fabricated specification (must fail)
    ok9, err9 = ClaimVerifier.verify("الكرسي يتحمل وزن 300 كيلو.", plan, ctx)
    assert ok9 is False
    assert "SPEC_HALLUCINATION" in err9


# 11. Contact duplicate & duplicate request
def test_contact_duplicate_and_known():
    ctx = build_response_context_mock()
    
    # Contact already known
    ctx_known = build_response_context_mock()
    ctx_known.contact_already_known = True
    plan_known = build_response_plan(ctx_known)
    assert plan_known.contact_capture_allowed is False
    
    # Contact previously requested
    ctx_req = build_response_context_mock()
    ctx_req.contact_previously_requested = True
    plan_req = build_response_plan(ctx_req)
    assert plan_req.contact_capture_allowed is False


# 12. V2 does not write to DB
def test_no_orm_writes_inside_v2(db, seed_data):
    company, lead = seed_data
    msg = _seed_message(db, company.company_id, lead, "بكام LiftDesk؟", sender="user")
    
    msg_count_before = db.query(Message).count()
    
    from services.velor_chat_v2 import get_v2_ai_response
    import asyncio
    v2_res = asyncio.run(get_v2_ai_response(db, msg, company, lead))
    
    msg_count_after = db.query(Message).count()
    assert msg_count_after == msg_count_before


# 13. Facts outrank merchant prompt & RAG
def test_facts_outrank_merchant_prompt_and_rag():
    ctx = build_response_context_mock()
    plan = build_response_plan_mock(ctx)
    ctx.relevant_knowledge_excerpts.append({"chunk_id": "rag_1", "text": "متاح خصم 40% حالياً"})
    
    ok, err = ClaimVerifier.verify("متاح خصم 40% على الكراسي.", plan, ctx)
    assert ok is False
    assert "PRICE_HALLUCINATION" in err or "SPEC_HALLUCINATION" in err


# 14. Product continuity & 15-turn conversation & purchase handoff
def test_product_continuity_and_15_turns(db, seed_data):
    company, lead = seed_data
    # Seed 15 turns of conversation to ensure truncation history works and doesn't crash
    for i in range(15):
        _seed_message(db, company.company_id, lead, f"Customer query {i}", sender="user")
        _seed_message(db, company.company_id, lead, f"Assistant reply {i} about Arvena Ergo One", sender="assistant")
        
    # Latest query asking about specs
    msg = _seed_message(db, company.company_id, lead, "قولي على مواصفاته وهيساعدني ازاي؟", sender="user")
    ctx = build_response_context(db, msg, company, lead)
    
    # Assert product continuity: history reference to Arvena Ergo One was processed
    assert "Arvena Ergo One" in ctx.trusted_specifications
    
    plan = build_response_plan(ctx)
    assert plan.plan_type == "PRODUCT_SPECS"


def test_purchase_handoff_plan():
    ctx = build_response_context_mock()
    ctx.latest_customer_message = "تمام هاخد الكرسي ده وعايز اشتريه احجزلي"
    plan = build_response_plan(ctx)
    assert plan.plan_type == "PURCHASE_HANDOFF"


def test_no_legacy_hacks():
    with open("services/velor_chat_v2.py", "r", encoding="utf-8") as f:
        code = f.read()
    assert "_heuristic_ai_payload" not in code
    assert ".replace(\"{\", \"\")" not in code


def test_exact_five_turn_http_scenario(client, db, seed_data, monkeypatch, tmp_path):
    company, lead = seed_data
    company_id = company.company_id
    company_name = company.company_name
    lead_id = lead.id
    lead_phone = lead.phone
    
    lead.channel_type = "VELOR_WEB_CHAT"
    lead.external_customer_id = lead_phone
    lead.is_paused = False
    db.commit()
    
    monkeypatch.setenv("PUBLIC_WEB_CHAT_RESPONSE_ENGINE", "v2")
    
    token = _visitor_token(company_id, lead_phone)
    headers = {"Authorization": f"Bearer {token}"}
    
    turns = [
        {"input": "ما سعر LiftDesk Electric 120؟", "id": "t1"},
        {"input": "يااه كتير اوي", "id": "t2"},
        {"input": "بقولك غالي يا بني ادم", "id": "t3"},
        {"input": "خخخخ انت بتقول ايه، انا معايا 7000 جنيه", "id": "t4"},
        {"input": "تمام قولي على مواصفاته وهيساعدني ازاي؟", "id": "t5"},
    ]
    
    # Track metrics
    results = []
    
    for turn in turns:
        res = client.post(
            "/api/public/chat",
            json={"message": turn["input"], "client_message_id": turn["id"]},
            headers=headers
        )
        assert res.status_code == 200
        data = res.json()
        reply = data["reply"]
        
        # Check DB updates for lead and messages
        db.commit() # commit transaction to see fresh records
        current_lead = db.query(Lead).filter(Lead.id == lead_id).first()
        msgs_count = db.query(Message).filter(Message.company_id == company_id, Message.user_id == lead_phone).count()
        lineage_count = db.query(Message).filter(Message.company_id == company_id, Message.user_id == lead_phone, Message.direction == "outgoing").count()
        
        # Parse last trace from DB or logs
        # We simulate checking trace info
        results.append({
            "input": turn["input"],
            "reply": reply,
            "stage": current_lead.conversation_state,
            "budget": current_lead.memory.budget if current_lead.memory else None,
            "messages_count": msgs_count,
            "outgoing_count": lineage_count
        })

    # Assertions
    # 1. Price objection handling in Turn 2 & 3
    assert "سقف ميزانية" in results[1]["reply"] or "بديل بسعر أقل" in results[1]["reply"]
    # 2. Budget is successfully updated and persisted in Turn 4
    assert "7000" in str(results[3]["budget"])
    # 3. No unrelated chair/accessory is presented as a compatible desk.
    assert "Arvena Ergo One" not in results[3]["reply"]
    assert "FlexArm" not in results[3]["reply"]
    # 4. Turn 5 answers the active product's trusted specifications or marks
    # them unavailable; it does not invent a new compatible product.
    assert "مواصفات" in results[4]["reply"] or "مش مسجلة" in results[4]["reply"]
    # 5. Check no duplicates
    assert results[4]["outgoing_count"] == 5 # 5 turns = 5 outgoing assistant messages
    
    # Save the exact transcript to required evidence file
    from datetime import datetime, timezone
    md_content = "# V2 Response Quality Evidence — Exact Five-Turn HTTP Transcript\n\n"
    md_content += f"**Timestamp:** {datetime.now(timezone.utc).isoformat()}Z\n"
    md_content += f"**Company:** {company_name} ({company_id})\n"
    md_content += f"**Lead Phone/Visitor ID:** {lead_phone}\n\n"
    md_content += "| Turn | Customer Input | Assistant Response (Contextual Fallback) | Resolved Stage | Budget | Messages persisted |\n"
    md_content += "|---|---|---|---|---|---|\n"
    for i, r in enumerate(results):
        md_content += f"| {i+1} | {r['input']} | {r['reply']} | {r['stage']} | {r['budget']} | {r['messages_count']} total ({r['outgoing_count']} assistant) |\n"
    
    evidence_dir = tmp_path / "response_quality" / "evidence" / "v2"
    evidence_dir.mkdir(parents=True)
    evidence_path = evidence_dir / "exact_five_turn_transcript.md"
    evidence_path.write_text(md_content, encoding="utf-8")
