from datetime import datetime, timedelta, timezone
import json
import uuid
from unittest.mock import AsyncMock

from database import Company, CompanyKnowledge, Message, SystemEvent, fail_pending_messages, hash_api_key


def _external_company(db, prefix="external_delivery"):
    suffix = uuid.uuid4().hex[:8]
    raw_key = f"{prefix}-{suffix}"
    company = Company(
        company_id=f"{prefix}_{suffix}",
        company_name="External Delivery Merchant",
        email=f"{prefix}_{suffix}@example.com",
        password="hashed",
        api_key_hash=hash_api_key(raw_key),
        plan="PRO",
        bot_auto_reply_enabled=True,
    )
    db.add(company)
    db.add(
        CompanyKnowledge(
            company_id=company.company_id,
            system_prompt="Be concise.",
            products_data='[{"name":"Chair","price":1000,"currency":"EGP"}]',
            knowledge_base="",
        )
    )
    db.commit()
    return company, raw_key


def _v2_result(answer="External V2 reply"):
    return {
        "answer_text": answer,
        "response_envelope": {"message": {"text": answer}},
        "trace": {
            "lead_to_save": None,
            "action_decision": None,
            "sales_snapshot": None,
            "objection_snapshot": None,
            "recommendation_decision": None,
            "conversation_action": None,
            "response_path": "MODEL",
            "response_plan_type": "GREETING",
        },
    }


def test_external_delivery_ack_requires_api_key(client, db):
    response = client.post(
        "/api/external/delivery/ack",
        json={"internal_message_id": "missing", "status": "sent"},
    )
    assert response.status_code == 401
    invalid = client.post(
        "/api/external/delivery/ack",
        json={"internal_message_id": "missing", "status": "sent"},
        headers={"X-API-Key": "not-a-valid-tenant-key"},
    )
    assert invalid.status_code == 401


def test_external_v2_delivery_ack_retry_is_idempotent_and_failure_isolated(
    client,
    db,
    monkeypatch,
):
    company, raw_key = _external_company(db)
    monkeypatch.setenv("EXTERNAL_API_RESPONSE_ENGINE", "v2")
    model = AsyncMock(return_value=_v2_result())
    monkeypatch.setattr("services.velor_chat_v2.get_v2_ai_response", model)
    payload = {
        "message": "Please send the details.",
        "user_id": "external-customer-1",
        "external_message_id": f"ext-{uuid.uuid4().hex}",
    }
    headers = {"X-API-Key": raw_key}

    first = client.post("/chat", json=payload, headers=headers)
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["delivery_status"] == "pending"
    assert first_body["delivery_ack"]["endpoint"] == "/api/external/delivery/ack"
    internal_id = first_body["internal_message_id"]

    created_event = (
        db.query(SystemEvent)
        .filter(
            SystemEvent.company_id == company.company_id,
            SystemEvent.event_type == "message.created",
            SystemEvent.entity_id == internal_id,
        )
        .one()
    )
    assert json.loads(created_event.payload)["channel"] == "EXTERNAL_API"

    failed = client.post(
        "/api/external/delivery/ack",
        json={
            "internal_message_id": internal_id,
            "status": "failed",
            "failure_reason": "client_timeout",
        },
        headers=headers,
    )
    assert failed.status_code == 200
    assert failed.json()["outcome"] == "applied"
    assert failed.json()["delivery_status"] == "failed"

    inbound = (
        db.query(Message)
        .filter(
            Message.company_id == company.company_id,
            Message.direction == "incoming",
        )
        .one()
    )
    outbound = (
        db.query(Message)
        .filter(Message.internal_message_id == internal_id)
        .one()
    )
    assert inbound.processing_status == "completed"
    assert outbound.delivery_status == "failed"
    failure_event = (
        db.query(SystemEvent)
        .filter(
            SystemEvent.company_id == company.company_id,
            SystemEvent.event_type == "delivery.failed",
            SystemEvent.entity_id == internal_id,
        )
        .one()
    )
    assert json.loads(failure_event.payload)["failure_reason"] == "client_timeout"

    retry = client.post("/chat", json=payload, headers=headers)
    assert retry.status_code == 200
    assert retry.json()["duplicate"] is True
    assert retry.json()["redeliver_existing_reply"] is True
    assert retry.json()["delivery_status"] == "failed"
    assert model.await_count == 1

    sent = client.post(
        "/api/external/delivery/ack",
        json={"internal_message_id": internal_id, "status": "sent"},
        headers=headers,
    )
    assert sent.status_code == 200
    assert sent.json()["outcome"] == "applied"
    assert sent.json()["delivery_status"] == "sent"

    duplicate = client.post(
        "/api/external/delivery/ack",
        json={"internal_message_id": internal_id, "status": "sent"},
        headers=headers,
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["outcome"] == "duplicate_or_stale"

    delivered = client.post(
        "/api/external/delivery/ack",
        json={"internal_message_id": internal_id, "status": "delivered"},
        headers=headers,
    )
    assert delivered.status_code == 200
    assert delivered.json()["delivery_status"] == "delivered"

    late_failure = client.post(
        "/api/external/delivery/ack",
        json={
            "internal_message_id": internal_id,
            "status": "failed",
            "failure_reason": "late_provider_error",
        },
        headers=headers,
    )
    assert late_failure.status_code == 200
    assert late_failure.json()["outcome"] == "duplicate_or_stale"
    final_outbound = (
        db.query(Message)
        .filter(Message.internal_message_id == internal_id)
        .one()
    )
    assert final_outbound.delivery_status == "delivered"


def test_stale_pending_messages_fail_with_durable_reason_and_are_not_repeated(db):
    company, _ = _external_company(db, prefix="stale_delivery")
    message = Message(
        company_id=company.company_id,
        user_id="external-customer-stale",
        sender="assistant",
        direction="outgoing",
        message="stale reply",
        internal_message_id=f"stale-{uuid.uuid4().hex}",
        delivery_status="pending",
        created_at=datetime.now(timezone.utc) - timedelta(minutes=10),
    )
    db.add(message)
    db.commit()

    assert fail_pending_messages(db, minutes_old=5) == 1
    db.refresh(message)
    assert message.delivery_status == "failed"
    event = (
        db.query(SystemEvent)
        .filter(
            SystemEvent.company_id == company.company_id,
            SystemEvent.event_type == "delivery.failed",
            SystemEvent.entity_id == message.internal_message_id,
        )
        .one()
    )
    payload = json.loads(event.payload)
    assert payload["failure_reason"] == "stale_pending_timeout:5m"
    assert payload["source"] == "pending_sweeper"
    assert fail_pending_messages(db, minutes_old=5) == 0
