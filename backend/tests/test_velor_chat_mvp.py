import json
import uuid

from jose import jwt

from database import Company, CompanyKnowledge, Lead, LeadEvidence, Message, WorkspaceSuggestedReply, hash_api_key


def _token(company_id, role="tenant"):
    return jwt.encode(
        {"company_id": company_id, "role": role, "token_type": "access"},
        "super-secret-test-key-32-chars-long",
        algorithm="HS256",
    )


def _seed_company(db, company_id=None, products_data='[{"name":"Demo Product","price":500,"currency":"EGP"}]'):
    company_id = company_id or f"velor_{uuid.uuid4().hex[:8]}"
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
            knowledge_base="Demo Product has free-text data that must not be used for prices.",
        )
    )
    db.commit()
    return company


def _seed_lead(db, company_id, name="Ahmed", phone=None, is_test=False):
    phone = phone or f"100{uuid.uuid4().hex[:7]}"
    lead = Lead(
        company_id=company_id,
        name=name,
        phone=phone,
        whatsapp_number=phone,
        whatsapp_jid=f"20{phone}@s.whatsapp.net",
        interest="Demo Product",
        is_paused=True,
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


def _ask_company(client, company_id, message):
    return client.post("/api/v1/copilot/chat", json={"message": message}, cookies={"access_token": _token(company_id)})


def _ask_lead(client, company_id, lead_id, message):
    return client.post(f"/api/v1/copilot/chat/lead/{lead_id}", json={"message": message}, cookies={"access_token": _token(company_id)})


def test_ask_velor_company_endpoint_requires_auth(client):
    response = client.post("/api/v1/copilot/chat", json={"message": "who is closest to buying?"})

    assert response.status_code == 401


def test_ask_velor_lead_endpoint_blocks_cross_company_access(client, db):
    company_a = _seed_company(db, "velor_cross_a")
    company_b = _seed_company(db, "velor_cross_b")
    lead_b = _seed_lead(db, company_b.company_id, name="Private Lead")

    response = _ask_lead(client, company_a.company_id, lead_b.id, "best reply for this customer?")

    assert response.status_code == 404


def test_ask_velor_excludes_test_leads_from_company_and_lead_scopes(client, db):
    company = _seed_company(db, "velor_test_lead_exclusion")
    lead = _seed_lead(db, company.company_id, name="Synthetic customer", is_test=True)
    message = _seed_message(db, company.company_id, lead, "I want to start today")
    _seed_evidence(db, company.company_id, lead, message, "start_intent")
    lead_id = lead.id

    company_response = _ask_company(client, company.company_id, "who is closest to buying?")
    company_data = company_response.json()
    lead_response = _ask_lead(client, company.company_id, lead_id, "summarize this customer")

    assert company_response.status_code == 200
    assert company_data["evidence"] == []
    assert lead_id not in company_data["source_entities"]["lead_ids"]
    assert "Synthetic customer" not in json.dumps(company_data)
    assert lead_response.status_code == 404


def test_closest_lead_to_purchase_uses_evidence_and_returns_evidence(client, db):
    company = _seed_company(db, "velor_closest")
    lead = _seed_lead(db, company.company_id, name="Ahmed")
    message = _seed_message(db, company.company_id, lead, "What is the price for Demo Product? I want to start today.")
    _seed_evidence(db, company.company_id, lead, message, "price_question")
    _seed_evidence(db, company.company_id, lead, message, "start_intent")
    _seed_evidence(db, company.company_id, lead, message, "product_mention", normalized_value="Demo Product")

    response = _ask_company(client, company.company_id, "who is closest to buying?")
    data = response.json()

    assert response.status_code == 200
    assert "Ahmed" in data["answer"]
    assert data["evidence"]
    assert {row["type"] for row in data["evidence"]} >= {"price_question", "start_intent"}
    assert data["source_entities"]["lead_ids"] == [lead.id]


def test_common_objection_uses_objection_evidence_and_does_not_invent(client, db):
    company = _seed_company(db, "velor_objection")
    lead = _seed_lead(db, company.company_id)
    message = _seed_message(db, company.company_id, lead, "This is expensive. Any discount?")
    _seed_evidence(db, company.company_id, lead, message, "objection_price")

    response = _ask_company(client, company.company_id, "most common objection?")
    data = response.json()

    assert response.status_code == 200
    assert data["evidence"][0]["type"] == "objection_price"
    assert "خسارة" in data["answer"] or "closed" not in data["answer"].lower()
    assert data["missing_data"] == []


def test_most_asked_product_uses_product_mention_and_does_not_say_most_sold(client, db):
    company = _seed_company(db, "velor_product")
    lead = _seed_lead(db, company.company_id)
    message = _seed_message(db, company.company_id, lead, "Is Demo Product available?")
    _seed_evidence(db, company.company_id, lead, message, "product_mention", normalized_value="Demo Product")

    response = _ask_company(client, company.company_id, "what product are people asking about?")
    data = response.json()

    assert response.status_code == 200
    assert data["source_entities"]["product_names"] == ["Demo Product"]
    assert "most sold" not in data["answer"].lower()
    assert "الأكثر مبيعا" not in data["answer"]


def test_best_reply_for_lead_returns_suggested_reply_without_sending_whatsapp(client, db):
    company = _seed_company(db, "velor_best_reply")
    lead = _seed_lead(db, company.company_id)
    message = _seed_message(db, company.company_id, lead, "What is the price for Demo Product?")
    _seed_evidence(db, company.company_id, lead, message, "price_question")
    suggestion = WorkspaceSuggestedReply(
        company_id=company.company_id,
        lead_id=lead.id,
        source_message_id=message.id,
        source_message_internal_id=message.internal_message_id,
        suggested_reply="The listed price is 500 EGP. What quantity do you need?",
        why_this_reply="Known price but missing quantity.",
        evidence_summary="Customer asked about price.",
        missing_data=json.dumps(["quantity"]),
        confidence=0.9,
        status="suggested",
    )
    db.add(suggestion)
    db.commit()

    response = _ask_lead(client, company.company_id, lead.id, "best reply for this customer?")
    data = response.json()

    assert response.status_code == 200
    assert data["suggested_reply"] == "The listed price is 500 EGP. What quantity do you need?"
    assert "الكمية" in data["missing_data"]
    assert db.query(Message).filter(Message.company_id == company.company_id, Message.direction == "outgoing").count() == 0


def test_lead_scope_greeting_only_messages_return_useful_summary(client, db):
    company = _seed_company(db, "velor_greeting_summary")
    lead = _seed_lead(db, company.company_id)
    _seed_message(db, company.company_id, lead, "السلام عليكم")

    response = _ask_lead(client, company.company_id, lead.id, "لخص حالة هذا العميل")
    data = response.json()

    assert response.status_code == 200
    assert "الخلاصة" in data["answer"]
    assert "تحية فقط" in data["answer"]
    assert "لا توجد أدلة" not in data["answer"]
    assert "lead_evidence" not in json.dumps(data, ensure_ascii=False)
    assert "نوع الخدمة" in data["missing_data"]


def test_lead_scope_service_inquiry_maps_to_service_exploration(client, db):
    company = _seed_company(db, "velor_service_inquiry")
    lead = _seed_lead(db, company.company_id)
    _seed_message(db, company.company_id, lead, "هاي، أنا بسأل على خدماتكم؟")

    response = _ask_lead(client, company.company_id, lead.id, "ما اهتمامه الرئيسي؟")
    data = response.json()

    assert response.status_code == 200
    assert "يستكشف الخدمات" in data["answer"]
    assert "نوع الخدمة" in data["missing_data"]
    assert "lead_evidence" not in json.dumps(data, ensure_ascii=False)


def test_lead_scope_what_should_i_say_returns_safe_reply_without_sending(client, db):
    company = _seed_company(db, "velor_what_to_say")
    lead = _seed_lead(db, company.company_id)
    _seed_message(db, company.company_id, lead, "بتقدموا إيه من خدمات؟")

    response = _ask_lead(client, company.company_id, lead.id, "ماذا أقول له؟")
    data = response.json()

    assert response.status_code == 200
    assert "اكتب له" in data["answer"]
    assert data["suggested_reply"]
    assert "خدماتنا" in data["suggested_reply"] or "مشكلة" in data["suggested_reply"]
    assert "لم يتم إرساله تلقائيًا" in data["answer"]
    assert db.query(Message).filter(Message.company_id == company.company_id, Message.direction == "outgoing").count() == 0


def test_lead_scope_answer_does_not_expose_internal_keys_when_evidence_missing(client, db):
    company = _seed_company(db, "velor_no_internal_keys")
    lead = _seed_lead(db, company.company_id)
    _seed_message(db, company.company_id, lead, "بسأل عن خدماتكم")

    response = _ask_lead(client, company.company_id, lead.id, "لخص حالة العميل")
    rendered = json.dumps(response.json(), ensure_ascii=False)

    assert response.status_code == 200
    assert "lead_evidence" not in rendered
    assert "price_question" not in rendered
    assert "product_mention" not in rendered
    assert "buying_signal" not in rendered


def test_lead_scope_reads_messages_saved_under_customer_provided_phone(client, db):
    company = _seed_company(db, "velor_customer_phone_context")
    lead = _seed_lead(db, company.company_id)
    lead.customer_provided_phone = "201550001111"
    db.add(
        Message(
            company_id=company.company_id,
            user_id=lead.customer_provided_phone,
            sender="user",
            direction="incoming",
            message="بسأل عن خدماتكم",
            internal_message_id=f"msg-{uuid.uuid4().hex}",
            delivery_status="received",
        )
    )
    db.commit()

    response = _ask_lead(client, company.company_id, lead.id, "ما اهتمامه الرئيسي؟")
    data = response.json()

    assert response.status_code == 200
    assert "يستكشف الخدمات" in data["answer"]
    assert "لا أرى رسائل" not in data["answer"]


def test_lead_scope_price_question_does_not_invent_price_or_product(client, db):
    company = _seed_company(db, "velor_lead_price_no_fake")
    lead = _seed_lead(db, company.company_id)
    _seed_message(db, company.company_id, lead, "السعر كام؟")

    response = _ask_lead(client, company.company_id, lead.id, "لخص حالة العميل")
    data = response.json()

    assert response.status_code == 200
    assert "يسأل عن السعر" in data["answer"]
    assert "المنتج أو الخدمة" in data["missing_data"]
    assert "الكمية" in data["missing_data"]
    assert "500" not in data["answer"]
    assert "deal value" not in data["answer"].lower()


def test_unknown_price_remains_missing_data_and_is_not_invented(client, db):
    company = _seed_company(db, "velor_unknown_price", products_data='[{"name":"Demo Product","price":"call us"}]')

    response = _ask_company(client, company.company_id, "what is the price for Demo Product?")
    data = response.json()

    assert response.status_code == 200
    assert "السعر الموثق" in data["missing_data"]
    assert "500" not in data["answer"]
    assert "غير معروف" in data["answer"]


def test_known_product_price_can_be_mentioned_only_from_product_context(client, db):
    company = _seed_company(db, "velor_known_price", products_data='[{"name":"Demo Product","price":750,"currency":"EGP"}]')

    response = _ask_company(client, company.company_id, "what is the price for Demo Product?")
    data = response.json()

    assert response.status_code == 200
    assert "750" in data["answer"]
    assert "EGP" in data["answer"]
    assert data["source_entities"]["product_names"] == ["Demo Product"]


def test_ask_velor_answers_owner_questions_from_latest_grounded_conversation(client, db):
    products = json.dumps(
        [
            {"name": "Arvena Ergo One", "aliases": ["Ergo One"], "category": "Office Chairs", "price": 6900, "currency": "EGP"},
            {"name": "Arvena Ergo Pro", "aliases": ["Ergo Pro"], "category": "Office Chairs", "price": 10900, "currency": "EGP"},
        ]
    )
    company = _seed_company(db, "velor_grounded_owner_questions", products_data=products)
    lead = _seed_lead(db, company.company_id)
    comparison = _seed_message(db, company.company_id, lead, "Compare Ergo One and Ergo Pro")
    _seed_evidence(db, company.company_id, lead, comparison, "product_mention", normalized_value="Arvena Ergo One", metadata={"matched_product_name": "Arvena Ergo One"})
    _seed_evidence(db, company.company_id, lead, comparison, "product_mention", normalized_value="Arvena Ergo Pro", metadata={"matched_product_name": "Arvena Ergo Pro"})
    _seed_message(db, company.company_id, lead, "Arvena Ergo One: 6900 EGP. Arvena Ergo Pro: 10900 EGP.", sender="assistant")
    price_reference = _seed_message(db, company.company_id, lead, "\u0639\u0627\u064a\u0632 \u0627\u0644\u0644\u064a \u0628\u06406900 \u062f\u0647")
    _seed_evidence(db, company.company_id, lead, price_reference, "product_mention", normalized_value="Arvena Ergo One", metadata={"matched_product_name": "Arvena Ergo One"})
    objection = _seed_message(db, company.company_id, lead, "10900 \u063a\u0627\u0644\u064a \u062c\u062f\u064b\u0627")
    _seed_evidence(db, company.company_id, lead, objection, "objection_price")

    interest = _ask_lead(client, company.company_id, lead.id, "\u0645\u0627 \u0627\u0647\u062a\u0645\u0627\u0645\u0647 \u0627\u0644\u0631\u0626\u064a\u0633\u064a\u061f").json()["answer"]
    latest = _ask_lead(client, company.company_id, lead.id, "\u0645\u0627 \u0622\u062e\u0631 \u0637\u0644\u0628 \u0644\u0644\u0639\u0645\u064a\u0644\u061f").json()["answer"]
    products_seen = _ask_lead(client, company.company_id, lead.id, "\u0645\u0627 \u0627\u0644\u0645\u0646\u062a\u062c\u0627\u062a \u0627\u0644\u062a\u064a \u0634\u0627\u0647\u062f\u0647\u0627\u061f").json()["answer"]
    colloquial_products_seen = _ask_lead(client, company.company_id, lead.id, "\u0634\u0627\u0641 \u0623\u0648 \u0627\u062a\u0643\u0644\u0645 \u0639\u0646 \u0623\u0646\u0647\u064a \u0645\u0646\u062a\u062c\u0627\u062a\u061f").json()["answer"]
    notes = _ask_lead(client, company.company_id, lead.id, "\u0645\u0627 \u0627\u0644\u0645\u0644\u0627\u062d\u0638\u0627\u062a \u0627\u0644\u0645\u0647\u0645\u0629\u061f").json()["answer"]
    criteria = _ask_lead(client, company.company_id, lead.id, "\u0645\u0627 \u0627\u0644\u0645\u0648\u0627\u0635\u0641\u0627\u062a \u0627\u0644\u0645\u0647\u0645\u0629\u061f").json()["answer"]

    assert "Arvena Ergo Pro" in interest
    assert "10900" in latest
    assert "Arvena Ergo One" in products_seen and "Arvena Ergo Pro" in products_seen
    assert "Arvena Ergo One" in colloquial_products_seen and "Arvena Ergo Pro" in colloquial_products_seen
    assert "\u0627\u0639\u062a\u0631\u0627\u0636" in notes
    assert "\u0645\u064a\u0632\u0627\u0646\u064a\u0629" in criteria


def test_insufficient_data_returns_safe_insufficient_data_answer(client, db):
    company = _seed_company(db, "velor_insufficient")

    response = _ask_company(client, company.company_id, "who is closest to buying?")
    data = response.json()

    assert response.status_code == 200
    assert data["evidence"] == []
    assert data["missing_data"]
    assert "غير كافية" in data["answer"]


def test_llm_failure_path_is_safe_because_mvp_uses_deterministic_fallback(client, db, monkeypatch):
    company = _seed_company(db, "velor_llm_failure")
    monkeypatch.setenv("GROQ_API_KEY", "broken")

    response = _ask_company(client, company.company_id, "summarize what matters")
    data = response.json()

    assert response.status_code == 200
    assert data["llm_used"] is False
    assert data["grounding"] == "deterministic_retrieval"
    assert data["answer"]


def test_existing_chat_behavior_remains_unchanged(client, db):
    company = _seed_company(db, "velor_existing_chat")
    company.bot_auto_reply_enabled = False
    db.commit()

    response = client.post(
        "/chat",
        json={"message": "What is the price for Demo Product?", "user_id": "201001112223@s.whatsapp.net", "external_message_id": "wamid.velor-chat-unchanged"},
        headers={"X-Internal-Secret": "secret", "X-Company-ID": company.company_id},
    )

    assert response.status_code == 200
    assert response.json()["auto_reply_skipped"] is True
