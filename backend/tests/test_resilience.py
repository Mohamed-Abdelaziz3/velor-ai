import json
import pytest
from types import SimpleNamespace

from database import Company, CompanyKnowledge, Lead, Message, SystemEvent, hash_api_key, save_message


class _FailingCompletions:
    async def create(self, *args, **kwargs):
        raise RuntimeError("simulated provider outage")


class _FailingChat:
    completions = _FailingCompletions()


class _FailingGroq:
    chat = _FailingChat()


class _MojibakeCompletions:
    async def create(self, *args, **kwargs):
        reply = "Ù…Ø±Ø­Ø¨Ø§ØŒ ÙƒÙŠÙ Ø£Ù‚Ø¯Ø± Ø£Ø³Ø§Ø¹Ø¯ÙƒØŸ".encode("utf-8").decode("cp1252")
        content = (
            '{"reply": "'
            + reply
            + '", "lead": {"name": null, "phone": null, "customer_provided_phone": null, "interest": "general"}, '
            + '"is_hot_deal": false, "lead_score": 45, "escalation_score": 0, '
            + '"conversation_summary": "summary", "short_term_facts": "", '
            + '"customer_temperature": "warm", "next_conversation_state": "QUALIFICATION", '
            + '"products_mentioned_in_chat": [], "suggested_quick_replies_for_dashboard": [], '
            + '"memory_updates_needed": false}'
        )
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def _make_mojibake(text):
    chars = []
    for byte in text.encode("utf-8"):
        try:
            chars.append(bytes([byte]).decode("cp1252"))
        except UnicodeDecodeError:
            chars.append(chr(byte))
    return "".join(chars)


class _MojibakeCompletions:
    async def create(self, *args, **kwargs):
        reply = _make_mojibake("\u0645\u0631\u062d\u0628\u0627\u060c \u0643\u064a\u0641 \u0623\u0642\u062f\u0631 \u0623\u0633\u0627\u0639\u062f\u0643\u061f")
        content = json.dumps(
            {
                "reply": reply,
                "lead": {"name": None, "phone": None, "customer_provided_phone": None, "interest": "general"},
                "is_hot_deal": False,
                "lead_score": 45,
                "escalation_score": 0,
                "conversation_summary": "summary",
                "short_term_facts": "",
                "customer_temperature": "warm",
                "next_conversation_state": "QUALIFICATION",
                "products_mentioned_in_chat": [],
                "suggested_quick_replies_for_dashboard": [],
                "memory_updates_needed": False,
            },
            ensure_ascii=False,
        )
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


class _MojibakeChat:
    completions = _MojibakeCompletions()


class _MojibakeGroq:
    chat = _MojibakeChat()


def _seed_company(db, company_id="demo_resilience"):
    company = Company(
        company_id=company_id,
        company_name="Demo Store",
        email=f"{company_id}@example.com",
        password="hashed",
        api_key_hash=hash_api_key(f"{company_id}-api-key"),
        plan="PRO",
    )
    db.add(company)
    db.add(
        CompanyKnowledge(
            company_id=company_id,
            system_prompt="You are a helpful sales assistant.",
            products_data='[{"name":"Demo Product","price":"1000 EGP"}]',
            knowledge_base="Demo Product is suitable for small businesses.",
            industry="Retail",
            tone="Friendly",
        )
    )
    db.commit()
    return company


def test_chat_uses_local_fallback_when_llm_provider_fails(client, db, monkeypatch):
    import brain
    import engine.analyzer as analyzer
    import engine.memory as memory

    _seed_company(db)
    monkeypatch.setattr(brain, "groq_client", _FailingGroq())
    monkeypatch.setattr(analyzer, "should_trigger_analysis", lambda *args, **kwargs: False)
    monkeypatch.setattr(memory, "rebuild_lead_memory_task", lambda *args, **kwargs: None)

    response = client.post(
        "/chat",
        json={"message": "Ø¹Ø§ÙŠØ² Ø§Ø¹Ø±Ù Ø§Ù„Ø³Ø¹Ø± ÙˆØ§Ø­Ø¬Ø² Ø¯ÙŠÙ…Ùˆ", "user_id": "201001112223@s.whatsapp.net"},
        headers={"X-Internal-Secret": "secret", "X-Company-ID": "demo_resilience"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["reply"]
    assert body["internal_message_id"]

    messages = db.query(Message).filter(Message.company_id == "demo_resilience").all()
    assert any(msg.direction == "incoming" for msg in messages)
    assert any(msg.direction == "outgoing" for msg in messages)

    lead = db.query(Lead).filter(Lead.company_id == "demo_resilience").first()
    assert lead is not None
    assert lead.lead_score >= 75


def test_save_message_emits_live_workspace_event(db):
    company = _seed_company(db, company_id="demo_sync_events")

    save_message(
        db,
        company.company_id,
        "201001112223@s.whatsapp.net",
        "user",
        "مرحبا",
        "msg-sync-1",
        "incoming",
    )

    events = db.query(SystemEvent).filter(SystemEvent.company_id == company.company_id).all()
    event_types = {event.event_type for event in events}

    assert "message.created" in event_types
    assert "message.received" in event_types


def test_chat_retry_with_same_external_message_id_is_idempotent(client, db, monkeypatch):
    import brain
    import engine.analyzer as analyzer
    import engine.memory as memory

    company = _seed_company(db, company_id="demo_idempotency")
    monkeypatch.setattr(brain, "groq_client", _FailingGroq())
    monkeypatch.setattr(analyzer, "should_trigger_analysis", lambda *args, **kwargs: False)
    monkeypatch.setattr(memory, "rebuild_lead_memory_task", lambda *args, **kwargs: None)

    payload = {
        "message": "I want to buy and book a demo.",
        "user_id": "201001112223@s.whatsapp.net",
        "external_message_id": "wamid.retry-1",
    }
    headers = {"X-Internal-Secret": "secret", "X-Company-ID": company.company_id}

    first = client.post("/chat", json=payload, headers=headers)
    second = client.post("/chat", json=payload, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["reply"]
    assert second.json()["reply"] == first.json()["reply"]
    assert second.json()["duplicate"] is True
    assert second.json()["redeliver_existing_reply"] is True
    assert second.json()["internal_message_id"] == first.json()["internal_message_id"]

    messages = db.query(Message).filter(Message.company_id == company.company_id).all()
    assert len(messages) == 2
    assert sum(msg.direction == "incoming" for msg in messages) == 1
    assert sum(msg.direction == "outgoing" for msg in messages) == 1


def test_chat_repairs_mojibake_arabic_reply_before_persisting(client, db, monkeypatch):
    import brain
    import engine.analyzer as analyzer
    import engine.memory as memory

    company = _seed_company(db, company_id="demo_arabic_encoding")
    monkeypatch.setattr(brain, "groq_client", _MojibakeGroq())
    monkeypatch.setattr(analyzer, "should_trigger_analysis", lambda *args, **kwargs: False)
    monkeypatch.setattr(memory, "rebuild_lead_memory_task", lambda *args, **kwargs: None)

    response = client.post(
        "/chat",
        json={"message": "\u0627\u0644\u0633\u0644\u0627\u0645 \u0639\u0644\u064a\u0643\u0645", "user_id": "201001112224@s.whatsapp.net", "external_message_id": "wamid.arabic-1"},
        headers={"X-Internal-Secret": "secret", "X-Company-ID": company.company_id},
    )

    expected_reply = "\u0645\u0631\u062d\u0628\u0627\u060c \u0643\u064a\u0641 \u0623\u0642\u062f\u0631 \u0623\u0633\u0627\u0639\u062f\u0643\u061f"
    assert response.status_code == 200
    assert response.json()["reply"] == expected_reply
    outgoing = (
        db.query(Message)
        .filter(Message.company_id == company.company_id, Message.direction == "outgoing")
        .one()
    )
    assert outgoing.message == expected_reply


def test_intelligence_insights_degrades_gracefully(client, db):
    from jose import jwt
    _seed_company(db, company_id="demo_intel")
    db.add(
        Lead(
            company_id="demo_intel",
            name="At Risk Customer",
            phone="01011112222",
            whatsapp_number="1011112222",
            interest="Demo Product",
            status="at-risk",
            stage="Objection Handling",
            ai_summary="Customer thinks the price is expensive.",
        )
    )
    db.commit()

    token = jwt.encode(
        {"company_id": "demo_intel", "role": "tenant", "token_type": "access"},
        "super-secret-test-key-32-chars-long",
        algorithm="HS256",
    )

    response = client.get("/api/v1/intelligence/insights", cookies={"access_token": token})

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert "insights" in body
    assert "strategic_recommendation" in body["insights"]
