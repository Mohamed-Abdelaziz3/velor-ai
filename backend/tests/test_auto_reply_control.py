import json
import asyncio
from types import SimpleNamespace

from jose import jwt

from database import Company, CompanyKnowledge, Lead, LeadEvidence, Message, SystemEvent, hash_api_key, save_message


class _FailingCompletions:
    async def create(self, *args, **kwargs):
        raise RuntimeError("simulated provider outage")


class _FailingChat:
    completions = _FailingCompletions()


class _FailingGroq:
    chat = _FailingChat()


class _OkAsyncClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post(self, *args, **kwargs):
        return SimpleNamespace(raise_for_status=lambda: None)


def _token(company_id, role="tenant"):
    return jwt.encode(
        {"company_id": company_id, "role": role, "token_type": "access"},
        "super-secret-test-key-32-chars-long",
        algorithm="HS256",
    )


def _seed_company(db, company_id="auto_reply_co", products_data='[{"name":"Demo Product","price":"500 EGP"}]'):
    company = Company(
        company_id=company_id,
        company_name="Auto Reply Company",
        email=f"{company_id}@example.com",
        password="hashed",
        api_key_hash=hash_api_key(f"{company_id}-api-key"),
        plan="PRO",
    )
    db.add(company)
    db.add(
        CompanyKnowledge(
            company_id=company_id,
            system_prompt="You are a sales assistant.",
            products_data=products_data,
            knowledge_base="",
        )
    )
    db.commit()
    return company


def _patch_chat_dependencies(monkeypatch):
    import brain
    import engine.analyzer as analyzer
    import engine.memory as memory

    monkeypatch.setattr(brain, "groq_client", _FailingGroq())
    monkeypatch.setattr(analyzer, "should_trigger_analysis", lambda *args, **kwargs: False)
    monkeypatch.setattr(memory, "rebuild_lead_memory_task", lambda *args, **kwargs: None)


def _chat(client, company_id, message="What is the price for Demo Product?", external_message_id=None):
    payload = {
        "message": message,
        "user_id": "201001112223@s.whatsapp.net",
    }
    if external_message_id:
        payload["external_message_id"] = external_message_id
    return client.post(
        "/chat",
        json=payload,
        headers={"X-Internal-Secret": "secret", "X-Company-ID": company_id},
    )


def test_default_company_and_lead_state_auto_replies_normally(client, db, monkeypatch):
    company = _seed_company(db, "auto_reply_default")
    company_id = company.company_id
    _patch_chat_dependencies(monkeypatch)

    response = _chat(client, company_id)

    assert response.status_code == 200
    assert response.json()["reply"]
    assert response.json()["internal_message_id"]
    assert "auto_reply_skipped" not in response.json()
    assert db.query(Message).filter(Message.company_id == company_id, Message.direction == "incoming").count() == 1
    assert db.query(Message).filter(Message.company_id == company_id, Message.direction == "outgoing", Message.sender == "assistant").count() == 1


def test_company_global_auto_reply_off_skips_automatic_reply(client, db):
    company = _seed_company(db, "auto_reply_company_off")
    company_id = company.company_id
    company.bot_auto_reply_enabled = False
    db.commit()

    response = _chat(client, company_id, external_message_id="wamid.company-off-1")

    assert response.status_code == 200
    assert response.json()["reply"] is None
    assert response.json()["auto_reply_skipped"] is True
    assert response.json()["reason"] == "company_auto_reply_disabled"
    assert db.query(Message).filter(Message.company_id == company_id, Message.direction == "incoming").count() == 1
    assert db.query(Message).filter(Message.company_id == company_id, Message.direction == "outgoing").count() == 0


def test_lead_human_takeover_skips_automatic_reply(client, db):
    company = _seed_company(db, "auto_reply_takeover")
    company_id = company.company_id
    db.add(
        Lead(
            company_id=company_id,
            name="Paused Customer",
            phone="1001112223",
            whatsapp_number="1001112223",
            whatsapp_jid="201001112223@s.whatsapp.net",
            interest="Demo Product",
            is_paused=True,
        )
    )
    db.commit()

    response = _chat(client, company_id)

    assert response.status_code == 200
    assert response.json()["reply"] is None
    assert response.json()["auto_reply_skipped"] is True
    assert response.json()["reason"] == "human_takeover_active"
    assert db.query(Message).filter(Message.company_id == company_id, Message.direction == "outgoing").count() == 0


def test_inbound_message_and_evidence_are_persisted_when_auto_reply_skipped(client, db):
    company = _seed_company(db, "auto_reply_evidence")
    company_id = company.company_id
    company.bot_auto_reply_enabled = False
    db.commit()

    response = _chat(client, company_id, message="What is the price?")

    assert response.status_code == 200
    incoming = db.query(Message).filter(Message.company_id == company_id, Message.direction == "incoming").one()
    evidence = db.query(LeadEvidence).filter(LeadEvidence.message_internal_id == incoming.internal_message_id).all()
    lead = db.query(Lead).filter(Lead.company_id == company_id).one()

    assert incoming.message == "What is the price?"
    assert {row.evidence_type for row in evidence} == {"price_question"}
    assert {row.lead_id for row in evidence} == {lead.id}


def test_product_pricing_evidence_remains_available_when_auto_reply_skipped(client, db):
    company = _seed_company(db, "auto_reply_product_context")
    company_id = company.company_id
    company.bot_auto_reply_enabled = False
    db.commit()

    response = _chat(client, company_id, message="What is the price for Demo Product?")

    assert response.status_code == 200
    product_evidence = db.query(LeadEvidence).filter(LeadEvidence.company_id == company_id, LeadEvidence.evidence_type == "product_mention").one()
    metadata = json.loads(product_evidence.metadata_json or "{}")

    assert product_evidence.normalized_value == "Demo Product"
    assert metadata["known_price"] == 500.0
    assert metadata["currency"] == "EGP"


def test_duplicate_external_message_id_preserves_skipped_behavior(client, db):
    company = _seed_company(db, "auto_reply_duplicate_skip")
    company_id = company.company_id
    company.bot_auto_reply_enabled = False
    db.commit()

    first = _chat(client, company_id, external_message_id="wamid.skip-dup-1")
    second = _chat(client, company_id, external_message_id="wamid.skip-dup-1")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["auto_reply_skipped"] is True
    assert second.json()["duplicate"] is True
    assert second.json()["auto_reply_skipped"] is True
    assert second.json()["reason"] == "company_auto_reply_disabled"
    assert db.query(Message).filter(Message.company_id == company_id, Message.direction == "incoming").count() == 1
    assert db.query(Message).filter(Message.company_id == company_id, Message.direction == "outgoing").count() == 0
    assert db.query(SystemEvent).filter(SystemEvent.company_id == company_id, SystemEvent.event_type == "auto_reply.skipped").count() == 1


def test_duplicate_external_message_id_redelivers_unsent_existing_reply(client, db):
    company = _seed_company(db, "auto_reply_duplicate_redeliver")
    company_id = company.company_id
    user_id = "146879794905304@lid"
    incoming_external_id = "wamid.duplicate-redeliver"

    save_message(
        db,
        company_id,
        user_id,
        "user",
        "Please reply",
        "incoming-redeliver-msg",
        "incoming",
        incoming_external_id,
    )
    save_message(
        db,
        company_id,
        user_id,
        "assistant",
        "Existing unsent reply",
        "assistant-redeliver-msg",
        "outgoing",
        delivery_status="pending",
    )

    response = _chat(client, company_id, message="Please reply", external_message_id=incoming_external_id)

    assert response.status_code == 200
    assert response.json()["reply"] == "Existing unsent reply"
    assert response.json()["internal_message_id"] == "assistant-redeliver-msg"
    assert response.json()["duplicate"] is True
    assert response.json()["redeliver_existing_reply"] is True
    assert db.query(Message).filter(Message.company_id == company_id, Message.direction == "outgoing").count() == 1


def test_cross_company_user_cannot_toggle_another_company_bot_settings(client, db):
    company_a = _seed_company(db, "auto_reply_company_a")
    company_b = _seed_company(db, "auto_reply_company_b")
    company_a_id = company_a.company_id
    company_b_id = company_b.company_id

    response = client.post(
        f"/api/company/bot/auto-reply?company_id={company_b_id}",
        json={"enabled": False},
        cookies={"access_token": _token(company_a_id)},
    )

    company_b = db.query(Company).filter(Company.company_id == company_b_id).one()
    assert response.status_code == 403
    assert company_b.bot_auto_reply_enabled is True


def test_company_user_can_toggle_own_bot_auto_reply(client, db):
    company = _seed_company(db, "auto_reply_toggle_own")
    company_id = company.company_id

    response = client.post(
        "/api/company/bot/auto-reply",
        json={"enabled": False},
        cookies={"access_token": _token(company_id)},
    )

    company = db.query(Company).filter(Company.company_id == company_id).one()
    assert response.status_code == 200
    assert response.json()["bot_auto_reply_enabled"] is False
    assert company.bot_auto_reply_enabled is False


def test_cross_company_user_cannot_toggle_another_company_lead(client, db):
    company_a = _seed_company(db, "auto_reply_lead_a")
    company_b = _seed_company(db, "auto_reply_lead_b")
    company_a_id = company_a.company_id
    company_b_id = company_b.company_id
    lead_b = Lead(
        company_id=company_b_id,
        name="Other Company Lead",
        phone="01099998888",
        whatsapp_number="1099998888",
        interest="Demo Product",
    )
    db.add(lead_b)
    db.commit()
    lead_b_id = lead_b.id

    response = client.post(
        f"/api/leads/{lead_b_id}/human-takeover/toggle",
        json={"enabled": True},
        cookies={"access_token": _token(company_a_id)},
    )

    lead_b = db.query(Lead).filter(Lead.id == lead_b_id).one()
    assert response.status_code == 404
    assert lead_b.is_paused is False


def test_manual_send_marks_lead_paused_and_records_owner_message(client, db, monkeypatch):
    import main

    company = _seed_company(db, "auto_reply_manual_send")
    company_id = company.company_id
    lead = Lead(
        company_id=company_id,
        name="Manual Customer",
        phone="1001112223",
        whatsapp_number="1001112223",
        whatsapp_jid="201001112223@s.whatsapp.net",
        interest="Demo Product",
    )
    db.add(lead)
    db.commit()
    lead_id = lead.id
    lead_whatsapp_number = lead.whatsapp_number
    monkeypatch.setattr(main.httpx, "AsyncClient", _OkAsyncClient)

    response = client.post(
        "/api/agent/outbound/send",
        json={"phone": lead_whatsapp_number, "message": "Human reply"},
        cookies={"access_token": _token(company_id)},
    )

    lead = db.query(Lead).filter(Lead.id == lead_id).one()
    owner_message = db.query(Message).filter(Message.company_id == company_id, Message.sender == "owner").one()
    assert response.status_code == 200
    assert lead.is_paused is True
    assert owner_message.message == "Human reply"


class _ReusedSession:
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self.db

    def __exit__(self, exc_type, exc, tb):
        return False


def _meta_payload(message_id="wamid.inbound.1", from_phone="201001112223", text="Hello"):
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": "meta-phone-id"},
                            "contacts": [{"profile": {"name": "Meta Customer"}}],
                            "messages": [
                                {
                                    "id": message_id,
                                    "from": from_phone,
                                    "type": "text",
                                    "text": {"body": text},
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }


def _fake_meta_ai_response(internal_in_id, internal_out_id):
    async def _fake(db, user_input, user_id, company_id, background_tasks=None, incoming_wa_message_id=None, persist_incoming=True, **kwargs):
        if persist_incoming:
            save_message(
                db,
                company_id,
                user_id,
                "user",
                user_input,
                internal_in_id,
                "incoming",
                wa_message_id=incoming_wa_message_id,
            )
        save_message(
            db,
            company_id,
            user_id,
            "assistant",
            "AI reply",
            internal_out_id,
            "outgoing",
            delivery_status="pending",
        )
        return "AI reply", internal_out_id

    return _fake


def _patch_meta_webhook(monkeypatch, db, company_id):
    import routers.webhook as webhook

    monkeypatch.setattr(webhook, "ENABLE_META_WEBHOOK", True)
    monkeypatch.setattr(webhook, "META_COMPANY_ID", company_id)
    monkeypatch.setattr(webhook, "SessionLocal", lambda: _ReusedSession(db))
    monkeypatch.setattr(webhook, "summarize_conversation", lambda *args, **kwargs: None)
    return webhook


def test_meta_webhook_marks_ai_reply_failed_when_whatsapp_dispatch_fails(client, db, monkeypatch):
    company = _seed_company(db, "meta_delivery_failed")
    webhook = _patch_meta_webhook(monkeypatch, db, company.company_id)
    monkeypatch.setattr(webhook, "META_GRAPH_API_TOKEN", "")
    monkeypatch.setattr(webhook, "META_PHONE_NUMBER_ID", "")
    monkeypatch.setattr(webhook, "get_ai_response", _fake_meta_ai_response("meta-in-failed", "meta-out-failed"))

    asyncio.run(webhook.process_webhook_payload(_meta_payload(message_id="wamid.meta.in.failed")))

    incoming = db.query(Message).filter(Message.company_id == company.company_id, Message.sender == "user").one()
    outgoing = db.query(Message).filter(Message.company_id == company.company_id, Message.sender == "assistant").one()
    update_event = (
        db.query(SystemEvent)
        .filter(SystemEvent.company_id == company.company_id, SystemEvent.event_type == "message.updated")
        .one()
    )
    update_payload = json.loads(update_event.payload)

    assert incoming.wa_message_id == "wamid.meta.in.failed"
    assert outgoing.delivery_status == "failed"
    assert update_payload["message_id"] == "meta-out-failed"
    assert update_payload["delivery_status"] == "failed"


def test_meta_webhook_marks_ai_reply_sent_with_meta_message_id(client, db, monkeypatch):
    company = _seed_company(db, "meta_delivery_sent")
    webhook = _patch_meta_webhook(monkeypatch, db, company.company_id)
    monkeypatch.setattr(webhook, "get_ai_response", _fake_meta_ai_response("meta-in-sent", "meta-out-sent"))

    async def _fake_send(phone, text):
        assert phone == "201001112223"
        assert text == "AI reply"
        return {"success": True, "wa_message_id": "wamid.meta.out.sent"}

    monkeypatch.setattr(webhook, "send_whatsapp_message", _fake_send)

    asyncio.run(webhook.process_webhook_payload(_meta_payload(message_id="wamid.meta.in.sent")))

    outgoing = db.query(Message).filter(Message.company_id == company.company_id, Message.sender == "assistant").one()
    update_event = (
        db.query(SystemEvent)
        .filter(SystemEvent.company_id == company.company_id, SystemEvent.event_type == "message.updated")
        .one()
    )
    update_payload = json.loads(update_event.payload)

    assert outgoing.delivery_status == "sent"
    assert outgoing.wa_message_id == "wamid.meta.out.sent"
    assert update_payload["wa_message_id"] == "wamid.meta.out.sent"
    assert update_payload["delivery_status"] == "sent"


def test_whatsapp_ack_allows_retry_recovery_from_failed_to_sent(client, db):
    company = _seed_company(db, "ack_retry_recovery")
    company_id = company.company_id
    db.add(
        Message(
            company_id=company_id,
            user_id="146879794905304@lid",
            sender="assistant",
            direction="outgoing",
            message="Retry me",
            internal_message_id="retry-recovery-msg",
            delivery_status="failed",
        )
    )
    db.commit()

    response = client.post(
        "/api/whatsapp/webhook/ack",
        json={
            "company_id": company_id,
            "internal_message_id": "retry-recovery-msg",
            "wa_message_id": "wamid.retry.sent",
            "status": "sent",
        },
        headers={"X-Internal-Secret": "secret"},
    )

    msg = db.query(Message).filter(Message.company_id == company_id, Message.internal_message_id == "retry-recovery-msg").one()
    assert response.status_code == 200
    assert response.json()["success"] is True
    assert msg.delivery_status == "sent"
    assert msg.wa_message_id == "wamid.retry.sent"
