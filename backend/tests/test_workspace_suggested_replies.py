import json
from types import SimpleNamespace

import httpx
from jose import jwt

from database import Company, CompanyKnowledge, Lead, LeadEvidence, Message, SystemEvent, WorkspaceSuggestedReply, hash_api_key
from services.workspace_suggestion_service import invalidate_prior_suggestions_for_inbound_message


class _OkAsyncClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post(self, *args, **kwargs):
        return SimpleNamespace(raise_for_status=lambda: None)


class _FailingAsyncClient(_OkAsyncClient):
    async def post(self, *args, **kwargs):
        raise httpx.RequestError("gateway unavailable")


def test_new_customer_turn_stales_only_older_active_suggestions_idempotently_and_per_tenant(db):
    company_a = _seed_company(db, "stale_turn_a")
    company_b = _seed_company(db, "stale_turn_b")
    lead_a = _seed_paused_lead(db, company_a.company_id)
    lead_b = _seed_paused_lead(db, company_b.company_id)
    rows = [
        WorkspaceSuggestedReply(company_id=company_a.company_id, lead_id=lead_a.id, source_message_internal_id="older-a-1", suggested_reply="old one", status="suggested"),
        WorkspaceSuggestedReply(company_id=company_a.company_id, lead_id=lead_a.id, source_message_internal_id="older-a-2", suggested_reply="old two", status="suggested"),
        WorkspaceSuggestedReply(company_id=company_a.company_id, lead_id=lead_a.id, source_message_internal_id="new-a", suggested_reply="current", status="suggested"),
        WorkspaceSuggestedReply(company_id=company_a.company_id, lead_id=lead_a.id, source_message_internal_id="used-a", suggested_reply="used", status="used"),
        WorkspaceSuggestedReply(company_id=company_a.company_id, lead_id=lead_a.id, source_message_internal_id="stale-a", suggested_reply="stale", status="stale", stale_reason="owner_replied"),
        WorkspaceSuggestedReply(company_id=company_b.company_id, lead_id=lead_b.id, source_message_internal_id="older-b", suggested_reply="private", status="suggested"),
    ]
    db.add_all(rows)
    db.commit()

    assert invalidate_prior_suggestions_for_inbound_message(
        db, company_id=company_a.company_id, lead_id=lead_a.id, inbound_message_internal_id="new-a"
    ) == 2
    assert invalidate_prior_suggestions_for_inbound_message(
        db, company_id=company_a.company_id, lead_id=lead_a.id, inbound_message_internal_id="new-a"
    ) == 0
    db.commit()

    by_source = {row.source_message_internal_id: row for row in db.query(WorkspaceSuggestedReply).all()}
    assert by_source["older-a-1"].status == by_source["older-a-2"].status == "stale"
    assert by_source["older-a-1"].stale_reason == by_source["older-a-2"].stale_reason == "new_customer_turn"
    assert by_source["new-a"].status == "suggested"
    assert by_source["used-a"].status == "used"
    assert by_source["stale-a"].stale_reason == "owner_replied"
    assert by_source["older-b"].status == "suggested"


def _token(company_id, role="tenant"):
    return jwt.encode(
        {"company_id": company_id, "role": role, "token_type": "access"},
        "super-secret-test-key-32-chars-long",
        algorithm="HS256",
    )


def _seed_company(db, company_id="workspace_suggestion_co", products_data='[{"name":"Demo Product","price":"500 EGP"}]'):
    company = Company(
        company_id=company_id,
        company_name="Workspace Suggestion Company",
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


def _seed_paused_lead(db, company_id, phone="1001112223"):
    lead = Lead(
        company_id=company_id,
        name="Paused Customer",
        phone=phone,
        whatsapp_number=phone,
        whatsapp_jid="201001112223@s.whatsapp.net",
        interest="Demo Product",
        is_paused=True,
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead


def _chat(client, company_id, message="What is the price for Demo Product?", external_message_id=None):
    payload = {"message": message, "user_id": "201001112223@s.whatsapp.net"}
    if external_message_id:
        payload["external_message_id"] = external_message_id
    return client.post(
        "/chat",
        json=payload,
        headers={"X-Internal-Secret": "secret", "X-Company-ID": company_id},
    )


def test_human_takeover_inbound_skips_auto_reply_and_creates_suggested_reply(client, db):
    company = _seed_company(db, "workspace_human_takeover")
    company_id = company.company_id
    lead = _seed_paused_lead(db, company_id)
    lead_id = lead.id

    response = _chat(client, company_id, external_message_id="wamid.workspace-human-1")

    suggestion = db.query(WorkspaceSuggestedReply).filter(WorkspaceSuggestedReply.company_id == company_id).one()
    assert response.status_code == 200
    assert response.json()["auto_reply_skipped"] is True
    assert response.json()["reason"] == "human_takeover_active"
    assert suggestion.lead_id == lead_id
    assert suggestion.source_message_internal_id == response.json()["internal_message_id"]
    assert suggestion.status == "suggested"
    assert suggestion.suggested_reply
    assert "500" in suggestion.suggested_reply
    assert db.query(Message).filter(Message.company_id == company_id, Message.direction == "outgoing").count() == 0
    assert db.query(SystemEvent).filter(
        SystemEvent.company_id == company_id,
        SystemEvent.event_type == "pilot.suggestion_generated",
    ).count() == 1


def test_company_auto_reply_off_creates_suggested_reply_without_outgoing_message(client, db):
    company = _seed_company(db, "workspace_company_off")
    company_id = company.company_id
    company.bot_auto_reply_enabled = False
    db.commit()

    response = _chat(client, company_id, message="What is the price?", external_message_id="wamid.workspace-company-1")

    suggestion = db.query(WorkspaceSuggestedReply).filter(WorkspaceSuggestedReply.company_id == company_id).one()
    incoming = db.query(Message).filter(Message.company_id == company_id, Message.direction == "incoming").one()
    evidence = db.query(LeadEvidence).filter(LeadEvidence.message_internal_id == incoming.internal_message_id).all()

    assert response.status_code == 200
    assert response.json()["reason"] == "company_auto_reply_disabled"
    assert incoming.message == "What is the price?"
    assert {row.evidence_type for row in evidence} == {"price_question"}
    assert suggestion.source_message_internal_id == incoming.internal_message_id
    assert suggestion.suggested_reply
    assert db.query(Message).filter(Message.company_id == company_id, Message.direction == "outgoing").count() == 0


def test_suggested_reply_does_not_invent_price_when_price_unknown(client, db):
    company = _seed_company(db, "workspace_unknown_price", products_data='[{"name":"Demo Product","price":"call us"}]')
    company_id = company.company_id
    company.bot_auto_reply_enabled = False
    db.commit()

    response = _chat(client, company_id, message="What is the price for Demo Product?")

    suggestion = db.query(WorkspaceSuggestedReply).filter(WorkspaceSuggestedReply.company_id == company_id).one()
    missing_data = json.loads(suggestion.missing_data or "[]")
    assert response.status_code == 200
    assert "500" not in suggestion.suggested_reply
    assert "price" in missing_data


def test_suggested_reply_uses_known_product_price_only_from_product_context(client, db):
    company = _seed_company(db, "workspace_known_price", products_data='[{"name":"Demo Product","price":750,"currency":"EGP"}]')
    company_id = company.company_id
    company.bot_auto_reply_enabled = False
    db.commit()

    response = _chat(client, company_id, message="What is the price for Demo Product?")

    suggestion = db.query(WorkspaceSuggestedReply).filter(WorkspaceSuggestedReply.company_id == company_id).one()
    missing_data = json.loads(suggestion.missing_data or "[]")
    assert response.status_code == 200
    assert "750" in suggestion.suggested_reply
    assert "EGP" in suggestion.suggested_reply
    assert "quantity" in missing_data


def test_duplicate_external_message_id_does_not_create_duplicate_suggestions(client, db):
    company = _seed_company(db, "workspace_duplicate")
    company_id = company.company_id
    company.bot_auto_reply_enabled = False
    db.commit()

    first = _chat(client, company_id, external_message_id="wamid.workspace-dup-1")
    second = _chat(client, company_id, external_message_id="wamid.workspace-dup-1")

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["duplicate"] is True
    assert db.query(WorkspaceSuggestedReply).filter(WorkspaceSuggestedReply.company_id == company_id).count() == 1
    assert db.query(Message).filter(Message.company_id == company_id, Message.direction == "incoming").count() == 1


def test_workspace_suggestions_are_returned_in_customer_profile(client, db):
    company = _seed_company(db, "workspace_profile")
    company_id = company.company_id
    company.bot_auto_reply_enabled = False
    db.commit()
    response = _chat(client, company_id, external_message_id="wamid.workspace-profile-1")
    lead = db.query(Lead).filter(Lead.company_id == company_id).one()
    lead_id = lead.id

    profile = client.get(f"/api/v1/crm/customers/{lead.id}", cookies={"access_token": _token(company_id)})

    assert response.status_code == 200
    assert profile.status_code == 200
    suggestions = profile.json()["customer"]["suggested_replies"]
    assert len(suggestions) == 1
    assert suggestions[0]["source_message_internal_id"] == response.json()["internal_message_id"]


def test_cross_company_access_to_suggestions_is_protected(client, db):
    company_a = _seed_company(db, "workspace_company_a")
    company_b = _seed_company(db, "workspace_company_b")
    company_a_id = company_a.company_id
    company_b_id = company_b.company_id
    company_b.bot_auto_reply_enabled = False
    db.commit()
    _chat(client, company_b_id, external_message_id="wamid.workspace-cross-1")
    lead_b = db.query(Lead).filter(Lead.company_id == company_b_id).one()
    suggestion = db.query(WorkspaceSuggestedReply).filter(WorkspaceSuggestedReply.company_id == company_b_id).one()
    suggestion_id = suggestion.id

    list_response = client.get(f"/api/v1/crm/customers/{lead_b.id}/suggested-replies", cookies={"access_token": _token(company_a_id)})
    patch_response = client.patch(
        f"/api/v1/crm/customers/{lead_b.id}/suggested-replies/{suggestion_id}",
        json={"status": "dismissed"},
        cookies={"access_token": _token(company_a_id)},
    )

    suggestion = db.query(WorkspaceSuggestedReply).filter(WorkspaceSuggestedReply.id == suggestion_id).one()
    assert list_response.status_code == 404
    assert patch_response.status_code == 404
    assert suggestion.status == "suggested"


def test_suggestion_can_be_dismissed_but_cannot_be_marked_used_without_a_send(client, db):
    company = _seed_company(db, "workspace_status")
    company_id = company.company_id
    company.bot_auto_reply_enabled = False
    db.commit()
    _chat(client, company_id, external_message_id="wamid.workspace-status-1")
    lead = db.query(Lead).filter(Lead.company_id == company_id).one()
    lead_id = lead.id
    suggestion = db.query(WorkspaceSuggestedReply).filter(WorkspaceSuggestedReply.company_id == company_id).one()
    suggestion_id = suggestion.id

    response = client.patch(
        f"/api/v1/crm/customers/{lead_id}/suggested-replies/{suggestion_id}",
        json={"status": "dismissed"},
        cookies={"access_token": _token(company_id)},
    )

    suggestion = db.query(WorkspaceSuggestedReply).filter(WorkspaceSuggestedReply.id == suggestion_id).one()
    assert response.status_code == 200
    assert response.json()["suggested_reply"]["status"] == "dismissed"
    assert suggestion.status == "dismissed"
    assert db.query(SystemEvent).filter(
        SystemEvent.company_id == company_id,
        SystemEvent.event_type == "pilot.suggestion_dismissed",
    ).count() == 1

    used_response = client.patch(
        f"/api/v1/crm/customers/{lead_id}/suggested-replies/{suggestion_id}",
        json={"status": "used"},
        cookies={"access_token": _token(company_id)},
    )
    assert used_response.status_code == 400


def test_suggestion_send_metadata_and_insert_telemetry_are_server_authoritative(client, db, monkeypatch):
    import main

    company_a = _seed_company(db, "workspace_authority_a")
    company_b = _seed_company(db, "workspace_authority_b")
    company_a_id = company_a.company_id
    company_b_id = company_b.company_id
    lead_a = _seed_paused_lead(db, company_a_id, phone="1001112299")
    lead_b = _seed_paused_lead(db, company_b_id, phone="1001112288")
    lead_a_id = lead_a.id
    lead_b_id = lead_b.id
    lead_a_phone = lead_a.whatsapp_number
    lead_a_jid = lead_a.whatsapp_jid
    lead_b_jid = lead_b.whatsapp_jid
    monkeypatch.setattr(main.httpx, "AsyncClient", _OkAsyncClient)

    source_a = Message(
        company_id=company_a_id,
        user_id=lead_a_jid,
        sender="user",
        direction="incoming",
        message="Can you confirm availability?",
        internal_message_id="authority-source-a",
        delivery_status="received",
    )
    source_b = Message(
        company_id=company_b_id,
        user_id=lead_b_jid,
        sender="user",
        direction="incoming",
        message="Private tenant B question",
        internal_message_id="authority-source-b",
        delivery_status="received",
    )
    db.add_all([source_a, source_b])
    db.flush()
    suggestion_a = WorkspaceSuggestedReply(
        company_id=company_a_id,
        lead_id=lead_a_id,
        source_message_id=source_a.id,
        source_message_internal_id=source_a.internal_message_id,
        suggested_reply="It is available.",
        style="natural",
        variants_json=json.dumps([{"style": "natural", "text": "It is available."}]),
        status="suggested",
    )
    suggestion_b = WorkspaceSuggestedReply(
        company_id=company_b_id,
        lead_id=lead_b_id,
        source_message_id=source_b.id,
        source_message_internal_id=source_b.internal_message_id,
        suggested_reply="Tenant B private reply.",
        style="natural",
        variants_json=json.dumps([{"style": "natural", "text": "Tenant B private reply."}]),
        status="suggested",
    )
    db.add_all([suggestion_a, suggestion_b])
    db.commit()
    suggestion_a_id = suggestion_a.id
    suggestion_b_id = suggestion_b.id
    source_a_internal_id = source_a.internal_message_id

    cookies_a = {"access_token": _token(company_a_id)}
    base_payload = {
        "phone": lead_a_phone,
        "message": "It is available.",
        "source_message_internal_id": source_a_internal_id,
        "variant_style": "natural",
    }
    invalid_id = client.post(
        "/api/agent/outbound/send",
        json={**base_payload, "suggestion_id": 999999},
        cookies=cookies_a,
    )
    cross_tenant = client.post(
        "/api/agent/outbound/send",
        json={**base_payload, "suggestion_id": suggestion_b_id},
        cookies=cookies_a,
    )
    wrong_source = client.post(
        "/api/agent/outbound/send",
        json={**base_payload, "suggestion_id": suggestion_a_id, "source_message_internal_id": "wrong-source"},
        cookies=cookies_a,
    )
    wrong_variant = client.post(
        "/api/agent/outbound/send",
        json={**base_payload, "suggestion_id": suggestion_a_id, "variant_style": "aggressive"},
        cookies=cookies_a,
    )
    assert invalid_id.status_code == 404
    assert cross_tenant.status_code == 404
    assert wrong_source.status_code == 409
    assert wrong_variant.status_code == 409

    inserted = client.post(
        "/api/v1/operations/telemetry",
        json={"events": [{
            "event_name": "suggestion_inserted",
            "client_event_id": "authority-insert-a",
            "metadata": {
                "lead_id": lead_a_id,
                "suggestion_id": suggestion_a_id,
                "source_message_internal_id": source_a_internal_id,
                "variant_style": "natural",
                "surface": "workspace",
            },
        }]},
        cookies=cookies_a,
    )
    forged_insert = client.post(
        "/api/v1/operations/telemetry",
        json={"events": [{
            "event_name": "suggestion_inserted",
            "client_event_id": "authority-insert-forged",
            "metadata": {"lead_id": lead_a_id, "suggestion_id": suggestion_b_id},
        }]},
        cookies=cookies_a,
    )
    assert inserted.status_code == 200
    assert forged_insert.status_code == 400

    sent = client.post(
        "/api/agent/outbound/send",
        json={
            **base_payload,
            "message": "It is available, and I can help with the next step.",
            "suggestion_id": suggestion_a_id,
            "suggestion_edited": False,
        },
        cookies=cookies_a,
    )
    assert sent.status_code == 200
    sent_payload = json.loads(db.query(SystemEvent).filter(
        SystemEvent.company_id == company_a_id,
        SystemEvent.event_type == "pilot.suggestion_sent",
    ).one().payload)
    assert sent_payload["metadata"]["edited"] is True

    stale_source = Message(
        company_id=company_a_id,
        user_id=lead_a_jid,
        sender="user",
        direction="incoming",
        message="Old customer turn",
        internal_message_id="authority-stale-source",
        delivery_status="received",
    )
    db.add(stale_source)
    db.flush()
    stale_suggestion = WorkspaceSuggestedReply(
        company_id=company_a_id,
        lead_id=lead_a_id,
        source_message_id=stale_source.id,
        source_message_internal_id=stale_source.internal_message_id,
        suggested_reply="Reply to old turn",
        style="natural",
        variants_json=json.dumps([{"style": "natural", "text": "Reply to old turn"}]),
        status="suggested",
    )
    db.add(stale_suggestion)
    db.flush()
    newer = Message(
        company_id=company_a_id,
        user_id=lead_a_jid,
        sender="user",
        direction="incoming",
        message="New customer turn",
        internal_message_id="authority-newer-source",
        delivery_status="received",
    )
    db.add(newer)
    db.commit()
    stale_source_internal_id = stale_source.internal_message_id
    stale_suggestion_id = stale_suggestion.id

    stale_send = client.post(
        "/api/agent/outbound/send",
        json={
            "phone": lead_a_phone,
            "message": "Reply to old turn",
            "source_message_internal_id": stale_source_internal_id,
            "suggestion_id": stale_suggestion_id,
            "variant_style": "natural",
        },
        cookies=cookies_a,
    )
    stale_suggestion = db.query(WorkspaceSuggestedReply).filter(WorkspaceSuggestedReply.id == stale_suggestion_id).one()
    assert stale_send.status_code == 409
    assert stale_suggestion.status == "stale"
    assert db.query(SystemEvent).filter(
        SystemEvent.company_id == company_a_id,
        SystemEvent.event_type == "pilot.suggestion_stale_blocked",
    ).count() == 1


def test_manual_send_still_works_with_suggested_replies(client, db, monkeypatch):
    import main

    company = _seed_company(db, "workspace_manual_send")
    company_id = company.company_id
    lead = _seed_paused_lead(db, company_id)
    monkeypatch.setattr(main.httpx, "AsyncClient", _OkAsyncClient)

    response = client.post(
        "/api/agent/outbound/send",
        json={"phone": lead.whatsapp_number, "message": "Human edited reply"},
        cookies={"access_token": _token(company_id)},
    )

    owner_message = db.query(Message).filter(Message.company_id == company_id, Message.sender == "owner").one()
    assert response.status_code == 200
    assert owner_message.message == "Human edited reply"


def test_suggestion_is_marked_used_only_after_verified_send_success(client, db, monkeypatch):
    import main

    company = _seed_company(db, "workspace_verified_suggestion_send")
    lead = _seed_paused_lead(db, company.company_id)
    monkeypatch.setattr(main.httpx, "AsyncClient", _OkAsyncClient)
    source = Message(
        company_id=company.company_id,
        user_id=lead.whatsapp_jid,
        sender="user",
        direction="incoming",
        message="Is it available?",
        internal_message_id="verified-suggestion-source",
        delivery_status="received",
    )
    db.add(source)
    db.flush()
    suggestion = WorkspaceSuggestedReply(
        company_id=company.company_id,
        lead_id=lead.id,
        source_message_id=source.id,
        source_message_internal_id=source.internal_message_id,
        suggested_reply="Yes, it is available.",
        style="natural",
        variants_json=json.dumps([{"style": "natural", "text": "Yes, it is available."}]),
        status="suggested",
    )
    db.add(suggestion)
    db.commit()
    company_id = company.company_id
    suggestion_id = suggestion.id
    source_id = source.id
    source_internal_id = source.internal_message_id
    phone = lead.whatsapp_number

    response = client.post(
        "/api/agent/outbound/send",
        json={
            "phone": phone,
            "message": "Yes, it is available.",
            "source_message_internal_id": source_internal_id,
            "suggestion_id": suggestion_id,
            "variant_style": "natural",
            "suggestion_edited": True,
        },
        cookies={"access_token": _token(company_id)},
    )

    suggestion = db.query(WorkspaceSuggestedReply).filter(WorkspaceSuggestedReply.id == suggestion_id).one()
    outbound = db.query(Message).filter(
        Message.company_id == company_id,
        Message.sender == "owner",
    ).one()
    sent_event = db.query(SystemEvent).filter(
        SystemEvent.company_id == company_id,
        SystemEvent.event_type == "pilot.suggestion_sent",
    ).one()
    assert response.status_code == 200
    assert suggestion.status == "used"
    assert outbound.in_reply_to_message_id == source_id
    assert json.loads(sent_event.payload)["metadata"]["edited"] is False


def test_failed_gateway_send_keeps_suggestion_active_and_unattributed(client, db, monkeypatch):
    import main

    company = _seed_company(db, "workspace_failed_suggestion_send")
    lead = _seed_paused_lead(db, company.company_id)
    monkeypatch.setattr(main.httpx, "AsyncClient", _FailingAsyncClient)
    source = Message(
        company_id=company.company_id,
        user_id=lead.whatsapp_jid,
        sender="user",
        direction="incoming",
        message="Can you confirm?",
        internal_message_id="failed-suggestion-source",
        delivery_status="received",
    )
    db.add(source)
    db.flush()
    suggestion = WorkspaceSuggestedReply(
        company_id=company.company_id,
        lead_id=lead.id,
        source_message_id=source.id,
        source_message_internal_id=source.internal_message_id,
        suggested_reply="I can confirm the known details.",
        style="natural",
        variants_json=json.dumps([{"style": "natural", "text": "I can confirm the known details."}]),
        status="suggested",
    )
    db.add(suggestion)
    db.commit()
    company_id = company.company_id
    suggestion_id = suggestion.id
    source_internal_id = source.internal_message_id
    suggested_text = suggestion.suggested_reply
    phone = lead.whatsapp_number

    response = client.post(
        "/api/agent/outbound/send",
        json={
            "phone": phone,
            "message": suggested_text,
            "source_message_internal_id": source_internal_id,
            "suggestion_id": suggestion_id,
            "variant_style": "natural",
        },
        cookies={"access_token": _token(company_id)},
    )

    suggestion = db.query(WorkspaceSuggestedReply).filter(WorkspaceSuggestedReply.id == suggestion_id).one()
    assert response.status_code == 502
    assert suggestion.status == "suggested"
    assert db.query(SystemEvent).filter(
        SystemEvent.company_id == company_id,
        SystemEvent.event_type == "pilot.suggestion_sent",
    ).count() == 0


def test_suggestion_derived_send_requires_its_source_to_remain_latest(client, db, monkeypatch):
    import main

    company = _seed_company(db, "workspace_manual_stale_cas")
    company_id = company.company_id
    lead = _seed_paused_lead(db, company_id)
    monkeypatch.setattr(main.httpx, "AsyncClient", _OkAsyncClient)
    source = Message(
        company_id=company_id,
        user_id=lead.whatsapp_jid,
        sender="user",
        direction="incoming",
        message="What is the price?",
        internal_message_id="draft-cas-source",
        delivery_status="received",
    )
    newer = Message(
        company_id=company_id,
        user_id=lead.whatsapp_jid,
        sender="user",
        direction="incoming",
        message="Actually, is it available?",
        internal_message_id="draft-cas-newer",
        delivery_status="received",
    )
    db.add_all([source, newer])
    db.commit()

    response = client.post(
        "/api/agent/outbound/send",
        json={
            "phone": lead.whatsapp_number,
            "message": "The old price answer",
            "source_message_internal_id": source.internal_message_id,
        },
        cookies={"access_token": _token(company_id)},
    )

    assert response.status_code == 409
    assert db.query(Message).filter(
        Message.company_id == company_id,
        Message.sender == "owner",
    ).count() == 0


def test_suggestion_derived_send_accepts_current_unanswered_source(client, db, monkeypatch):
    import main

    company = _seed_company(db, "workspace_manual_current_cas")
    company_id = company.company_id
    lead = _seed_paused_lead(db, company_id)
    monkeypatch.setattr(main.httpx, "AsyncClient", _OkAsyncClient)
    source = Message(
        company_id=company_id,
        user_id=lead.whatsapp_jid,
        sender="user",
        direction="incoming",
        message="Is it available?",
        internal_message_id="draft-cas-current",
        delivery_status="received",
    )
    db.add(source)
    db.commit()

    response = client.post(
        "/api/agent/outbound/send",
        json={
            "phone": lead.whatsapp_number,
            "message": "Yes, it is available.",
            "source_message_internal_id": source.internal_message_id,
        },
        cookies={"access_token": _token(company_id)},
    )

    assert response.status_code == 200
    assert db.query(Message).filter(
        Message.company_id == company_id,
        Message.sender == "owner",
        Message.message == "Yes, it is available.",
    ).count() == 1


def test_customer_profile_round_trips_clean_arabic_messages_and_ownership(client, db):
    company = _seed_company(db, "workspace_arabic_roundtrip")
    company_id = company.company_id
    lead = _seed_paused_lead(db, company_id)
    db.add_all(
        [
            Message(
                company_id=company_id,
                user_id=lead.whatsapp_jid,
                sender="user",
                direction="incoming",
                message="السلام عليكم، أريد معرفة السعر.",
                internal_message_id="msg-arabic-user",
                delivery_status="received",
            ),
            Message(
                company_id=company_id,
                user_id=lead.whatsapp_jid,
                sender="assistant",
                direction="outgoing",
                message="أهلا بك، سأساعدك بالمعلومات المتاحة.",
                internal_message_id="msg-arabic-assistant",
                delivery_status="delivered",
            ),
            Message(
                company_id=company_id,
                user_id=lead.whatsapp_jid,
                sender="owner",
                direction="outgoing",
                message="أنا أراجع التفاصيل الآن.",
                internal_message_id="msg-arabic-owner",
                delivery_status="sent",
            ),
        ]
    )
    db.commit()

    profile = client.get(f"/api/v1/crm/customers/{lead.id}", cookies={"access_token": _token(company_id)})

    assert profile.status_code == 200
    messages = [item for item in profile.json()["customer"]["timeline"] if item["type"] == "message"]
    assert [item["message"] for item in messages] == [
        "السلام عليكم، أريد معرفة السعر.",
        "أهلا بك، سأساعدك بالمعلومات المتاحة.",
        "أنا أراجع التفاصيل الآن.",
    ]
    assert [(item["sender"], item["direction"], item["is_ai"]) for item in messages] == [
        ("user", "incoming", False),
        ("assistant", "outgoing", True),
        ("owner", "outgoing", False),
    ]


def test_manual_send_returns_clean_arabic_owner_message(client, db, monkeypatch):
    import main

    company = _seed_company(db, "workspace_manual_arabic")
    company_id = company.company_id
    lead = _seed_paused_lead(db, company_id)
    monkeypatch.setattr(main.httpx, "AsyncClient", _OkAsyncClient)

    response = client.post(
        "/api/agent/outbound/send",
        json={"phone": lead.whatsapp_number, "message": "تم، سأرسل لك التفاصيل الآن."},
        cookies={"access_token": _token(company_id)},
    )

    assert response.status_code == 200
    payload = response.json()["message"]
    assert payload["message"] == "تم، سأرسل لك التفاصيل الآن."
    assert payload["sender"] == "owner"
    assert payload["direction"] == "outgoing"
    assert payload["is_ai"] is False


def test_customer_brief_uses_insufficient_data_without_fake_value(client, db):
    company = _seed_company(db, "workspace_brief_empty")
    company_id = company.company_id
    lead = _seed_paused_lead(db, company_id)

    profile = client.get(f"/api/v1/crm/customers/{lead.id}", cookies={"access_token": _token(company_id)})

    assert profile.status_code == 200
    customer = profile.json()["customer"]
    assert customer["permanent_context"]["identity"]["revenue_potential"] is None
    assert customer["customer_brief"]["insufficient_data"] is True
    assert customer["customer_brief"]["what_customer_wants"] == "لا توجد بيانات كافية بعد."


def test_customer_brief_maps_greeting_to_clean_state(client, db):
    company = _seed_company(db, "workspace_brief_greeting")
    company_id = company.company_id
    lead = _seed_paused_lead(db, company_id)
    db.add(
        Message(
            company_id=company_id,
            user_id=lead.whatsapp_jid,
            sender="user",
            direction="incoming",
            message="السلام عليكم",
            internal_message_id="msg-brief-greeting",
            delivery_status="received",
        )
    )
    db.commit()

    profile = client.get(f"/api/v1/crm/customers/{lead.id}", cookies={"access_token": _token(company_id)})
    brief = profile.json()["customer"]["customer_brief"]

    assert profile.status_code == 200
    assert brief["what_customer_wants"] == "تحية فقط"
    assert brief["latest_signal"] == "لا توجد نية شراء واضحة بعد."
    assert "نوع الخدمة" in brief["missing_data"]


def test_customer_brief_maps_service_inquiry_to_clean_state(client, db):
    company = _seed_company(db, "workspace_brief_service")
    company_id = company.company_id
    lead = _seed_paused_lead(db, company_id)
    db.add(
        Message(
            company_id=company_id,
            user_id=lead.whatsapp_jid,
            sender="user",
            direction="incoming",
            message="هاي، أنا بسأل على خدماتكم؟",
            internal_message_id="msg-brief-service",
            delivery_status="received",
        )
    )
    db.commit()

    profile = client.get(f"/api/v1/crm/customers/{lead.id}", cookies={"access_token": _token(company_id)})
    brief = profile.json()["customer"]["customer_brief"]

    assert profile.status_code == 200
    assert brief["what_customer_wants"] == "يستكشف الخدمات"
    assert "العميل يريد معرفة ما تقدمه" in brief["latest_signal"]
    assert "نوع الخدمة" in brief["missing_data"]
    assert "lead_evidence" not in json.dumps(brief, ensure_ascii=False)


def test_customer_brief_never_uses_short_raw_customer_text_as_state(client, db):
    company = _seed_company(db, "workspace_brief_raw_short")
    company_id = company.company_id
    lead = _seed_paused_lead(db, company_id)
    db.add(
        Message(
            company_id=company_id,
            user_id=lead.whatsapp_jid,
            sender="user",
            direction="incoming",
            message="استاذي؟",
            internal_message_id="msg-brief-short",
            delivery_status="received",
        )
    )
    db.commit()

    profile = client.get(f"/api/v1/crm/customers/{lead.id}", cookies={"access_token": _token(company_id)})
    brief = profile.json()["customer"]["customer_brief"]

    assert profile.status_code == 200
    assert brief["what_customer_wants"] == "ينتظر ردًا"
    assert brief["customer_state"] == "ينتظر ردًا"
    assert "يلفت الانتباه" in brief["latest_signal"] or "ينتظر ردًا" in brief["latest_signal"]
    assert brief["what_customer_wants"] != "استاذي؟"
    assert "استاذي" not in json.dumps(brief, ensure_ascii=False)


def test_customer_brief_missing_data_is_human_readable_arabic(client, db):
    company = _seed_company(db, "workspace_brief_missing_copy")
    company_id = company.company_id
    lead = _seed_paused_lead(db, company_id)
    db.add(
        Message(
            company_id=company_id,
            user_id=lead.whatsapp_jid,
            sender="user",
            direction="incoming",
            message="السعر كام؟",
            internal_message_id="msg-brief-price-copy",
            delivery_status="received",
        )
    )
    db.commit()

    profile = client.get(f"/api/v1/crm/customers/{lead.id}", cookies={"access_token": _token(company_id)})
    brief = profile.json()["customer"]["customer_brief"]
    rendered = json.dumps(brief, ensure_ascii=False)

    assert profile.status_code == 200
    assert brief["what_customer_wants"] == "يسأل عن السعر بدون تفاصيل كافية"
    assert "المنتج" in "، ".join(brief["missing_data"])
    assert "الكمية" in brief["missing_data"]
    assert "price_question" not in rendered
    assert "lead_evidence" not in rendered


def test_suggested_replies_are_not_returned_as_sent_messages(client, db):
    company = _seed_company(db, "workspace_suggestion_not_message")
    company_id = company.company_id
    lead = _seed_paused_lead(db, company_id)
    lead.is_paused = False
    db.commit()
    db.add(
        Message(
            company_id=company_id,
            user_id=lead.whatsapp_jid,
            sender="user",
            direction="incoming",
            message="Test message",
            internal_message_id="msg-source-only",
            delivery_status="received",
        )
    )
    db.add(
        WorkspaceSuggestedReply(
            company_id=company_id,
            lead_id=lead.id,
            source_message_internal_id="msg-source-only",
            suggested_reply="رد مقترح فقط، ليس رسالة مرسلة.",
            why_this_reply="اختبار",
            evidence_summary="اختبار",
            missing_data="[]",
            status="suggested",
        )
    )
    db.commit()

    profile = client.get(f"/api/v1/crm/customers/{lead.id}", cookies={"access_token": _token(company_id)})

    assert profile.status_code == 200
    timeline_messages = [item for item in profile.json()["customer"]["timeline"] if item["type"] == "message"]
    assert len(timeline_messages) == 1
    assert timeline_messages[0]["message"] == "Test message"
    assert profile.json()["customer"]["suggested_replies"][0]["suggested_reply"] == "رد مقترح فقط، ليس رسالة مرسلة."
