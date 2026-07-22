import json
import uuid
import pytest
from jose import jwt
from database import Company, CompanyKnowledge, Lead, Message, MessageEvent, hash_api_key, SessionLocal
from services.processing_claim import acquire_inbound_processing_claim, ClaimResult

# JWT Test helpers
def _tenant_token(company_id, role="tenant"):
    return jwt.encode(
        {"company_id": company_id, "role": role, "token_type": "access"},
        "super-secret-test-key-32-chars-long",
        algorithm="HS256",
    )

def _seed_company(db, company_id=None, products_data='[{"name":"Demo Item","price":400,"currency":"EGP"}]'):
    company_id = company_id or f"velor_{uuid.uuid4().hex[:8]}"
    company = Company(
        company_id=company_id,
        company_name=f"{company_id} Corp",
        email=f"{company_id}@example.com",
        password="hashed",
        api_key_hash=hash_api_key(f"{company_id}-api-key"),
        plan="PRO",
        is_web_chat_enabled=False, # strictly opt-in
        public_chat_slug=f"{company_id}-slug"
    )
    db.add(company)
    db.add(
        CompanyKnowledge(
            company_id=company_id,
            system_prompt="You are a helpful assistant.",
            welcome_message="مرحبا بك في شركتنا!",
            suggested_questions="ما هي الخدمات المتاحة؟\nكم سعر المنتج؟",
            products_data=products_data,
            knowledge_base="Demo Item is our top product.",
        )
    )
    db.commit()
    db.refresh(company)
    return company

def _mock_groq(monkeypatch, reply_text="أهلاً بك", interest="general", products=[]):
    from types import SimpleNamespace
    import brain

    class MockCompletions:
        async def create(self, *args, **kwargs):
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({
                    "reply": reply_text,
                    "lead": {"name": None, "phone": None, "customer_provided_phone": None, "interest": interest},
                    "is_hot_deal": False,
                    "lead_score": 10,
                    "escalation_score": 0,
                    "conversation_summary": "summary",
                    "short_term_facts": "",
                    "customer_temperature": "warm",
                    "next_conversation_state": "GREETING",
                    "products_mentioned_in_chat": products,
                    "suggested_quick_replies_for_dashboard": [],
                    "memory_updates_needed": False
                }, ensure_ascii=False)))]
            )

    class MockChat:
        def __init__(self):
            self.completions = MockCompletions()

    class MockGroq:
        def __init__(self):
            self.chat = MockChat()

    monkeypatch.setattr(brain, "groq_client", MockGroq())


def _mock_groq_failure(monkeypatch):
    import brain

    calls = {"calls": 0}

    class MockCompletions:
        async def create(self, *args, **kwargs):
            calls["calls"] += 1
            raise AssertionError("Catalog direct-answer path must not call the LLM provider")

    class MockChat:
        def __init__(self):
            self.completions = MockCompletions()

    class MockGroq:
        def __init__(self):
            self.chat = MockChat()

    monkeypatch.setattr(brain, "groq_client", MockGroq())
    return calls


# 1. Test dedicated Web Chat settings endpoints
def test_web_chat_settings_endpoints(client, db):
    company = _seed_company(db)
    token = _tenant_token(company.company_id)
    slug = company.public_chat_slug
    
    # Verify opt-in default status is False
    res = client.get("/api/company/bot/web-chat", cookies={"access_token": token})
    assert res.status_code == 200
    assert res.json()["is_web_chat_enabled"] is False
    assert res.json()["public_chat_slug"] == slug
    
    # Toggle to enabled
    res = client.post("/api/company/bot/web-chat", json={"enabled": True}, cookies={"access_token": token})
    assert res.status_code == 200
    assert res.json()["is_web_chat_enabled"] is True
    
    # Re-verify GET returns True
    res = client.get("/api/company/bot/web-chat", cookies={"access_token": token})
    assert res.json()["is_web_chat_enabled"] is True

# 2. Test visitor session initiation
def test_visitor_session_creation(client, db):
    company = _seed_company(db)
    slug = company.public_chat_slug
    company_name = company.company_name
    company_id = company.company_id
    
    # Session creation fails when disabled
    res = client.post(f"/api/public/companies/{slug}/session")
    assert res.status_code == 400
    assert "disabled" in res.json()["message"]
    
    # Enable Web Chat using the shared db session
    comp = db.query(Company).filter(Company.company_id == company_id).first()
    comp.is_web_chat_enabled = True
    db.commit()
    
    # Session creation succeeds
    res = client.post(f"/api/public/companies/{slug}/session")
    assert res.status_code == 200
    data = res.json()
    assert "token" in data
    assert data["visitor_id"].startswith("wc_v_")
    assert data["company_name"] == company_name
    assert data["welcome_message"] == "مرحبا بك في شركتنا!"
    assert len(data["suggested_questions"]) == 2
    
    # Decode and verify JWT structure and boundaries
    decoded = jwt.decode(
        data["token"], 
        "super-secret-test-key-32-chars-long", 
        algorithms=["HS256"],
        audience="velor-public-client"
    )
    assert decoded["iss"] == "velor-webchat"
    assert decoded["role"] == "visitor"
    assert decoded["company_id"] == company_id
    assert decoded["sub"] == data["visitor_id"]
    
    # Lead exists in DB with phone=None and channel_type="VELOR_WEB_CHAT"
    with SessionLocal() as local_db:
        lead = local_db.query(Lead).filter(Lead.external_customer_id == data["visitor_id"]).first()
        assert lead is not None
        lead_id = lead.id
        assert lead.phone is None
        assert lead.whatsapp_number is None
        assert lead.channel_type == "VELOR_WEB_CHAT"

    # Regression: the authenticated inbox contract must retain the channel and
    # visitor identifier even though Web Chat leads intentionally have no phone.
    leads_res = client.get(
        "/leads",
        cookies={"access_token": _tenant_token(company_id)},
    )
    assert leads_res.status_code == 200
    inbox_lead = next(item for item in leads_res.json()["leads"] if item["id"] == lead_id)
    assert inbox_lead["phone"] is None
    assert inbox_lead["channel_type"] == "VELOR_WEB_CHAT"
    assert inbox_lead["external_customer_id"] == data["visitor_id"]
    assert inbox_lead["contact_identifier"] == data["visitor_id"]
    
    # Malformed slugs return 404
    res = client.post("/api/public/companies/non-existent-slug-123/session")
    assert res.status_code == 404


def test_leads_contract_preserves_whatsapp_phone_compatibility(client, db):
    company = _seed_company(db)
    whatsapp_number = f"201{uuid.uuid4().int % 10**9:09d}"
    lead = Lead(
        company_id=company.company_id,
        name="WhatsApp customer",
        phone=whatsapp_number,
        whatsapp_number=whatsapp_number,
        channel_type="WHATSAPP_QR",
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    response = client.get(
        "/leads",
        cookies={"access_token": _tenant_token(company.company_id)},
    )

    assert response.status_code == 200
    inbox_lead = next(item for item in response.json()["leads"] if item["id"] == lead.id)
    assert inbox_lead["phone"] == whatsapp_number
    assert inbox_lead["channel_type"] == "WHATSAPP_QR"
    assert inbox_lead["external_customer_id"] is None
    assert inbox_lead["contact_identifier"] == whatsapp_number

# 3. Test resume session and cross-tenant isolation
def test_visitor_session_resume_and_cross_tenant_isolation(client, db):
    company_a = _seed_company(db, company_id="webchat_comp_a")
    company_b = _seed_company(db, company_id="webchat_comp_b")
    
    company_a.is_web_chat_enabled = True
    company_b.is_web_chat_enabled = True
    slug_a = company_a.public_chat_slug
    slug_b = company_b.public_chat_slug
    db.commit()
    
    # Create session for company A
    res_a = client.post(f"/api/public/companies/{slug_a}/session")
    token_a = res_a.json()["token"]
    visitor_a = res_a.json()["visitor_id"]
    
    # Resume succeeds for company A with token A
    res = client.get(f"/api/public/companies/{slug_a}/session", headers={"Authorization": f"Bearer {token_a}"})
    assert res.status_code == 200
    assert res.json()["visitor_id"] == visitor_a
    
    # Resume fails for company B using token A (cross-tenant token theft)
    res = client.get(f"/api/public/companies/{slug_b}/session", headers={"Authorization": f"Bearer {token_a}"})
    assert res.status_code == 403
    
    # Resume fails with malformed token
    res = client.get(f"/api/public/companies/{slug_a}/session", headers={"Authorization": "Bearer malformed-token-xyz"})
    assert res.status_code == 401

# 4. Test message sending, idempotency key, and size limit
def test_public_chat_messaging_and_idempotency(client, db, monkeypatch):
    _mock_groq(monkeypatch, reply_text="أهلاً بك")
    company = _seed_company(db)
    company.is_web_chat_enabled = True
    slug = company.public_chat_slug
    db.commit()
    
    # Init session
    session_data = client.post(f"/api/public/companies/{slug}/session").json()
    token = session_data["token"]
    visitor_id = session_data["visitor_id"]
    
    # Send message with client_message_id
    client_msg_id = str(uuid.uuid4())
    res = client.post(
        "/api/public/chat",
        json={"message": "Hello there", "client_message_id": client_msg_id},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert res.status_code == 200
    assert "reply" in res.json()
    
    # Re-send same message and verify duplicate detection (COMPLETED state)
    res_dup = client.post(
        "/api/public/chat",
        json={"message": "Hello there", "client_message_id": client_msg_id},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert res_dup.status_code == 200
    assert res_dup.json()["status"] == "completed"
    assert res_dup.json()["duplicate"] is True
    
    # Verify input size boundaries: > 1000 characters returns 400
    long_msg = "A" * 1001
    res_long = client.post(
        "/api/public/chat",
        json={"message": long_msg, "client_message_id": str(uuid.uuid4())},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert res_long.status_code == 400
    
    # Verify empty message returns 400
    res_empty = client.post(
        "/api/public/chat",
        json={"message": "   ", "client_message_id": str(uuid.uuid4())},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert res_empty.status_code == 400

# 5. Test human takeover active bypass and suggested reply generation
def test_takeover_bypass_and_workspace_suggestions(client, db):
    company = _seed_company(db)
    company.is_web_chat_enabled = True
    slug = company.public_chat_slug
    company_id = company.company_id
    db.commit()
    
    # Init session
    session_data = client.post(f"/api/public/companies/{slug}/session").json()
    token = session_data["token"]
    visitor_id = session_data["visitor_id"]
    
    # Pause lead (Human Takeover)
    lead = db.query(Lead).filter(Lead.external_customer_id == visitor_id).first()
    lead.is_paused = True
    lead_id = lead.id
    db.commit()
    
    # Send message, must return skipped status
    client_msg_id = str(uuid.uuid4())
    res = client.post(
        "/api/public/chat",
        json={"message": "I need help from a human", "client_message_id": client_msg_id},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert res.status_code == 200
    assert res.json()["status"] == "skipped"
    assert res.json()["reply"] is None
    
    # Verify workspace suggestion generated
    from database import WorkspaceSuggestedReply
    with SessionLocal() as local_db:
        suggestion = local_db.query(WorkspaceSuggestedReply).filter(
            WorkspaceSuggestedReply.company_id == company_id,
            WorkspaceSuggestedReply.lead_id == lead_id
        ).first()
        assert suggestion is not None
        assert suggestion.status == "suggested"

# 6. Test pricing and evidence gate enforcement (ARVENA truth check)
def test_pricing_and_evidence_gate(client, db, monkeypatch):
    _mock_groq(monkeypatch, reply_text="سعر حقيبة جلدية هو 1200 EGP", interest="حقيبة جلدية", products=["حقيبة جلدية"])
    company = _seed_company(db, products_data='[{"name":"حقيبة جلدية","price":1200,"currency":"EGP"}]')
    company.is_web_chat_enabled = True
    slug = company.public_chat_slug
    company_id = company.company_id
    db.commit()
    
    session_data = client.post(f"/api/public/companies/{slug}/session").json()
    token = session_data["token"]
    
    # Ask about the price of the item
    res = client.post(
        "/api/public/chat",
        json={"message": "كم سعر حقيبة جلدية؟", "client_message_id": str(uuid.uuid4())},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert res.status_code == 200
    reply = res.json()["reply"]
    # The brain must use the exact catalog price
    assert "1200" in reply
    
    # Verify evidence was persisted
    from database import LeadEvidence
    with SessionLocal() as local_db:
        evidence = local_db.query(LeadEvidence).filter(
            LeadEvidence.company_id == company_id,
            LeadEvidence.evidence_type == "product_mention"
        ).first()
        assert evidence is not None
        assert evidence.normalized_value == "حقيبة جلدية"

def test_web_chat_catalog_price_answers_directly_without_phone_gate(client, db, monkeypatch):
    groq_calls = _mock_groq_failure(monkeypatch)
    products_data = json.dumps(
        [
            {"name": "Arvena Ergo One", "aliases": ["Ergo One"], "category": "chair", "price": 6900, "currency": "EGP"},
            {"name": "Arvena Ergo Pro", "aliases": ["Ergo Pro"], "category": "chair", "price": 10900, "currency": "EGP"},
        ]
    )
    company = _seed_company(db, products_data=products_data)
    company.is_web_chat_enabled = True
    slug = company.public_chat_slug
    db.commit()

    session_data = client.post(f"/api/public/companies/{slug}/session").json()
    token = session_data["token"]

    res = client.post(
        "/api/public/chat",
        json={"message": "Ergo One price?", "client_message_id": str(uuid.uuid4())},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    reply = res.json()["reply"]
    assert "6900" in reply
    assert "phone" not in reply.lower()
    assert "رقم" not in reply
    assert "Ø±Ù‚Ù…" not in reply
    assert groq_calls["calls"] == 0


def test_web_chat_catalog_comparison_answers_directly_without_phone_gate(client, db, monkeypatch):
    groq_calls = _mock_groq_failure(monkeypatch)
    products_data = json.dumps(
        [
            {
                "name": "Arvena Ergo One",
                "aliases": ["Ergo One"],
                "category": "chair",
                "description": "Comfort chair for long sitting",
                "price": 6900,
                "currency": "EGP",
            },
            {
                "name": "Arvena Ergo Pro",
                "aliases": ["Ergo Pro"],
                "category": "chair",
                "description": "Pro chair with headrest",
                "price": 10900,
                "currency": "EGP",
            },
        ]
    )
    company = _seed_company(db, products_data=products_data)
    company.is_web_chat_enabled = True
    slug = company.public_chat_slug
    db.commit()

    session_data = client.post(f"/api/public/companies/{slug}/session").json()
    token = session_data["token"]

    res = client.post(
        "/api/public/chat",
        json={"message": "إيه الفرق بين Ergo One و Ergo Pro؟", "client_message_id": str(uuid.uuid4())},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    reply = res.json()["reply"]
    assert "6900" in reply
    assert "10900" in reply
    assert "phone" not in reply.lower()
    assert "رقم" not in reply
    assert groq_calls["calls"] == 0


def test_web_chat_arabic_catalog_question_uses_direct_empty_catalog_answer(client, db, monkeypatch):
    groq_calls = _mock_groq_failure(monkeypatch)
    company = _seed_company(db, products_data="[]")
    company.is_web_chat_enabled = True
    slug = company.public_chat_slug
    db.commit()

    session_data = client.post(f"/api/public/companies/{slug}/session").json()
    token = session_data["token"]

    res = client.post(
        "/api/public/chat",
        json={"message": "عندكم كراسي مكتب بكام؟", "client_message_id": str(uuid.uuid4())},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    reply = res.json()["reply"]
    assert "كتالوج" in reply
    assert "رقم" not in reply
    assert groq_calls["calls"] == 0


def test_web_chat_catalog_followup_price_uses_previous_category_context(client, db, monkeypatch):
    groq_calls = _mock_groq_failure(monkeypatch)
    products_data = json.dumps(
        [
            {"name": "Arvena Ergo One", "aliases": ["Ergo One"], "category": "chair", "price": 6900, "currency": "EGP"},
            {"name": "Arvena Ergo Pro", "aliases": ["Ergo Pro"], "category": "chair", "price": 10900, "currency": "EGP"},
        ]
    )
    company = _seed_company(db, products_data=products_data)
    company.is_web_chat_enabled = True
    slug = company.public_chat_slug
    db.commit()

    session_data = client.post(f"/api/public/companies/{slug}/session").json()
    token = session_data["token"]

    first = client.post(
        "/api/public/chat",
        json={"message": "Do you have chairs?", "client_message_id": str(uuid.uuid4())},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert first.status_code == 200

    followup = client.post(
        "/api/public/chat",
        json={"message": "price?", "client_message_id": str(uuid.uuid4())},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert followup.status_code == 200
    reply = followup.json()["reply"]
    assert "6900" in reply
    assert "10900" in reply
    assert "phone" not in reply.lower()
    assert groq_calls["calls"] == 0


def test_web_chat_category_and_price_reference_stay_focused(client, db, monkeypatch):
    groq_calls = _mock_groq_failure(monkeypatch)
    products_data = json.dumps(
        [
            {"name": "Arvena Ergo One", "aliases": ["Ergo One"], "category": "Office Chairs", "price": 6900, "currency": "EGP"},
            {"name": "Arvena Ergo Pro", "aliases": ["Ergo Pro"], "category": "Office Chairs", "price": 10900, "currency": "EGP"},
            {"name": "FocusDesk 120", "category": "Office Desks", "price": 8500, "currency": "EGP"},
            {"name": "CleanCable Kit", "category": "Accessories", "price": 700, "currency": "EGP"},
        ]
    )
    company = _seed_company(db, products_data=products_data)
    company.is_web_chat_enabled = True
    slug = company.public_chat_slug
    db.commit()

    token = client.post(f"/api/public/companies/{slug}/session").json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    category = client.post(
        "/api/public/chat",
        json={"message": "\u0639\u0646\u062f\u0643\u0645 \u0643\u0631\u0627\u0633\u064a \u0645\u0643\u062a\u0628\u064a\u0629\u061f", "client_message_id": str(uuid.uuid4())},
        headers=headers,
    )
    assert category.status_code == 200
    assert "Arvena Ergo One" in category.json()["reply"]
    assert "Arvena Ergo Pro" in category.json()["reply"]
    assert "FocusDesk" not in category.json()["reply"]
    assert "CleanCable" not in category.json()["reply"]

    reference = client.post(
        "/api/public/chat",
        json={"message": "\u0639\u0627\u064a\u0632 \u0627\u0644\u0644\u064a \u0628\u06406900 \u062f\u0647", "client_message_id": str(uuid.uuid4())},
        headers=headers,
    )
    assert reference.status_code == 200
    assert "Arvena Ergo One" in reference.json()["reply"]
    assert "6900" in reference.json()["reply"]
    assert "Arvena Ergo Pro" not in reference.json()["reply"]
    assert groq_calls["calls"] == 0


# 7. Test owner outbound dispatch routing (Generic Endpoint)
def test_owner_takeover_dispatch(client, db):
    company = _seed_company(db)
    company.is_web_chat_enabled = True
    slug = company.public_chat_slug
    company_id = company.company_id
    db.commit()
    
    session_data = client.post(f"/api/public/companies/{slug}/session").json()
    token = session_data["token"]
    visitor_id = session_data["visitor_id"]
    
    tenant_tok = _tenant_token(company_id)
    
    # Dispatch owner message via new generic endpoint
    res = client.post(
        "/api/agent/outbound/send",
        json={"phone": visitor_id, "message": "مرحبا! أنا صاحب العمل هنا لمساعدتك."},
        cookies={"access_token": tenant_tok}
    )
    assert res.status_code == 200
    
    # Verify message persisted in DB as outgoing, sent, owner sender
    with SessionLocal() as local_db:
        msg = local_db.query(Message).filter(
            Message.company_id == company_id,
            Message.user_id == visitor_id,
            Message.direction == "outgoing"
        ).first()
        assert msg is not None
        assert msg.sender == "owner"
        assert msg.delivery_status == "sent"
    
    # Verify that message is returned in visitor's short-polling session history
    res_poll = client.get(f"/api/public/companies/{slug}/session", headers={"Authorization": f"Bearer {token}"})
    assert res_poll.status_code == 200
    poll_msg = res_poll.json()["conversations"][-1]
    assert poll_msg["message"] == "مرحبا! أنا صاحب العمل هنا لمساعدتك."
    assert poll_msg["sender"] == "owner"
    assert poll_msg["delivery_status"] == "sent"


@pytest.mark.asyncio
async def test_web_chat_summarizer_resolves_external_customer_id(db, monkeypatch):
    company = _seed_company(db)
    visitor_id = f"wc_v_{uuid.uuid4().hex[:12]}"
    lead = Lead(
        company_id=company.company_id,
        name="Potential Customer",
        phone=None,
        whatsapp_number=None,
        whatsapp_jid=None,
        channel_type="VELOR_WEB_CHAT",
        external_customer_id=visitor_id,
    )
    db.add(lead)
    db.flush()
    db.add_all(
        [
            Message(
                internal_message_id=str(uuid.uuid4()),
                company_id=company.company_id,
                user_id=visitor_id,
                sender="user",
                direction="incoming",
                message="What is the price?",
                delivery_status="received",
            ),
            Message(
                internal_message_id=str(uuid.uuid4()),
                company_id=company.company_id,
                user_id=visitor_id,
                sender="owner",
                direction="outgoing",
                message="The price is 10900 EGP.",
                delivery_status="sent",
            ),
        ]
    )
    db.commit()

    import services.context_engine as context_engine

    class MockCompletions:
        async def create(self, *args, **kwargs):
            raise RuntimeError("force local fallback")

    class MockChat:
        def __init__(self):
            self.completions = MockCompletions()

    class MockGroq:
        def __init__(self):
            self.chat = MockChat()

    monkeypatch.setattr(context_engine, "groq_client", MockGroq())

    await context_engine.summarize_conversation(company.company_id, visitor_id)

    db.refresh(lead)
    assert lead.summary
    assert lead.intent_score and lead.intent_score > 0


def test_web_chat_customer_workspace_profile_includes_same_conversation(client, db, monkeypatch):
    _mock_groq(monkeypatch, reply_text="Ø£Ù‡Ù„Ø§Ù‹ Ø¨Ùƒ")
    company = _seed_company(db)
    company.is_web_chat_enabled = True
    slug = company.public_chat_slug
    company_id = company.company_id
    db.commit()

    session_data = client.post(f"/api/public/companies/{slug}/session").json()
    token = session_data["token"]
    visitor_id = session_data["visitor_id"]

    res_msg = client.post(
        "/api/public/chat",
        json={"message": "Hello from web chat", "client_message_id": str(uuid.uuid4())},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert res_msg.status_code == 200

    lead = db.query(Lead).filter(
        Lead.company_id == company_id,
        Lead.channel_type == "VELOR_WEB_CHAT",
        Lead.external_customer_id == visitor_id,
    ).first()
    assert lead is not None
    duplicate_leads = db.query(Lead).filter(
        Lead.company_id == company_id,
        ((Lead.external_customer_id == visitor_id) | (Lead.whatsapp_number == visitor_id)),
    ).all()
    assert len(duplicate_leads) == 1

    tenant_tok = _tenant_token(company_id)
    res_profile = client.get(
        f"/api/v1/crm/customers/{lead.id}",
        cookies={"access_token": tenant_tok},
    )
    assert res_profile.status_code == 200
    customer = res_profile.json()["customer"]
    assert customer["channel_type"] == "VELOR_WEB_CHAT"
    assert customer["external_customer_id"] == visitor_id
    assert customer["phone"] is None
    assert customer["whatsapp_number"] is None

    timeline_messages = [item for item in customer["timeline"] if item["type"] == "message"]
    assert [item["sender"] for item in timeline_messages] == ["user", "assistant"]
    assert all(item["source"] == "web_chat" for item in timeline_messages)
    assert set(customer["owner_intelligence"].keys()) == {
        "current_situation",
        "what_is_blocking",
        "customer_understanding",
        "commercial_fit",
        "best_next_action",
        "relationship_communication",
    }
    assert customer["owner_intelligence"]["relationship_communication"]["channel"] == "web_chat"

# 8. Test owner outbound dispatch routing (Legacy Endpoint - backward compatibility regression check)
def test_owner_takeover_dispatch_legacy(client, db):
    company = _seed_company(db)
    company.is_web_chat_enabled = True
    slug = company.public_chat_slug
    company_id = company.company_id
    db.commit()
    
    session_data = client.post(f"/api/public/companies/{slug}/session").json()
    token = session_data["token"]
    visitor_id = session_data["visitor_id"]
    
    tenant_tok = _tenant_token(company_id)
    
    # Dispatch owner message via legacy takeover endpoint
    res = client.post(
        "/whatsapp/agent/takeover",
        json={"phone": visitor_id, "message": "مرحبا! هذا فحص التوافقية الرجعية."},
        cookies={"access_token": tenant_tok}
    )
    assert res.status_code == 200
    
    # Verify message persisted in DB as outgoing, sent, owner sender
    with SessionLocal() as local_db:
        msg = local_db.query(Message).filter(
            Message.company_id == company_id,
            Message.user_id == visitor_id,
            Message.direction == "outgoing"
        ).first()
        assert msg is not None
        assert msg.sender == "owner"
        assert msg.delivery_status == "sent"
    
    # Verify that message is returned in visitor's short-polling session history
    res_poll = client.get(f"/api/public/companies/{slug}/session", headers={"Authorization": f"Bearer {token}"})
    assert res_poll.status_code == 200
    poll_msg = res_poll.json()["conversations"][-1]
    assert poll_msg["message"] == "مرحبا! هذا فحص التوافقية الرجعية."
    assert poll_msg["sender"] == "owner"
    assert poll_msg["delivery_status"] == "sent"

# 9. Test rate limiting enforcement
def test_rate_limiting(client, db, monkeypatch):
    _mock_groq(monkeypatch, reply_text="تأكيد")
    company = _seed_company(db)
    company.is_web_chat_enabled = True
    slug = company.public_chat_slug
    db.commit()

    # Create session
    session_data = client.post(f"/api/public/companies/{slug}/session").json()
    token = session_data["token"]

    # Send 25 messages rapidly (rate limit is 10/min per visitor)
    status_codes = []
    for _ in range(25):
        res = client.post(
            "/api/public/chat",
            json={"message": "Rate limit check", "client_message_id": str(uuid.uuid4())},
            headers={"Authorization": f"Bearer {token}"}
        )
        status_codes.append(res.status_code)
    
    # At least one request must be rate limited (429)
    assert 429 in status_codes

# 10. Test concurrent duplicate claim suppression (Concurrency Lock)
def test_concurrent_claim_suppression(db):
    company_id = "test_concurrent_co"
    _seed_company(db, company_id=company_id)
    client_msg_id = str(uuid.uuid4())
    wa_message_id = f"wc:{company_id}:{client_msg_id}"

    # First claim acquisition (acquires lock/claim)
    claim1 = acquire_inbound_processing_claim(db, company_id, "wc_v_dummy", wa_message_id, "Hello")
    assert claim1[0] == ClaimResult.CLAIM_ACQUIRED

    # Second claim acquisition concurrently before the first one completes
    claim2 = acquire_inbound_processing_claim(db, company_id, "wc_v_dummy", wa_message_id, "Hello")
    assert claim2[0] == ClaimResult.ALREADY_PROCESSING

# 11. Test session token tampering and malformed tokens
def test_token_tampering_and_malformed(client, db):
    company = _seed_company(db)
    company.is_web_chat_enabled = True
    slug = company.public_chat_slug
    db.commit()

    # Create invalid token signed with dummy key
    tampered_payload = {
        "iss": "velor-webchat",
        "aud": "velor-public-client",
        "sub": "wc_v_dummy",
        "company_id": company.company_id,
        "role": "visitor"
    }
    tampered_token = jwt.encode(tampered_payload, "wrong-key-xyz", algorithm="HS256")

    # Access resume session with tampered token
    res = client.get(f"/api/public/companies/{slug}/session", headers={"Authorization": f"Bearer {tampered_token}"})
    assert res.status_code == 401

    # Access chat endpoint with malformed token
    res_chat = client.post(
        "/api/public/chat",
        json={"message": "Hello", "client_message_id": str(uuid.uuid4())},
        headers={"Authorization": "Bearer malformed-token-content"}
    )
    assert res_chat.status_code == 401

# 12. Test XSS HTML inputs safe serialization
def test_xss_input_serialization(client, db, monkeypatch):
    _mock_groq(monkeypatch, reply_text="تم الاستلام")
    company = _seed_company(db)
    company.is_web_chat_enabled = True
    slug = company.public_chat_slug
    db.commit()

    session_data = client.post(f"/api/public/companies/{slug}/session").json()
    token = session_data["token"]

    # Send message containing raw script tags
    xss_message = "<script>alert('xss')</script> Hello"
    res = client.post(
        "/api/public/chat",
        json={"message": xss_message, "client_message_id": str(uuid.uuid4())},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert res.status_code == 200

    # Resume session and verify that the message is returned serialized as plain text
    res_poll = client.get(f"/api/public/companies/{slug}/session", headers={"Authorization": f"Bearer {token}"})
    conversations = res_poll.json()["conversations"]
    sent_msg = [m for m in conversations if m["sender"] == "user"][-1]
    assert sent_msg["message"] == xss_message

# 13. Test cross-channel idempotency claim uniqueness bounds
def test_cross_channel_idempotency_claim_uniqueness(db):
    suffix = uuid.uuid4().hex[:8]
    company_a = f"claim_company_a_{suffix}"
    company_b = f"claim_company_b_{suffix}"
    _seed_company(db, company_id=company_a)
    _seed_company(db, company_id=company_b)
    client_msg_id = "common_msg_id_123"

    # A. same company, same client_msg_id, WHATSAPP_QR vs VELOR_WEB_CHAT -> no collision
    wa_msg_id_wa = client_msg_id
    wa_msg_id_wc = f"wc:{company_a}:{client_msg_id}"

    claim_wa = acquire_inbound_processing_claim(db, company_a, "user_wa", wa_msg_id_wa, "Hello WA")
    claim_wc = acquire_inbound_processing_claim(db, company_a, "wc_v_dummy", wa_msg_id_wc, "Hello WC")
    
    assert claim_wa[0] == ClaimResult.CLAIM_ACQUIRED
    assert claim_wc[0] == ClaimResult.CLAIM_ACQUIRED

    # B. different company, same channel (Web Chat), same client_msg_id -> no collision
    wa_msg_id_b = f"wc:{company_b}:{client_msg_id}"
    claim_b = acquire_inbound_processing_claim(db, company_b, "wc_v_dummy", wa_msg_id_b, "Hello B")
    assert claim_b[0] == ClaimResult.CLAIM_ACQUIRED

    # C. same company, same channel (Web Chat), same client_msg_id -> one logical owner only
    claim_dup = acquire_inbound_processing_claim(db, company_a, "wc_v_dummy", wa_msg_id_wc, "Hello WC Duplicate")
    assert claim_dup[0] == ClaimResult.ALREADY_PROCESSING

# 14. Test direct LLM provider call count ledger
def test_provider_call_ledger(client, db, monkeypatch):
    groq_calls = {"calls": 0}
    
    from types import SimpleNamespace
    import brain

    class MockCompletions:
        async def create(self, *args, **kwargs):
            groq_calls["calls"] += 1
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({
                    "reply": "أهلاً بك، تفضل بالدخول",
                    "lead": {"name": None, "phone": None, "customer_provided_phone": None, "interest": "general"},
                    "is_hot_deal": False,
                    "lead_score": 10,
                    "escalation_score": 0,
                    "conversation_summary": "summary",
                    "short_term_facts": "",
                    "customer_temperature": "warm",
                    "next_conversation_state": "GREETING",
                    "products_mentioned_in_chat": [],
                    "suggested_quick_replies_for_dashboard": [],
                    "memory_updates_needed": False
                }, ensure_ascii=False)))]
            )

    class MockChat:
        def __init__(self):
            self.completions = MockCompletions()

    class MockGroq:
        def __init__(self):
            self.chat = MockChat()

    monkeypatch.setattr(brain, "groq_client", MockGroq())

    company = _seed_company(db)
    company.is_web_chat_enabled = True
    slug = company.public_chat_slug
    company_id = company.company_id
    db.commit()

    # Session creation
    session_data = client.post(f"/api/public/companies/{slug}/session").json()
    token = session_data["token"]
    visitor_id = session_data["visitor_id"]

    # 1. Normal eligible request -> exactly 1 provider call
    groq_calls["calls"] = 0
    client_msg_id = str(uuid.uuid4())
    res1 = client.post(
        "/api/public/chat",
        json={"message": "First message", "client_message_id": client_msg_id},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert res1.status_code == 200
    assert groq_calls["calls"] == 1

    # 2. Sequential duplicate -> 0 additional provider calls (remains 1)
    res2 = client.post(
        "/api/public/chat",
        json={"message": "First message", "client_message_id": client_msg_id},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert res2.status_code == 200
    assert groq_calls["calls"] == 1

    # 3. Auto Reply OFF -> 0 provider calls
    comp = db.query(Company).filter(Company.company_id == company_id).first()
    comp.bot_auto_reply_enabled = False
    db.commit()

    groq_calls["calls"] = 0
    res3 = client.post(
        "/api/public/chat",
        json={"message": "Message with bot off", "client_message_id": str(uuid.uuid4())},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert res3.status_code == 200
    assert groq_calls["calls"] == 0

    # Turn bot back ON
    comp = db.query(Company).filter(Company.company_id == company_id).first()
    comp.bot_auto_reply_enabled = True
    db.commit()

    # 4. Human Takeover active -> 0 provider calls
    lead = db.query(Lead).filter(Lead.external_customer_id == visitor_id).first()
    lead.is_paused = True
    db.commit()

    groq_calls["calls"] = 0
    res4 = client.post(
        "/api/public/chat",
        json={"message": "Message under takeover", "client_message_id": str(uuid.uuid4())},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert res4.status_code == 200
    assert groq_calls["calls"] == 0

    # Unpause lead
    lead = db.query(Lead).filter(Lead.external_customer_id == visitor_id).first()
    lead.is_paused = False
    db.commit()

    # 5. Outbound transport dispatch & channel normalization -> 0 provider calls
    groq_calls["calls"] = 0
    tenant_tok = _tenant_token(company_id)
    res5 = client.post(
        "/api/agent/outbound/send",
        json={"phone": visitor_id, "message": "Reply from owner"},
        cookies={"access_token": tenant_tok}
    )
    assert res5.status_code == 200
    assert groq_calls["calls"] == 0

# 15. Test history and public API safety boundary (strictly no prompt, secrets, or internals leakage)
def test_public_api_safety_and_no_leakage(client, db, monkeypatch):
    _mock_groq(monkeypatch, reply_text="أهلاً بك")
    company = _seed_company(db)
    company.is_web_chat_enabled = True
    slug = company.public_chat_slug
    company_id = company.company_id
    db.commit()

    # Fetch/init public session (POST)
    res = client.post(f"/api/public/companies/{slug}/session")
    assert res.status_code == 200
    data = res.json()

    # Verify root level response schema contains only the safe whitelist of keys (POST)
    assert set(data.keys()) == {"visitor_id", "token", "company_name", "welcome_message", "suggested_questions"}
    
    # Assert absolutely NO system prompt, keys, or credential leaks in config
    assert "system_prompt" not in data
    assert "api_key" not in data
    assert "api_key_hash" not in data
    assert "password" not in data
    assert "email" not in data

    token = data["token"]
    
    # Send a message to populate history
    client.post(
        "/api/public/chat",
        json={"message": "أريد شراء المنتج", "client_message_id": str(uuid.uuid4())},
        headers={"Authorization": f"Bearer {token}"}
    )

    # Call public resume endpoint to fetch history (GET)
    res_poll = client.get(f"/api/public/companies/{slug}/session", headers={"Authorization": f"Bearer {token}"})
    assert res_poll.status_code == 200
    history_data = res_poll.json()

    # Verify root level response schema contains only the safe whitelist of keys (GET)
    assert set(history_data.keys()) == {"visitor_id", "company_name", "welcome_message", "suggested_questions", "is_paused", "conversations"}

    # Verify history item keys contain only basic fields (id, sender, direction, message, delivery_status, created_at, client_message_id)
    for msg in history_data["conversations"]:
        assert set(msg.keys()) == {"id", "sender", "direction", "message", "delivery_status", "created_at", "client_message_id"}
        # Verify absolutely no internal IDs, ORM schema dumps or internal processing properties are leaked
        assert "internal_message_id" not in msg
        assert "wa_message_id" not in msg
        assert "user_id" not in msg
        assert "company_id" not in msg
        assert "processing_status" not in msg
        assert "processing_started_at" not in msg
        # Option C check: verify ID is a dedicated random public-safe value (starts with pub- and is not derived from old pub_ prefix)
        assert msg["id"].startswith("pub-")
        assert len(msg["id"]) > 30
        assert "pub_" not in msg["id"]

def test_jwt_secret_fail_closed_and_dedicated_public_message_id(client, db, monkeypatch):
    # Setup company
    company = _seed_company(db)
    company.is_web_chat_enabled = True
    slug = company.public_chat_slug
    db.commit()

    # Proof A: Valid explicit secret -> token issuance succeeds
    res = client.post(f"/api/public/companies/{slug}/session")
    assert res.status_code == 200
    token = res.json()["token"]
    visitor_id = res.json()["visitor_id"]

    # Proof E: Tampered token -> 401
    tampered = token + "xyz"
    res_tamp = client.get(f"/api/public/companies/{slug}/session", headers={"Authorization": f"Bearer {tampered}"})
    assert res_tamp.status_code == 401

    # Proof F: Wrong signing secret -> 401
    wrong_token = jwt.encode(
        {"iss": "velor-webchat", "aud": "velor-public-client", "sub": visitor_id, "company_id": company.company_id, "role": "visitor"},
        "wrong-secret-key-32-chars-long-123456",
        algorithm="HS256"
    )
    res_wrong = client.get(f"/api/public/companies/{slug}/session", headers={"Authorization": f"Bearer {wrong_token}"})
    assert res_wrong.status_code == 401

    # Proof G: Cross-tenant token reuse -> rejected
    other_comp = _seed_company(db)
    other_comp.is_web_chat_enabled = True
    other_slug = other_comp.public_chat_slug
    db.commit()
    res_cross = client.get(f"/api/public/companies/{other_slug}/session", headers={"Authorization": f"Bearer {token}"})
    assert res_cross.status_code == 403

    # Proof B/C: Missing/empty/malformed secret fails closed
    import main as api_main
    old_secret = api_main.JWT_SECRET

    try:
        # B. Missing (None)
        api_main.JWT_SECRET = None
        res_none = client.post(f"/api/public/companies/{slug}/session")
        assert res_none.status_code == 500

        res_none_get = client.get(f"/api/public/companies/{slug}/session", headers={"Authorization": f"Bearer {token}"})
        assert res_none_get.status_code == 500

        # C. Empty
        api_main.JWT_SECRET = ""
        res_empty = client.post(f"/api/public/companies/{slug}/session")
        assert res_empty.status_code == 500

        # Malformed/too short
        api_main.JWT_SECRET = "short"
        res_short = client.post(f"/api/public/companies/{slug}/session")
        assert res_short.status_code == 500
    finally:
        api_main.JWT_SECRET = old_secret

    # Proof D: Known historical/default fallback secret -> cannot forge accepted production visitor token in production env
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setattr(api_main, "ENV", "production")
    try:
        api_main.JWT_SECRET = "super-secret-test-key-32-chars-long"
        res_weak = client.post(f"/api/public/companies/{slug}/session")
        assert res_weak.status_code == 500

        res_weak_get = client.get(f"/api/public/companies/{slug}/session", headers={"Authorization": f"Bearer {token}"})
        assert res_weak_get.status_code == 500
    finally:
        monkeypatch.setenv("ENV", "test")
        monkeypatch.setattr(api_main, "ENV", "test")
        api_main.JWT_SECRET = old_secret
