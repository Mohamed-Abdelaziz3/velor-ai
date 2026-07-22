import asyncio
import json
import uuid

from jose import jwt

from database import (
    ActivityLog,
    Company,
    CompanyKnowledge,
    KnowledgeSource,
    Lead,
    LeadAnalytics,
    LeadIntelligenceSnapshot,
    LeadMemory,
    Message,
    SystemEvent,
    hash_api_key,
)


JWT_TEST_SECRET = "super-secret-test-key-32-chars-long"


def _token(company_id, *, sub_marker=None, role="tenant"):
    payload = {"company_id": company_id, "role": role, "token_type": "access"}
    if sub_marker is not None:
        payload["sub"] = sub_marker
    return jwt.encode(payload, JWT_TEST_SECRET, algorithm="HS256")


def _tenant(db, prefix):
    suffix = uuid.uuid4().hex[:8]
    company_id = f"{prefix}_{suffix}"
    raw_key = f"{company_id}-key"
    company = Company(
        company_id=company_id,
        company_name=company_id,
        email=f"{company_id}@example.com",
        password="hashed",
        api_key_hash=hash_api_key(raw_key),
        plan="PRO",
    )
    db.add(company)
    db.add(CompanyKnowledge(company_id=company_id, products_data="[]", knowledge_base=f"policy-{company_id}"))
    db.commit()
    return company_id, raw_key


def test_malformed_identity_and_cross_tenant_resolution_are_rejected(client, db):
    company_id, _ = _tenant(db, "phase5_identity")

    assert client.get("/stats").status_code == 401
    malformed = _token([company_id])
    assert client.get("/stats", cookies={"access_token": malformed}).status_code == 401
    mismatched_subject = _token(company_id, sub_marker="different-tenant")
    assert client.get("/stats", cookies={"access_token": mismatched_subject}).status_code == 401

    other_id, _ = _tenant(db, "phase5_other")
    cross_tenant = client.get(
        f"/api/conversations?company_id={other_id}",
        cookies={"access_token": _token(company_id)},
    )
    assert cross_tenant.status_code == 403


def test_catalog_policy_and_conversation_records_are_tenant_scoped(client, db):
    company_a_id, _ = _tenant(db, "phase5_catalog_a")
    company_b_id, _ = _tenant(db, "phase5_catalog_b")
    db.query(CompanyKnowledge).filter(CompanyKnowledge.company_id == company_a_id).one().products_data = json.dumps(
        [{"name": "A-only", "category": "chairs", "price": 10}]
    )
    db.query(CompanyKnowledge).filter(CompanyKnowledge.company_id == company_b_id).one().products_data = json.dumps(
        [{"name": "B-only", "category": "chairs", "price": 20}]
    )
    source_b = KnowledgeSource(
        company_id=company_b_id,
        source_name="B-policy.txt",
        source_type="txt",
        mime_type="text/plain",
        extracted_text="private B policy",
        extracted_char_count=15,
        chunk_count=1,
    )
    lead_b = Lead(company_id=company_b_id, name="B customer", phone="201000000002", channel_type="VELOR_WEB_CHAT")
    db.add_all([source_b, lead_b])
    db.commit()
    lead_b_id = lead_b.id

    token_a = {"access_token": _token(company_a_id)}
    catalog = client.get("/api/v1/catalog", cookies=token_a)
    assert catalog.status_code == 200
    assert [row["name"] for row in catalog.json()["records"]] == ["A-only"]
    policy = client.get("/api/v1/knowledge/sources", cookies=token_a)
    assert policy.status_code == 200
    assert policy.json()["sources"] == []
    assert client.get(f"/api/v1/crm/customers/{lead_b_id}", cookies=token_a).status_code == 404


def test_delivery_ack_cannot_cross_tenant_or_bypass_internal_tenant(client, db):
    company_a_id, _ = _tenant(db, "phase5_delivery_a")
    company_b_id, key_b = _tenant(db, "phase5_delivery_b")
    internal_id = f"phase5-{uuid.uuid4().hex}"
    message = Message(
        company_id=company_a_id,
        user_id="external-customer",
        sender="assistant",
        direction="outgoing",
        message="reply",
        internal_message_id=internal_id,
        delivery_status="pending",
    )
    db.add(message)
    db.add(
        SystemEvent(
            company_id=company_a_id,
            event_type="message.created",
            entity_id=internal_id,
            payload=json.dumps({"channel": "EXTERNAL_API"}),
        )
    )
    db.commit()

    cross = client.post(
        "/api/external/delivery/ack",
        json={"internal_message_id": internal_id, "status": "sent"},
        headers={"X-API-Key": key_b},
    )
    assert cross.status_code == 404
    assert db.query(Message).filter(Message.internal_message_id == internal_id).one().delivery_status == "pending"

    missing_company = client.post(
        "/api/whatsapp/webhook/ack",
        json={"internal_message_id": internal_id, "status": "sent"},
        headers={"X-Internal-Secret": "secret"},
    )
    assert missing_company.status_code == 422
    wrong_company = client.post(
        "/api/whatsapp/webhook/ack",
        json={"company_id": company_b_id, "internal_message_id": internal_id, "status": "sent"},
        headers={"X-Internal-Secret": "secret"},
    )
    assert wrong_company.status_code == 200
    assert wrong_company.json()["success"] is False
    assert db.query(Message).filter(Message.internal_message_id == internal_id).one().delivery_status == "pending"


def test_background_workers_require_matching_tenant_context(db, monkeypatch):
    company_a_id, _ = _tenant(db, "phase5_worker_a")
    company_b_id, _ = _tenant(db, "phase5_worker_b")
    lead_a = Lead(company_id=company_a_id, name="A worker lead", phone="201000000003")
    db.add(lead_a)
    db.commit()

    import engine.analytics_worker as analytics_worker
    import workers.intelligence_worker as intelligence_worker

    monkeypatch.setattr(analytics_worker, "groq_client", object())
    result = asyncio.run(
        analytics_worker.analyze_lead_product_interest(company_b_id, "user", lead_a.id)
    )
    assert result is None
    assert db.query(LeadAnalytics).filter(LeadAnalytics.lead_id == lead_a.id).first() is None

    monkeypatch.setattr(intelligence_worker, "LEGACY_INTELLIGENCE_WORKER_ENABLED", True)
    monkeypatch.setattr(intelligence_worker, "groq_client", object())
    asyncio.run(intelligence_worker.rebuild_lead_intelligence_task(company_b_id, lead_a.id))
    assert db.query(LeadIntelligenceSnapshot).filter(LeadIntelligenceSnapshot.lead_id == lead_a.id).first() is None


def test_v2_memory_reads_and_writes_do_not_cross_tenants(db):
    company_a_id, _ = _tenant(db, "phase5_memory_a")
    company_b_id, _ = _tenant(db, "phase5_memory_b")
    lead_b = Lead(company_id=company_b_id, name="B memory lead", phone="201000000004")
    db.add(lead_b)
    db.commit()

    from services.customer_memory_service import (
        CustomerPreferenceMemorySnapshot,
        evaluate_customer_preference_memory,
        sync_preference_memory_to_db,
    )

    lead_b_id = lead_b.id
    snapshot_b = evaluate_customer_preference_memory(None, company_b_id, lead_b_id, "I prefer mesh")
    sync_preference_memory_to_db(db, company_b_id, lead_b_id, snapshot_b)
    db.expire_all()

    read_as_a = evaluate_customer_preference_memory(db, company_a_id, lead_b_id, "", recent_messages=[])
    assert read_as_a.active_preferences == []
    before = db.query(LeadMemory).filter(LeadMemory.lead_id == lead_b_id).one().preferences
    sync_preference_memory_to_db(
        db,
        company_a_id,
        lead_b_id,
        CustomerPreferenceMemorySnapshot(company_id=company_a_id, lead_id=str(lead_b_id)),
    )
    db.expire_all()
    assert db.query(LeadMemory).filter(LeadMemory.lead_id == lead_b_id).one().preferences == before
