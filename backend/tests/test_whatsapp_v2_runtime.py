import uuid
import json
from unittest.mock import AsyncMock

import pytest

from database import (
    Company,
    CompanyKnowledge,
    Lead,
    Message,
    MessageEvent,
    SystemEvent,
    WebhookInbox,
    WorkspaceSuggestedReply,
    hash_api_key,
)


def _company(db, prefix: str) -> Company:
    suffix = uuid.uuid4().hex[:8]
    company = Company(
        company_id=f"{prefix}_{suffix}",
        company_name="VELOR V2 Merchant",
        email=f"{prefix}_{suffix}@example.com",
        password="hashed",
        api_key_hash=hash_api_key(f"{prefix}-{suffix}"),
        plan="PRO",
        bot_auto_reply_enabled=True,
    )
    db.add(company)
    db.add(
        CompanyKnowledge(
            company_id=company.company_id,
            system_prompt="Be practical and concise.",
            products_data='[{"name":"Chair","price":1000,"currency":"EGP"}]',
            knowledge_base="",
        )
    )
    db.commit()
    return company


def _v2_result(answer: str = "رد V2 مرتبط بالرسالة") -> dict:
    return {
        "answer_text": answer,
        "response_path": "MODEL",
        "response_envelope": {
            "message": {
                "text": answer,
                "language": "ar-EG",
                "register": "EGYPTIAN_COLLOQUIAL",
            },
            "presentation": {
                "product_cards": [],
                "quick_replies": [],
                "primary_action": None,
                "conversation_action": None,
            },
            "meta": {
                "engine_version": "v2",
                "response_path": "MODEL",
                "capability": "GREETING",
            },
        },
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


def test_qr_v2_is_exactly_once_and_redelivers_cached_pending_reply(
    client,
    db,
    monkeypatch,
):
    import services.velor_chat_v2 as v2

    company = _company(db, "qr_v2")
    company_id = company.company_id
    model = AsyncMock(return_value=_v2_result())
    monkeypatch.setenv("WHATSAPP_RESPONSE_ENGINE", "v2")
    monkeypatch.setattr(v2, "get_v2_ai_response", model)

    payload = {
        "message": "محتاج كرسي للشغل",
        "user_id": "201001112223@s.whatsapp.net",
        "external_message_id": f"wamid.qr-v2-{uuid.uuid4().hex}",
    }
    headers = {
        "X-Internal-Secret": "secret",
        "X-Company-ID": company_id,
    }

    first = client.post("/chat", json=payload, headers=headers)
    duplicate = client.post("/chat", json=payload, headers=headers)

    assert first.status_code == 200
    assert first.json()["reply"] == "رد V2 مرتبط بالرسالة"
    assert first.json()["delivery_status"] == "pending"
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True
    assert duplicate.json()["redeliver_existing_reply"] is True
    assert duplicate.json()["reply"] == first.json()["reply"]
    assert model.await_count == 1
    assert model.await_args.kwargs["channel_type"] == "WHATSAPP_QR"

    db.expire_all()
    inbound = db.query(Message).filter(
        Message.company_id == company_id,
        Message.direction == "incoming",
    ).one()
    outbound = db.query(Message).filter(
        Message.company_id == company_id,
        Message.direction == "outgoing",
        Message.sender == "assistant",
    ).one()
    assert outbound.in_reply_to_message_id == inbound.id
    assert outbound.delivery_status == "pending"

    ack = client.post(
        "/api/whatsapp/webhook/ack",
        json={
            "company_id": company_id,
            "internal_message_id": outbound.internal_message_id,
            "wa_message_id": f"wamid.out-{uuid.uuid4().hex}",
            "status": "sent",
        },
        headers={"X-Internal-Secret": "secret"},
    )
    assert ack.status_code == 200
    assert ack.json()["success"] is True

    delivered_duplicate = client.post("/chat", json=payload, headers=headers)
    assert delivered_duplicate.status_code == 200
    assert delivered_duplicate.json()["duplicate"] is True
    assert delivered_duplicate.json()["reply"] is None
    assert delivered_duplicate.json()["redeliver_existing_reply"] is False
    assert model.await_count == 1


def test_qr_v2_requires_provider_message_id(client, db, monkeypatch):
    company = _company(db, "qr_v2_id")
    company_id = company.company_id
    monkeypatch.setenv("WHATSAPP_RESPONSE_ENGINE", "v2")

    response = client.post(
        "/chat",
        json={
            "message": "hello",
            "user_id": "201001112224@s.whatsapp.net",
        },
        headers={
            "X-Internal-Secret": "secret",
            "X-Company-ID": company_id,
        },
    )

    assert response.status_code == 400
    assert "external_message_id" in str(response.json())


def test_qr_ack_is_monotonic_and_duplicate_can_attach_provider_id(
    client,
    db,
):
    company = _company(db, "qr_ack_order")
    company_id = company.company_id
    internal_id = f"qr-ack-{uuid.uuid4().hex}"
    provider_id = f"wamid.qr-ack-{uuid.uuid4().hex}"
    db.add(
        Message(
            company_id=company_id,
            user_id="201001112229@s.whatsapp.net",
            sender="assistant",
            direction="outgoing",
            message="reply",
            internal_message_id=internal_id,
            delivery_status="sent",
        )
    )
    db.commit()

    duplicate_sent = client.post(
        "/api/whatsapp/webhook/ack",
        json={
            "company_id": company_id,
            "internal_message_id": internal_id,
            "wa_message_id": provider_id,
            "status": "sent",
        },
        headers={"X-Internal-Secret": "secret"},
    )
    assert duplicate_sent.status_code == 200

    db.expire_all()
    message = db.query(Message).filter(
        Message.company_id == company_id,
        Message.internal_message_id == internal_id,
    ).one()
    message_id = message.id
    assert message.delivery_status == "sent"
    assert message.wa_message_id == provider_id
    assert db.query(MessageEvent).filter(
        MessageEvent.message_id == message.id
    ).count() == 0

    read = client.post(
        "/api/whatsapp/webhook/ack",
        json={
            "company_id": company_id,
            "internal_message_id": internal_id,
            "wa_message_id": provider_id,
            "status": "read",
        },
        headers={"X-Internal-Secret": "secret"},
    )
    late_failed = client.post(
        "/api/whatsapp/webhook/ack",
        json={
            "company_id": company_id,
            "internal_message_id": internal_id,
            "wa_message_id": provider_id,
            "status": "failed",
        },
        headers={"X-Internal-Secret": "secret"},
    )

    assert read.status_code == 200
    assert late_failed.status_code == 200
    assert "Ignored" in late_failed.json()["detail"]
    db.expire_all()
    message = db.query(Message).filter(Message.id == message_id).one()
    assert message.delivery_status == "read"
    assert [
        event.status
        for event in db.query(MessageEvent)
        .filter(MessageEvent.message_id == message.id)
        .order_by(MessageEvent.id.asc())
        .all()
    ] == ["read"]


def test_delivery_update_rechecks_a_stale_worker_snapshot(
    db,
):
    import routers.webhook as webhook
    from services.message_delivery import apply_message_delivery_update

    company = _company(db, "delivery_stale_worker")
    message = Message(
        company_id=company.company_id,
        user_id="201001112232",
        sender="assistant",
        direction="outgoing",
        message="reply",
        internal_message_id=f"delivery-stale-{uuid.uuid4().hex}",
        delivery_status="pending",
    )
    db.add(message)
    db.commit()
    message_id = message.id

    with webhook.SessionLocal() as stale_worker:
        stale_message = stale_worker.query(Message).filter(
            Message.id == message_id
        ).one()
        assert stale_message.delivery_status == "pending"

        with webhook.SessionLocal() as winning_worker:
            winning_message = winning_worker.query(Message).filter(
                Message.id == message_id
            ).one()
            result = apply_message_delivery_update(
                winning_worker,
                winning_message,
                "read",
            )
            assert result.status_changed is True

        stale_result = apply_message_delivery_update(
            stale_worker,
            stale_message,
            "failed",
        )
        assert stale_result.status_changed is False
        assert stale_result.final_status == "read"

    db.expire_all()
    message = db.query(Message).filter(Message.id == message_id).one()
    assert message.delivery_status == "read"


def test_qr_v2_respects_human_takeover_before_model_call(
    client,
    db,
    monkeypatch,
):
    import services.velor_chat_v2 as v2

    company = _company(db, "qr_v2_pause")
    lead = Lead(
        company_id=company.company_id,
        name="Paused Customer",
        phone="1001112225",
        whatsapp_number="1001112225",
        whatsapp_jid="201001112225@s.whatsapp.net",
        channel_type="WHATSAPP_QR",
        is_paused=True,
    )
    db.add(lead)
    db.commit()
    company_id = company.company_id
    lead_jid = lead.whatsapp_jid

    model = AsyncMock(return_value=_v2_result())
    monkeypatch.setenv("WHATSAPP_RESPONSE_ENGINE", "v2")
    monkeypatch.setattr(v2, "get_v2_ai_response", model)
    external_message_id = f"wamid.pause-{uuid.uuid4().hex}"
    response = client.post(
        "/chat",
        json={
            "message": "محتاج مساعدة",
            "user_id": lead_jid,
            "external_message_id": external_message_id,
        },
        headers={
            "X-Internal-Secret": "secret",
            "X-Company-ID": company_id,
        },
    )

    assert response.status_code == 200
    assert response.json()["auto_reply_skipped"] is True
    assert response.json()["reason"] == "human_takeover_active"
    duplicate = client.post(
        "/chat",
        json={
            "message": "محتاج مساعدة",
            "user_id": lead_jid,
            "external_message_id": external_message_id,
        },
        headers={
            "X-Internal-Secret": "secret",
            "X-Company-ID": company_id,
        },
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True
    model.assert_not_awaited()

    suggestion = db.query(WorkspaceSuggestedReply).filter(
        WorkspaceSuggestedReply.company_id == company_id,
    ).one()
    assert suggestion.source_message_internal_id == response.json()["internal_message_id"]
    assert suggestion.status == "suggested"
    stored_variants = json.loads(suggestion.variants_json)
    assert stored_variants[0]["goal"]
    assert "history_turn_count" in stored_variants[0]["context_signals"]
    assert db.query(Message).filter(
        Message.company_id == company_id,
        Message.direction == "outgoing",
    ).count() == 0
    assert db.query(SystemEvent).filter(
        SystemEvent.company_id == company_id,
        SystemEvent.event_type == "workspace.suggested_reply",
    ).count() == 1


@pytest.mark.asyncio
async def test_meta_v2_human_takeover_creates_one_idempotent_workspace_suggestion(
    db,
    monkeypatch,
):
    import routers.webhook as webhook
    import services.velor_chat_v2 as v2

    company = _company(db, "meta_v2_pause")
    phone = "201001112229"
    lead = Lead(
        company_id=company.company_id,
        name="Paused Meta Customer",
        phone=phone,
        whatsapp_number=phone,
        whatsapp_jid=phone,
        external_customer_id=phone,
        channel_type="WHATSAPP_META",
        is_paused=True,
    )
    db.add(lead)
    db.commit()

    model = AsyncMock(return_value=_v2_result())
    monkeypatch.setattr(v2, "get_v2_ai_response", model)
    external_message_id = f"wamid.meta-pause-{uuid.uuid4().hex}"
    payload = {
        "db": db,
        "company": company,
        "raw_phone": phone,
        "phone": phone,
        "text_body": "عايز أعرف سعر Chair",
        "external_message_id": external_message_id,
        "client_name": "Paused Meta Customer",
    }

    await webhook._process_meta_message_v2(**payload)
    await webhook._process_meta_message_v2(**payload)

    model.assert_not_awaited()
    suggestion = db.query(WorkspaceSuggestedReply).filter(
        WorkspaceSuggestedReply.company_id == company.company_id,
    ).one()
    inbound = db.query(Message).filter(
        Message.company_id == company.company_id,
        Message.direction == "incoming",
    ).one()
    assert suggestion.source_message_internal_id == inbound.internal_message_id
    assert suggestion.status == "suggested"
    stored_variants = json.loads(suggestion.variants_json)
    assert stored_variants[0]["goal"]
    assert "history_turn_count" in stored_variants[0]["context_signals"]
    assert db.query(Message).filter(
        Message.company_id == company.company_id,
        Message.direction == "outgoing",
    ).count() == 0
    assert db.query(SystemEvent).filter(
        SystemEvent.company_id == company.company_id,
        SystemEvent.event_type == "workspace.suggested_reply",
    ).count() == 1


@pytest.mark.asyncio
async def test_meta_v2_persists_then_sends_and_never_regenerates_duplicate(
    db,
    monkeypatch,
):
    import routers.webhook as webhook
    import services.velor_chat_v2 as v2

    company = _company(db, "meta_v2")
    model = AsyncMock(return_value=_v2_result("رد Meta V2"))
    sender = AsyncMock(
        return_value={
            "success": True,
            "wa_message_id": f"wamid.meta-out-{uuid.uuid4().hex}",
        }
    )
    monkeypatch.setenv("WHATSAPP_RESPONSE_ENGINE", "v2")
    monkeypatch.setattr(webhook, "ENABLE_META_WEBHOOK", True)
    monkeypatch.setattr(webhook, "META_COMPANY_ID", company.company_id)
    monkeypatch.setattr(webhook, "send_whatsapp_message", sender)
    monkeypatch.setattr(webhook, "summarize_conversation", AsyncMock())
    monkeypatch.setattr(v2, "get_v2_ai_response", model)

    external_id = f"wamid.meta-in-{uuid.uuid4().hex}"
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": "meta-phone-1"},
                            "contacts": [
                                {
                                    "profile": {"name": "Meta Customer"},
                                }
                            ],
                            "messages": [
                                {
                                    "id": external_id,
                                    "from": "201001112226",
                                    "type": "text",
                                    "text": {"body": "عايز أعرف المنتجات"},
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }

    await webhook.process_webhook_payload(payload)
    await webhook.process_webhook_payload(payload)

    assert model.await_count == 1
    assert model.await_args.kwargs["channel_type"] == "WHATSAPP_META"
    assert sender.await_count == 1
    db.expire_all()
    inbound = db.query(Message).filter(
        Message.company_id == company.company_id,
        Message.direction == "incoming",
    ).one()
    outbound = db.query(Message).filter(
        Message.company_id == company.company_id,
        Message.direction == "outgoing",
        Message.sender == "assistant",
    ).one()
    assert outbound.in_reply_to_message_id == inbound.id
    assert outbound.delivery_status == "sent"
    assert outbound.wa_message_id

    await webhook.process_webhook_payload(
        {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "metadata": {
                                    "phone_number_id": "meta-phone-1",
                                },
                                "statuses": [
                                    {
                                        "id": outbound.wa_message_id,
                                        "status": "delivered",
                                    }
                                ],
                            }
                        }
                    ]
                }
            ]
        }
    )
    db.expire_all()
    assert db.query(Message).filter(Message.id == outbound.id).one().delivery_status == "delivered"


def test_meta_delivery_state_does_not_regress_after_read(
    db,
    monkeypatch,
):
    import routers.webhook as webhook

    company = _company(db, "meta_status_order")
    provider_id = f"wamid.meta-status-{uuid.uuid4().hex}"
    message = Message(
        company_id=company.company_id,
        user_id="201001112230",
        sender="assistant",
        direction="outgoing",
        message="reply",
        internal_message_id=f"meta-status-{uuid.uuid4().hex}",
        wa_message_id=provider_id,
        delivery_status="read",
    )
    db.add(message)
    db.commit()
    monkeypatch.setattr(webhook, "META_COMPANY_ID", company.company_id)

    webhook._process_meta_delivery_statuses(
        {
            "metadata": {"phone_number_id": "meta-status-phone"},
            "statuses": [{"id": provider_id, "status": "failed"}],
        }
    )

    db.expire_all()
    message = db.query(Message).filter(Message.id == message.id).one()
    assert message.delivery_status == "read"
    assert db.query(MessageEvent).filter(
        MessageEvent.message_id == message.id
    ).count() == 0


def test_meta_failed_after_acceptance_and_retry_relinks_new_send_attempt(
    db,
    monkeypatch,
):
    import routers.webhook as webhook

    company = _company(db, "meta_send_retry")
    old_provider_id = f"wamid.meta-old-{uuid.uuid4().hex}"
    new_provider_id = f"wamid.meta-new-{uuid.uuid4().hex}"
    message = Message(
        company_id=company.company_id,
        user_id="1001112233",
        sender="assistant",
        direction="outgoing",
        message="reply",
        internal_message_id=f"meta-retry-{uuid.uuid4().hex}",
        wa_message_id=old_provider_id,
        delivery_status="sent",
    )
    db.add(message)
    db.commit()
    message_id = message.id
    internal_id = message.internal_message_id
    monkeypatch.setattr(webhook, "META_COMPANY_ID", company.company_id)

    webhook._process_meta_delivery_statuses(
        {
            "metadata": {"phone_number_id": "meta-retry-phone"},
            "statuses": [
                {
                    "id": old_provider_id,
                    "recipient_id": "201001112233",
                    "status": "failed",
                }
            ],
        }
    )
    with webhook.SessionLocal() as retry_db:
        webhook._publish_message_delivery_update(
            retry_db,
            company.company_id,
            internal_id,
            "sent",
            new_provider_id,
        )

    db.expire_all()
    message = db.query(Message).filter(Message.id == message_id).one()
    assert message.delivery_status == "sent"
    assert message.wa_message_id == new_provider_id

    webhook._process_meta_delivery_statuses(
        {
            "metadata": {"phone_number_id": "meta-retry-phone"},
            "statuses": [
                {
                    "id": new_provider_id,
                    "recipient_id": "201001112233",
                    "status": "delivered",
                }
            ],
        }
    )
    db.expire_all()
    message = db.query(Message).filter(Message.id == message_id).one()
    assert message.delivery_status == "delivered"
    assert [
        event.status
        for event in db.query(MessageEvent)
        .filter(MessageEvent.message_id == message_id)
        .order_by(MessageEvent.id.asc())
        .all()
    ] == ["failed", "sent", "delivered"]


@pytest.mark.asyncio
async def test_meta_v2_processes_every_message_in_a_batched_change(
    db,
    monkeypatch,
):
    import routers.webhook as webhook
    import services.velor_chat_v2 as v2

    company = _company(db, "meta_v2_batch")
    model = AsyncMock(return_value=_v2_result("رد مجمع"))
    sender = AsyncMock(
        side_effect=[
            {"success": True, "wa_message_id": f"wamid.batch-out-{uuid.uuid4().hex}"},
            {"success": True, "wa_message_id": f"wamid.batch-out-{uuid.uuid4().hex}"},
        ]
    )
    monkeypatch.setenv("WHATSAPP_RESPONSE_ENGINE", "v2")
    monkeypatch.setattr(webhook, "ENABLE_META_WEBHOOK", True)
    monkeypatch.setattr(webhook, "META_COMPANY_ID", company.company_id)
    monkeypatch.setattr(webhook, "send_whatsapp_message", sender)
    monkeypatch.setattr(webhook, "summarize_conversation", AsyncMock())
    monkeypatch.setattr(v2, "get_v2_ai_response", model)

    await webhook.process_webhook_payload(
        {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "metadata": {"phone_number_id": "batch-phone"},
                                "contacts": [{"profile": {"name": "Batch Customer"}}],
                                "messages": [
                                    {
                                        "id": f"wamid.batch-in-{uuid.uuid4().hex}",
                                        "from": "201001112227",
                                        "type": "text",
                                        "text": {"body": "الرسالة الأولى"},
                                    },
                                    {
                                        "id": f"wamid.batch-in-{uuid.uuid4().hex}",
                                        "from": "201001112227",
                                        "type": "text",
                                        "text": {"body": "الرسالة الثانية"},
                                    },
                                ],
                            }
                        }
                    ]
                }
            ]
        }
    )

    assert model.await_count == 2
    assert sender.await_count == 2
    assert db.query(Message).filter(
        Message.company_id == company.company_id,
        Message.direction == "incoming",
    ).count() == 2
    assert db.query(Message).filter(
        Message.company_id == company.company_id,
        Message.direction == "outgoing",
        Message.sender == "assistant",
    ).count() == 2


def test_durable_meta_inbox_recovers_a_task_lost_after_provider_ack(
    db,
    monkeypatch,
):
    import routers.webhook as webhook
    import services.velor_chat_v2 as v2

    company = _company(db, "meta_v2_inbox")
    model = AsyncMock(return_value=_v2_result("رد مستعاد"))
    sender = AsyncMock(
        return_value={
            "success": True,
            "wa_message_id": f"wamid.inbox-out-{uuid.uuid4().hex}",
        }
    )
    monkeypatch.setenv("WHATSAPP_RESPONSE_ENGINE", "v2")
    monkeypatch.setattr(webhook, "ENABLE_META_WEBHOOK", True)
    monkeypatch.setattr(webhook, "META_COMPANY_ID", company.company_id)
    monkeypatch.setattr(webhook, "send_whatsapp_message", sender)
    monkeypatch.setattr(webhook, "summarize_conversation", AsyncMock())
    monkeypatch.setattr(v2, "get_v2_ai_response", model)

    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": "inbox-phone"},
                            "contacts": [{"profile": {"name": "Inbox Customer"}}],
                            "messages": [
                                {
                                    "id": f"wamid.inbox-in-{uuid.uuid4().hex}",
                                    "from": "201001112228",
                                    "type": "text",
                                    "text": {"body": "رسالة يجب ألا تضيع"},
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }
    body = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    item = webhook._persist_meta_webhook_inbox(body, payload)

    assert item.status == "pending"
    assert webhook.recover_pending_webhook_inbox() == 1
    db.expire_all()
    persisted_item = db.query(WebhookInbox).filter(
        WebhookInbox.id == item.id
    ).one()
    assert persisted_item.status == "completed"
    assert persisted_item.attempts == 1
    assert model.await_count == 1
    assert sender.await_count == 1
    assert webhook.recover_pending_webhook_inbox() == 0


@pytest.mark.asyncio
async def test_durable_meta_status_retries_until_outbound_id_is_linked(
    db,
    monkeypatch,
):
    import routers.webhook as webhook

    company = _company(db, "meta_status_race")
    provider_id = f"wamid.meta-race-{uuid.uuid4().hex}"
    recipient_id = "201001112231"
    monkeypatch.setattr(webhook, "ENABLE_META_WEBHOOK", True)
    monkeypatch.setattr(webhook, "META_COMPANY_ID", company.company_id)
    message = Message(
        company_id=company.company_id,
        user_id=webhook.normalize_whatsapp_number(recipient_id),
        sender="assistant",
        direction="outgoing",
        message="reply",
        internal_message_id=f"meta-race-{uuid.uuid4().hex}",
        delivery_status="sent",
    )
    db.add(message)
    db.commit()
    message_id = message.id
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": "meta-race-phone"},
                            "statuses": [
                                {
                                    "id": provider_id,
                                    "recipient_id": recipient_id,
                                    "status": "delivered",
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }
    item = webhook._persist_meta_webhook_inbox(
        json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        payload,
    )

    assert await webhook.process_webhook_inbox_item(item.id) is False
    db.expire_all()
    failed_item = db.query(WebhookInbox).filter(
        WebhookInbox.id == item.id
    ).one()
    assert failed_item.status == "failed"
    assert failed_item.last_error_category == "MetaDeliveryStatusNotLinked"

    message = db.query(Message).filter(Message.id == message_id).one()
    message.wa_message_id = provider_id
    db.commit()

    assert await webhook.process_webhook_inbox_item(item.id) is True
    db.expire_all()
    completed_item = db.query(WebhookInbox).filter(
        WebhookInbox.id == item.id
    ).one()
    message = db.query(Message).filter(Message.id == message_id).one()
    assert completed_item.status == "completed"
    assert completed_item.attempts == 2
    assert message.delivery_status == "delivered"


@pytest.mark.asyncio
async def test_durable_meta_status_ignores_provider_messages_we_do_not_track(
    db,
    monkeypatch,
):
    import routers.webhook as webhook

    company = _company(db, "meta_status_external")
    monkeypatch.setattr(webhook, "ENABLE_META_WEBHOOK", True)
    monkeypatch.setattr(webhook, "META_COMPANY_ID", company.company_id)
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": "meta-external-phone"},
                            "statuses": [
                                {
                                    "id": f"wamid.external-{uuid.uuid4().hex}",
                                    "recipient_id": "201001119999",
                                    "status": "delivered",
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }
    item = webhook._persist_meta_webhook_inbox(
        json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        payload,
    )

    assert await webhook.process_webhook_inbox_item(item.id) is True
    db.expire_all()
    completed_item = db.query(WebhookInbox).filter(
        WebhookInbox.id == item.id
    ).one()
    assert completed_item.status == "completed"
    assert completed_item.attempts == 1
