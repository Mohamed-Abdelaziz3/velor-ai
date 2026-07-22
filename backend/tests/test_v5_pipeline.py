from jose import jwt

from database import Company, CompanyKnowledge, Lead, LeadIntelligenceSnapshot, Message, get_latest_leads, hash_api_key


class _FailingCompletions:
    async def create(self, *args, **kwargs):
        raise RuntimeError("simulated provider outage")


class _FailingChat:
    completions = _FailingCompletions()


class _FailingGroq:
    chat = _FailingChat()


def _seed_pipeline_company(db, company_id="pipeline_company"):
    company = Company(
        company_id=company_id,
        company_name="Pipeline Demo",
        email=f"{company_id}@example.com",
        password="hashed",
        api_key_hash=hash_api_key(f"{company_id}-api-key"),
        plan="PRO",
    )
    lead = Lead(
        company_id=company_id,
        name="Test Lead",
        phone="01012345678",
        whatsapp_number="01012345678",
        interest="Demo Product",
        intent_score=50,
        ai_summary="New lead.",
        stage="Information Gathering",
        status="new",
    )
    knowledge = CompanyKnowledge(
        company_id=company_id,
        system_prompt="You are a helpful sales assistant.",
        products_data='[{"name":"Demo Product","price":"1000 EGP"}]',
        knowledge_base="Demo Product is suitable for small businesses.",
        industry="Retail",
        tone="Friendly",
    )
    db.add(company)
    db.add(lead)
    db.add(knowledge)
    db.commit()
    db.refresh(lead)
    return company, lead


def _token(company_id):
    return jwt.encode(
        {"company_id": company_id, "role": "tenant", "token_type": "access"},
        "super-secret-test-key-32-chars-long",
        algorithm="HS256",
    )


def test_webhook_brain_responds(client, db, monkeypatch):
    import brain
    import engine.analyzer as analyzer
    import engine.memory as memory

    company, _lead = _seed_pipeline_company(db, "pipeline_chat")
    monkeypatch.setattr(brain, "groq_client", _FailingGroq())
    monkeypatch.setattr(analyzer, "should_trigger_analysis", lambda *args, **kwargs: False)
    monkeypatch.setattr(memory, "rebuild_lead_memory_task", lambda *args, **kwargs: None)

    response = client.post(
        "/chat",
        json={"message": "I am interested in your premium product and ready to buy.", "user_id": "01012345678"},
        headers={"X-Internal-Secret": "secret", "X-Company-ID": company.company_id},
    )

    assert response.status_code == 200
    assert response.json()["reply"]


def test_meta_webhook_is_disabled_by_default(client):
    verify = client.get(
        "/api/whatsapp/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "velor_secret_fallback",
            "hub.challenge": "challenge-value",
        },
    )
    receive = client.post("/api/whatsapp/webhook", json={"entry": []})

    assert verify.status_code == 404
    assert receive.status_code == 404


def test_crm_deep_fetch(client, db):
    company, lead = _seed_pipeline_company(db, "pipeline_crm")

    response = client.get(f"/api/v1/crm/customers/{lead.id}", cookies={"access_token": _token(company.company_id)})

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["customer"]["id"] == lead.id
    assert "activity_logs" in data["customer"]
    assert "notes" in data["customer"]
    assert "customer_brief" in data["customer"]


def test_crm_timeline_exposes_internal_message_id_for_status_sync(client, db):
    company, lead = _seed_pipeline_company(db, "pipeline_crm_status")
    internal_id = "msg-internal-status-1"
    db.add(
        Message(
            company_id=company.company_id,
            user_id=lead.whatsapp_number,
            sender="owner",
            direction="outgoing",
            message="Following up now.",
            internal_message_id=internal_id,
            delivery_status="sent",
        )
    )
    db.commit()

    response = client.get(f"/api/v1/crm/customers/{lead.id}", cookies={"access_token": _token(company.company_id)})

    assert response.status_code == 200
    timeline_messages = [item for item in response.json()["customer"]["timeline"] if item["type"] == "message"]
    assert timeline_messages == [
        {
            "id": f"msg_{internal_id}",
            "internal_message_id": internal_id,
            "type": "message",
            "sender": "owner",
            "direction": "outgoing",
            "source": "whatsapp",
            "is_ai": False,
            "message": "Following up now.",
            "delivery_status": "sent",
            "status": "sent",
            "timestamp": timeline_messages[0]["timestamp"],
        }
    ]


def test_crm_timeline_matches_whatsapp_lid_message_identity(client, db):
    company, lead = _seed_pipeline_company(db, "pipeline_crm_lid")
    lead.phone = "146879794905304"
    lead.whatsapp_number = "146879794905304"
    lead.whatsapp_jid = "146879794905304@lid"
    internal_id = "msg-live-lid-1"
    db.add(
        Message(
            company_id=company.company_id,
            user_id="146879794905304@lid",
            sender="user",
            direction="incoming",
            message="السلام عليكم",
            internal_message_id=internal_id,
            delivery_status="received",
        )
    )
    db.commit()

    response = client.get(f"/api/v1/crm/customers/{lead.id}", cookies={"access_token": _token(company.company_id)})

    assert response.status_code == 200
    customer = response.json()["customer"]
    timeline_messages = [item for item in customer["timeline"] if item["type"] == "message"]
    assert customer["whatsapp_jid"] == "146879794905304@lid"
    assert customer["display_phone"] == "146879794905304"
    assert timeline_messages == [
        {
            "id": f"msg_{internal_id}",
            "internal_message_id": internal_id,
            "type": "message",
            "sender": "user",
            "direction": "incoming",
            "source": "whatsapp",
            "is_ai": False,
            "message": "السلام عليكم",
            "delivery_status": "received",
            "status": "received",
            "timestamp": timeline_messages[0]["timestamp"],
        }
    ]


def test_intelligence_insights(client, db):
    company, _lead = _seed_pipeline_company(db, "pipeline_intel")
    db.add(
        Lead(
            company_id=company.company_id,
            name="At Risk Customer",
            phone="01099998888",
            whatsapp_number="01099998888",
            interest="Demo Product",
            status="at-risk",
            stage="Objection Handling",
            ai_summary="Customer thinks the price is expensive.",
        )
    )
    db.commit()
    response = client.get("/api/v1/intelligence/insights", cookies={"access_token": _token(company.company_id)})

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "top_objections" in data["insights"]
    assert "trending_products" in data["insights"]
    assert "sentiment_trend" in data["insights"]
    assert "strategic_recommendation" in data["insights"]


def test_latest_leads_serializes_intelligence_snapshot(db):
    company, lead = _seed_pipeline_company(db, "pipeline_latest_snapshot")
    lead.intent_score = 72
    db.add(
        LeadIntelligenceSnapshot(
            lead_id=lead.id,
            priority_score=80,
            lost_risk_score=10,
            next_best_action="Follow up",
            action_reason="Customer is interested",
            why_summary="Customer asked about pricing.",
        )
    )
    db.commit()

    latest = get_latest_leads(db, company.company_id, limit=5)

    assert latest[0]["intelligence_snapshot"]["intent_score"] == 72
    assert latest[0]["intelligence_snapshot"]["priority_score"] == 80
