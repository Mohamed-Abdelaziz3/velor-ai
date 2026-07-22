import json
import uuid
from datetime import datetime, timezone

from jose import jwt

from database import Company, CompanyKnowledge, Lead, LeadEvidence, Message, WorkspaceSuggestedReply, hash_api_key


def _token(company_id, role="tenant"):
    return jwt.encode(
        {"company_id": company_id, "role": role, "token_type": "access"},
        "super-secret-test-key-32-chars-long",
        algorithm="HS256",
    )


def _seed_company(db, company_id=None, products_data='[{"name":"Demo Product","price":500,"currency":"EGP"}]'):
    company_id = company_id or f"priority_{uuid.uuid4().hex[:8]}"
    company = Company(
        company_id=company_id,
        company_name=f"{company_id} Company",
        email=f"{company_id}@example.com",
        password="hashed",
        api_key_hash=hash_api_key(f"{company_id}-api-key"),
        plan="PRO",
    )
    db.add(company)
    db.add(
        CompanyKnowledge(
            company_id=company_id,
            system_prompt="You are a grounded sales assistant.",
            products_data=products_data,
            knowledge_base="Demo Product knowledge must not be used for fabricated deal values.",
        )
    )
    db.commit()
    return company


def _seed_lead(db, company_id, name="Ahmed", phone=None, stage="New", opportunity_value=None, is_paused=False, is_test=False):
    phone = phone or f"100{uuid.uuid4().hex[:7]}"
    lead = Lead(
        company_id=company_id,
        name=name,
        phone=phone,
        whatsapp_number=phone,
        whatsapp_jid=f"20{phone}@s.whatsapp.net",
        interest="Demo Product",
        stage=stage,
        opportunity_value=opportunity_value,
        is_paused=is_paused,
        is_test=is_test,
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead


def _seed_message(db, company_id, lead, text, sender="user", internal_id=None):
    message = Message(
        company_id=company_id,
        user_id=lead.whatsapp_number,
        sender=sender,
        direction="incoming" if sender == "user" else "outgoing",
        message=text,
        internal_message_id=internal_id or f"msg-{uuid.uuid4().hex}",
        delivery_status="delivered",
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    return message


def _seed_evidence(db, company_id, lead, message, evidence_type, source_text=None, normalized_value=None, metadata=None, confidence=0.9):
    evidence = LeadEvidence(
        company_id=company_id,
        lead_id=lead.id,
        message_id=message.id,
        message_internal_id=message.internal_message_id,
        evidence_type=evidence_type,
        source="message",
        source_text=source_text or message.message,
        normalized_value=normalized_value,
        metadata_json=json.dumps(metadata or {}),
        confidence=confidence,
        evidence_hash=f"{evidence_type}-{uuid.uuid4().hex}",
    )
    db.add(evidence)
    db.commit()
    db.refresh(evidence)
    return evidence


def _get_priorities(client, company_id, limit=5):
    return client.get(f"/api/engine/priorities?limit={limit}", cookies={"access_token": _token(company_id)})


def _first_action(response):
    data = response.json()
    assert response.status_code == 200
    assert data["success"] is True
    assert data["actions"]
    return data["actions"][0]


def test_priority_actions_endpoint_requires_auth(client):
    response = client.get("/api/engine/priorities")

    assert response.status_code == 401


def test_priority_actions_endpoint_accepts_dashboard_limit_10(client, db):
    company = _seed_company(db, "priority_limit_10")

    response = _get_priorities(client, company.company_id, limit=10)

    assert response.status_code == 200


def test_cross_company_evidence_and_leads_do_not_leak(client, db):
    company_a = _seed_company(db, "priority_cross_a")
    company_b = _seed_company(db, "priority_cross_b")
    lead_b = _seed_lead(db, company_b.company_id, name="Private Lead")
    message_b = _seed_message(db, company_b.company_id, lead_b, "I want to start today")
    _seed_evidence(db, company_b.company_id, lead_b, message_b, "start_intent")

    response = _get_priorities(client, company_a.company_id)
    data = response.json()

    assert response.status_code == 200
    assert data["actions"] == []
    assert "Private Lead" not in json.dumps(data)


def test_priority_actions_exclude_test_leads(client, db):
    company = _seed_company(db, "priority_test_lead_exclusion")
    lead = _seed_lead(db, company.company_id, name="Synthetic customer", is_test=True)
    message = _seed_message(db, company.company_id, lead, "I want to start today")
    _seed_evidence(db, company.company_id, lead, message, "start_intent")

    response = _get_priorities(client, company.company_id)
    data = response.json()

    assert response.status_code == 200
    assert data["actions"] == []
    assert "Synthetic customer" not in json.dumps(data)


def test_hot_lead_action_generated_from_buying_signal_start_intent(client, db):
    company = _seed_company(db, "priority_hot")
    lead = _seed_lead(db, company.company_id, name="Ahmed")
    message = _seed_message(db, company.company_id, lead, "I want to start today")
    _seed_evidence(db, company.company_id, lead, message, "buying_signal")
    _seed_evidence(db, company.company_id, lead, message, "start_intent")

    action = _first_action(_get_priorities(client, company.company_id))

    assert action["type"] == "follow_up_hot_lead"
    assert action["lead_id"] == lead.id
    assert {row["type"] for row in action["evidence"]} >= {"buying_signal", "start_intent"}
    assert action["suggested_action"]


def test_price_question_action_generated_from_price_question_evidence(client, db):
    company = _seed_company(db, "priority_price")
    lead = _seed_lead(db, company.company_id)
    message = _seed_message(db, company.company_id, lead, "What is the price for Demo Product?")
    _seed_evidence(db, company.company_id, lead, message, "price_question")
    _seed_evidence(
        db,
        company.company_id,
        lead,
        message,
        "product_mention",
        normalized_value="Demo Product",
        metadata={"matched_product_name": "Demo Product", "known_price": 750, "currency": "EGP"},
    )

    action = _first_action(_get_priorities(client, company.company_id))

    assert action["type"] == "answer_price_question"
    assert "750" in action["suggested_reply"]
    assert "EGP" in action["suggested_reply"]
    assert "quantity" in action["missing_data"]


def test_price_objection_action_generated_from_objection_evidence(client, db):
    company = _seed_company(db, "priority_objection")
    lead = _seed_lead(db, company.company_id)
    message = _seed_message(db, company.company_id, lead, "This is expensive")
    _seed_evidence(db, company.company_id, lead, message, "objection_price")

    action = _first_action(_get_priorities(client, company.company_id))

    assert action["type"] == "handle_price_objection"
    assert "quantity" in action["missing_data"]


def test_urgent_waiting_action_generated_from_urgency_evidence(client, db):
    company = _seed_company(db, "priority_urgent")
    lead = _seed_lead(db, company.company_id, name="Mona")
    message = _seed_message(db, company.company_id, lead, "Please reply now")
    _seed_evidence(db, company.company_id, lead, message, "urgency")

    action = _first_action(_get_priorities(client, company.company_id))

    assert action["type"] == "urgent_customer_waiting"
    assert action["data"]["waiting_time"]


def test_action_includes_evidence_source_message_ids(client, db):
    company = _seed_company(db, "priority_source")
    lead = _seed_lead(db, company.company_id)
    message = _seed_message(db, company.company_id, lead, "I am ready", internal_id="msg-priority-source")
    _seed_evidence(db, company.company_id, lead, message, "buying_signal")

    action = _first_action(_get_priorities(client, company.company_id))

    assert action["evidence"][0]["source_message_internal_id"] == "msg-priority-source"


def test_unknown_price_and_deal_value_not_invented(client, db):
    company = _seed_company(db, "priority_no_fake_price")
    lead = _seed_lead(db, company.company_id, opportunity_value=None)
    message = _seed_message(db, company.company_id, lead, "What is the price?")
    _seed_evidence(db, company.company_id, lead, message, "price_question")

    action = _first_action(_get_priorities(client, company.company_id))
    payload = json.dumps(action)

    assert action["type"] == "clarify_missing_data"
    assert "1000" not in payload
    assert "15000" not in payload
    assert "deal_value" not in action["data"]
    assert "value" not in action["data"]
    assert {"product", "price", "quantity"}.issubset(set(action["missing_data"]))


def test_known_product_price_may_appear_only_from_product_context(client, db):
    company = _seed_company(db, "priority_known_price")
    lead = _seed_lead(db, company.company_id)
    message = _seed_message(db, company.company_id, lead, "What is the price for Demo Product?")
    _seed_evidence(db, company.company_id, lead, message, "price_question")
    _seed_evidence(
        db,
        company.company_id,
        lead,
        message,
        "product_mention",
        normalized_value="Demo Product",
        metadata={"matched_product_name": "Demo Product", "known_price": 750, "currency": "EGP"},
    )

    action = _first_action(_get_priorities(client, company.company_id))

    assert "750" in action["suggested_reply"]
    assert "EGP" in action["suggested_reply"]


def test_existing_unsafe_default_opportunity_value_not_used(client, db):
    company = _seed_company(db, "priority_no_default_value")
    lead = _seed_lead(db, company.company_id, opportunity_value=None)
    message = _seed_message(db, company.company_id, lead, "I want to buy today")
    _seed_evidence(db, company.company_id, lead, message, "buying_signal")

    action = _first_action(_get_priorities(client, company.company_id))
    payload = json.dumps(action)

    assert "expected_revenue" not in payload
    assert "deal_value" not in payload
    assert "$1,000" not in payload
    assert "1000" not in payload


def test_suggested_reply_included_without_auto_sending(client, db):
    company = _seed_company(db, "priority_suggestion")
    lead = _seed_lead(db, company.company_id, is_paused=True)
    message = _seed_message(db, company.company_id, lead, "What is the price for Demo Product?")
    _seed_evidence(db, company.company_id, lead, message, "price_question")
    suggestion = WorkspaceSuggestedReply(
        company_id=company.company_id,
        lead_id=lead.id,
        source_message_id=message.id,
        source_message_internal_id=message.internal_message_id,
        suggested_reply="The listed price is 500 EGP. What quantity do you need?",
        why_this_reply="Known price, missing quantity.",
        evidence_summary="Customer asked about price.",
        missing_data=json.dumps(["quantity"]),
        confidence=0.9,
        status="suggested",
    )
    db.add(suggestion)
    db.commit()

    action = _first_action(_get_priorities(client, company.company_id))

    assert action["suggested_reply"] != "The listed price is 500 EGP. What quantity do you need?"
    assert "500" not in action["suggested_reply"]
    assert action["suggested_reply"]
    assert db.query(Message).filter(Message.company_id == company.company_id, Message.direction == "outgoing").count() == 0


def test_unsafe_stored_suggested_reply_fake_price_is_replaced(client, db):
    company = _seed_company(db, "priority_unsafe_suggestion_price", products_data='[{"name":"Demo Product","price":"call us"}]')
    lead = _seed_lead(db, company.company_id)
    message = _seed_message(db, company.company_id, lead, "What is the price?")
    _seed_evidence(db, company.company_id, lead, message, "price_question")
    db.add(
        WorkspaceSuggestedReply(
            company_id=company.company_id,
            lead_id=lead.id,
            source_message_id=message.id,
            source_message_internal_id=message.internal_message_id,
            suggested_reply="The price is 15000 EGP and the deal value is 45000.",
            why_this_reply="Unsafe generated value.",
            evidence_summary="Customer asked about price.",
            missing_data=json.dumps(["quantity"]),
            confidence=0.9,
            status="suggested",
        )
    )
    db.commit()

    action = _first_action(_get_priorities(client, company.company_id))
    payload = json.dumps(action)

    assert action["suggested_reply"]
    assert "15000" not in payload
    assert "45000" not in payload
    assert "deal value" not in action["suggested_reply"].lower()
    assert action["suggested_reply"]


def test_unsafe_stored_suggested_reply_fake_revenue_opportunity_is_replaced(client, db):
    company = _seed_company(db, "priority_unsafe_suggestion_revenue")
    lead = _seed_lead(db, company.company_id, is_paused=True)
    message = _seed_message(db, company.company_id, lead, "I want to buy today")
    _seed_evidence(db, company.company_id, lead, message, "buying_signal")
    db.add(
        WorkspaceSuggestedReply(
            company_id=company.company_id,
            lead_id=lead.id,
            source_message_id=message.id,
            source_message_internal_id=message.internal_message_id,
            suggested_reply="This opportunity value is 99000 and expected revenue is 88000.",
            why_this_reply="Unsafe generated value.",
            evidence_summary="Customer showed buying signal.",
            missing_data=json.dumps([]),
            confidence=0.9,
            status="suggested",
        )
    )
    db.commit()

    action = _first_action(_get_priorities(client, company.company_id))
    payload = json.dumps(action)

    assert "99000" not in payload
    assert "88000" not in payload
    assert "opportunity value" not in action["suggested_reply"].lower()
    assert "expected revenue" not in action["suggested_reply"].lower()


def test_unsafe_stored_suggestion_does_not_override_trusted_product_price(client, db):
    company = _seed_company(db, "priority_trusted_price_overrides_bad_suggestion")
    lead = _seed_lead(db, company.company_id)
    message = _seed_message(db, company.company_id, lead, "What is the price for Demo Product?")
    _seed_evidence(db, company.company_id, lead, message, "price_question")
    _seed_evidence(
        db,
        company.company_id,
        lead,
        message,
        "product_mention",
        normalized_value="Demo Product",
        metadata={"matched_product_name": "Demo Product", "known_price": 750, "currency": "EGP"},
    )
    db.add(
        WorkspaceSuggestedReply(
            company_id=company.company_id,
            lead_id=lead.id,
            source_message_id=message.id,
            source_message_internal_id=message.internal_message_id,
            suggested_reply="The price is 9999 EGP.",
            why_this_reply="Unsafe generated value.",
            evidence_summary="Customer asked about price.",
            missing_data=json.dumps(["quantity"]),
            confidence=0.9,
            status="suggested",
        )
    )
    db.commit()

    action = _first_action(_get_priorities(client, company.company_id))

    assert "750" in action["suggested_reply"]
    assert "EGP" in action["suggested_reply"]
    assert "9999" not in action["suggested_reply"]


def test_actions_sorted_by_deterministic_score(client, db):
    company = _seed_company(db, "priority_sort")
    hot_lead = _seed_lead(db, company.company_id, name="Hot Lead")
    warm_lead = _seed_lead(db, company.company_id, name="Warm Lead")
    hot_message = _seed_message(db, company.company_id, hot_lead, "Urgent, I want to start today")
    warm_message = _seed_message(db, company.company_id, warm_lead, "Maybe later")
    _seed_evidence(db, company.company_id, hot_lead, hot_message, "urgency")
    _seed_evidence(db, company.company_id, hot_lead, hot_message, "start_intent")
    _seed_evidence(db, company.company_id, warm_lead, warm_message, "hesitation")

    data = _get_priorities(client, company.company_id).json()

    assert len(data["actions"]) == 2
    assert data["actions"][0]["lead_id"] == hot_lead.id
    assert data["actions"][0]["score"] > data["actions"][1]["score"]


def test_same_score_same_timestamp_actions_sort_by_stable_tiebreakers(client, db):
    company = _seed_company(db, "priority_sort_tie")
    first_lead = _seed_lead(db, company.company_id, name="First Lead")
    second_lead = _seed_lead(db, company.company_id, name="Second Lead")
    first_message = _seed_message(db, company.company_id, first_lead, "I am ready")
    second_message = _seed_message(db, company.company_id, second_lead, "I am ready")
    fixed_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    first_evidence = _seed_evidence(db, company.company_id, first_lead, first_message, "buying_signal")
    second_evidence = _seed_evidence(db, company.company_id, second_lead, second_message, "buying_signal")
    first_evidence.created_at = fixed_time
    second_evidence.created_at = fixed_time
    db.commit()

    data = _get_priorities(client, company.company_id).json()

    assert [item["lead_id"] for item in data["actions"]] == sorted([first_lead.id, second_lead.id])


def test_empty_insufficient_data_returns_empty_actions(client, db):
    company = _seed_company(db, "priority_empty")

    response = _get_priorities(client, company.company_id)
    data = response.json()

    assert response.status_code == 200
    assert data["actions"] == []
    assert data["message"]


def test_copilot_actions_endpoint_uses_priority_actions_contract(client, db):
    company = _seed_company(db, "priority_copilot_route")
    lead = _seed_lead(db, company.company_id, name="Route Lead")
    message = _seed_message(db, company.company_id, lead, "I am ready to buy")
    _seed_evidence(db, company.company_id, lead, message, "buying_signal")
    db.add(
        WorkspaceSuggestedReply(
            company_id=company.company_id,
            lead_id=lead.id,
            source_message_id=message.id,
            source_message_internal_id=message.internal_message_id,
            suggested_reply="Expected revenue is 45000.",
            why_this_reply="Unsafe generated value.",
            evidence_summary="Customer showed buying signal.",
            missing_data=json.dumps([]),
            confidence=0.9,
            status="suggested",
        )
    )
    db.commit()

    response = client.get("/api/v1/copilot/actions", cookies={"access_token": _token(company.company_id)})
    data = response.json()
    payload = json.dumps(data)

    assert response.status_code == 200
    assert data[0]["lead_name"] == "Route Lead"
    assert data[0]["evidence"]
    assert data[0]["suggested_action"]
    assert "45000" not in payload
    assert "expected_revenue" not in payload


def test_existing_chat_behavior_remains_unchanged(client, db):
    company = _seed_company(db, "priority_existing_chat")
    company.bot_auto_reply_enabled = False
    db.commit()

    response = client.post(
        "/chat",
        json={"message": "What is the price for Demo Product?", "user_id": "201001112223@s.whatsapp.net", "external_message_id": "wamid.priority-unchanged"},
        headers={"X-Internal-Secret": "secret", "X-Company-ID": company.company_id},
    )

    assert response.status_code == 200
    assert response.json()["auto_reply_skipped"] is True
