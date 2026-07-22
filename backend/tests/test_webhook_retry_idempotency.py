import pytest
import asyncio
from unittest.mock import patch, AsyncMock
from types import SimpleNamespace

from database import Company, Lead, Message, LeadEvidence, UsageStats, create_company, hash_api_key
import routers.webhook as webhook_module
from routers.webhook import process_webhook_payload


@pytest.fixture(autouse=True)
def _setup_webhook_env(monkeypatch):
    monkeypatch.setattr(webhook_module, "ENABLE_META_WEBHOOK", True)
    monkeypatch.setattr(webhook_module, "META_COMPANY_ID", "wh_idemp_company")


def _seed_company(db, company_id="wh_idemp_company"):
    db.query(Message).filter(Message.company_id == company_id).delete()
    db.query(LeadEvidence).filter(LeadEvidence.company_id == company_id).delete()
    db.query(Lead).filter(Lead.company_id == company_id).delete()
    db.query(UsageStats).filter(UsageStats.company_id == company_id).delete()
    db.query(Company).filter(Company.company_id == company_id).delete()
    db.commit()

    company = Company(
        company_id=company_id,
        company_name="Idempotency Test Co",
        email=f"{company_id}@test.com",
        password="password123",
        api_key_hash=hash_api_key(f"{company_id}-key"),
        plan="PRO",
        bot_auto_reply_enabled=True,
    )
    db.add(company)
    db.commit()
    return company


def _make_payload(ext_id="wamid.test-idemp-001", body="مرحبا أريد معرفة الأنشطة", phone="201000000001"):
    return {
        "entry": [{
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"phone_number_id": "123456"},
                    "contacts": [{"profile": {"name": "Test Customer"}, "wa_id": phone}],
                    "messages": [{
                        "from": phone,
                        "id": ext_id,
                        "timestamp": "1700000000",
                        "type": "text",
                        "text": {"body": body}
                    }]
                }
            }]
        }]
    }


@pytest.mark.asyncio
async def test_duplicate_webhook_same_external_message_id_calls_ai_once(db):
    _seed_company(db)
    payload = _make_payload(ext_id="wamid.ai-once-001")

    mock_groq_resp = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"reply": "أهلاً وسهلاً بك!", "next_conversation_state": "PITCHING", "lead": {"name": "Test Customer", "phone": "01000000001"}, "is_hot_deal": false, "lead_score": 50, "customer_temperature": "warm"}'))]
    )

    with patch("routers.webhook.send_whatsapp_message", new_callable=AsyncMock) as mock_send, \
         patch("brain.groq_client.chat.completions.create", new_callable=AsyncMock) as mock_groq:
        mock_send.return_value = {"success": True, "wa_message_id": "wamid.out-001"}
        mock_groq.return_value = mock_groq_resp

        # First delivery
        await process_webhook_payload(payload)
        ai_calls_1 = mock_groq.call_count
        assert ai_calls_1 >= 1

        # Second delivery (duplicate)
        await process_webhook_payload(payload)
        ai_calls_2 = mock_groq.call_count
        assert ai_calls_2 == ai_calls_1  # 0 additional AI calls!


@pytest.mark.asyncio
async def test_duplicate_webhook_does_not_create_second_incoming_message(db):
    _seed_company(db)
    payload = _make_payload(ext_id="wamid.inc-dedupe-001")

    with patch("routers.webhook.send_whatsapp_message", new_callable=AsyncMock) as mock_send, \
         patch("brain.groq_client.chat.completions.create", new_callable=AsyncMock) as mock_groq:
        mock_send.return_value = {"success": True, "wa_message_id": "wamid.out-002"}
        mock_groq.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"reply": "مرحباً", "lead": {}}'))]
        )

        await process_webhook_payload(payload)
        inc_1 = db.query(Message).filter(Message.company_id == "wh_idemp_company", Message.direction == "incoming").count()
        assert inc_1 == 1

        await process_webhook_payload(payload)
        inc_2 = db.query(Message).filter(Message.company_id == "wh_idemp_company", Message.direction == "incoming").count()
        assert inc_2 == 1


@pytest.mark.asyncio
async def test_duplicate_webhook_does_not_create_second_outgoing_reply(db):
    _seed_company(db)
    payload = _make_payload(ext_id="wamid.out-dedupe-001")

    with patch("routers.webhook.send_whatsapp_message", new_callable=AsyncMock) as mock_send, \
         patch("brain.groq_client.chat.completions.create", new_callable=AsyncMock) as mock_groq:
        mock_send.return_value = {"success": True, "wa_message_id": "wamid.out-003"}
        mock_groq.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"reply": "مرحباً بك", "lead": {}}'))]
        )

        await process_webhook_payload(payload)
        out_1 = db.query(Message).filter(Message.company_id == "wh_idemp_company", Message.direction == "outgoing").count()
        assert out_1 == 1

        await process_webhook_payload(payload)
        out_2 = db.query(Message).filter(Message.company_id == "wh_idemp_company", Message.direction == "outgoing").count()
        assert out_2 == 1


@pytest.mark.asyncio
async def test_duplicate_webhook_does_not_duplicate_evidence(db):
    _seed_company(db)
    payload = _make_payload(ext_id="wamid.ev-dedupe-001")

    with patch("routers.webhook.send_whatsapp_message", new_callable=AsyncMock) as mock_send, \
         patch("brain.groq_client.chat.completions.create", new_callable=AsyncMock) as mock_groq:
        mock_send.return_value = {"success": True, "wa_message_id": "wamid.out-004"}
        mock_groq.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"reply": "نص الرد", "lead": {"name": "Test"}}'))]
        )

        await process_webhook_payload(payload)
        ev_1 = db.query(LeadEvidence).filter(LeadEvidence.company_id == "wh_idemp_company").count()

        await process_webhook_payload(payload)
        ev_2 = db.query(LeadEvidence).filter(LeadEvidence.company_id == "wh_idemp_company").count()
        assert ev_2 == ev_1


@pytest.mark.asyncio
async def test_duplicate_webhook_does_not_repeat_lead_mutation(db):
    _seed_company(db)
    payload = _make_payload(ext_id="wamid.lead-mut-001")

    with patch("routers.webhook.send_whatsapp_message", new_callable=AsyncMock) as mock_send, \
         patch("brain.groq_client.chat.completions.create", new_callable=AsyncMock) as mock_groq:
        mock_send.return_value = {"success": True, "wa_message_id": "wamid.out-005"}
        mock_groq.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"reply": "مرحباً", "lead": {}}'))]
        )

        await process_webhook_payload(payload)
        lead_1 = db.query(Lead).filter(Lead.company_id == "wh_idemp_company").first()
        conv_count_1 = lead_1.conversation_count

        await process_webhook_payload(payload)
        db.refresh(lead_1)
        conv_count_2 = lead_1.conversation_count
        assert conv_count_2 == conv_count_1


@pytest.mark.asyncio
async def test_duplicate_webhook_does_not_repeat_usage_increment(db):
    _seed_company(db)
    payload = _make_payload(ext_id="wamid.usage-001")

    with patch("routers.webhook.send_whatsapp_message", new_callable=AsyncMock) as mock_send, \
         patch("brain.groq_client.chat.completions.create", new_callable=AsyncMock) as mock_groq:
        mock_send.return_value = {"success": True, "wa_message_id": "wamid.out-006"}
        mock_groq.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"reply": "مرحباً", "lead": {}}'))]
        )

        await process_webhook_payload(payload)
        usage_1 = db.query(UsageStats).filter(UsageStats.company_id == "wh_idemp_company").first()
        cnt_1 = usage_1.messages_count if usage_1 else 0

        await process_webhook_payload(payload)
        usage_2 = db.query(UsageStats).filter(UsageStats.company_id == "wh_idemp_company").first()
        cnt_2 = usage_2.messages_count if usage_2 else 0
        assert cnt_2 == cnt_1


@pytest.mark.asyncio
async def test_duplicate_webhook_does_not_repeat_background_tasks(db):
    _seed_company(db)
    payload = _make_payload(ext_id="wamid.bg-tasks-001")

    with patch("routers.webhook.send_whatsapp_message", new_callable=AsyncMock) as mock_send, \
         patch("brain.groq_client.chat.completions.create", new_callable=AsyncMock) as mock_groq, \
         patch("brain._send_fomo_alert_sync") as mock_fomo:
        mock_send.return_value = {"success": True, "wa_message_id": "wamid.out-007"}
        mock_groq.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"reply": "صفقة ممتازة!", "is_hot_deal": true, "lead": {"name": "Hot Lead"}}'))]
        )

        await process_webhook_payload(payload)
        fomo_calls_1 = mock_fomo.call_count

        await process_webhook_payload(payload)
        fomo_calls_2 = mock_fomo.call_count
        assert fomo_calls_2 == fomo_calls_1


@pytest.mark.asyncio
async def test_duplicate_pending_reply_reuses_existing_reply_without_ai_regeneration(db):
    _seed_company(db)
    payload = _make_payload(ext_id="wamid.pending-001")

    with patch("routers.webhook.send_whatsapp_message", new_callable=AsyncMock) as mock_send, \
         patch("brain.groq_client.chat.completions.create", new_callable=AsyncMock) as mock_groq:
        # First send fails, leaving reply in failed/pending status
        mock_send.side_effect = Exception("Meta API timeout")
        mock_groq.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"reply": "رد محمي للتسليم", "lead": {}}'))]
        )

        await process_webhook_payload(payload)
        groq_1 = mock_groq.call_count
        msg = db.query(Message).filter(Message.company_id == "wh_idemp_company", Message.direction == "outgoing").first()
        assert msg.delivery_status == "failed"

        # Second delivery succeeds
        mock_send.side_effect = None
        mock_send.return_value = {"success": True, "wa_message_id": "wamid.out-pending-retry"}
        await process_webhook_payload(payload)

        groq_2 = mock_groq.call_count
        assert groq_2 == groq_1  # No new AI generation!
        db.refresh(msg)
        assert msg.delivery_status == "sent"
        assert msg.wa_message_id == "wamid.out-pending-retry"


@pytest.mark.asyncio
async def test_duplicate_sent_reply_does_not_regenerate_ai(db):
    _seed_company(db)
    payload = _make_payload(ext_id="wamid.sent-001")

    with patch("routers.webhook.send_whatsapp_message", new_callable=AsyncMock) as mock_send, \
         patch("brain.groq_client.chat.completions.create", new_callable=AsyncMock) as mock_groq:
        mock_send.return_value = {"success": True, "wa_message_id": "wamid.out-sent"}
        mock_groq.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"reply": "تم الإرسال", "lead": {}}'))]
        )

        await process_webhook_payload(payload)
        assert mock_groq.call_count >= 1
        cnt_after_1 = mock_groq.call_count

        await process_webhook_payload(payload)
        assert mock_groq.call_count == cnt_after_1


@pytest.mark.asyncio
async def test_duplicate_delivered_reply_does_not_regenerate_ai(db):
    _seed_company(db)
    payload = _make_payload(ext_id="wamid.delivered-001")

    with patch("routers.webhook.send_whatsapp_message", new_callable=AsyncMock) as mock_send, \
         patch("brain.groq_client.chat.completions.create", new_callable=AsyncMock) as mock_groq:
        mock_send.return_value = {"success": True, "wa_message_id": "wamid.out-deliv"}
        mock_groq.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"reply": "تم التسليم", "lead": {}}'))]
        )

        await process_webhook_payload(payload)
        msg = db.query(Message).filter(Message.company_id == "wh_idemp_company", Message.direction == "outgoing").first()
        msg.delivery_status = "delivered"
        db.commit()

        cnt_after_1 = mock_groq.call_count
        await process_webhook_payload(payload)
        assert mock_groq.call_count == cnt_after_1


@pytest.mark.asyncio
async def test_duplicate_read_reply_does_not_regenerate_ai(db):
    _seed_company(db)
    payload = _make_payload(ext_id="wamid.read-001")

    with patch("routers.webhook.send_whatsapp_message", new_callable=AsyncMock) as mock_send, \
         patch("brain.groq_client.chat.completions.create", new_callable=AsyncMock) as mock_groq:
        mock_send.return_value = {"success": True, "wa_message_id": "wamid.out-read"}
        mock_groq.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"reply": "تمت القراءة", "lead": {}}'))]
        )

        await process_webhook_payload(payload)
        msg = db.query(Message).filter(Message.company_id == "wh_idemp_company", Message.direction == "outgoing").first()
        msg.delivery_status = "read"
        db.commit()

        cnt_after_1 = mock_groq.call_count
        await process_webhook_payload(payload)
        assert mock_groq.call_count == cnt_after_1


@pytest.mark.asyncio
async def test_duplicate_failed_reply_does_not_regenerate_ai(db):
    _seed_company(db)
    payload = _make_payload(ext_id="wamid.failed-001")

    with patch("routers.webhook.send_whatsapp_message", new_callable=AsyncMock) as mock_send, \
         patch("brain.groq_client.chat.completions.create", new_callable=AsyncMock) as mock_groq:
        mock_send.side_effect = Exception("Network error")
        mock_groq.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"reply": "محاولة فاشلة", "lead": {}}'))]
        )

        await process_webhook_payload(payload)
        cnt_1 = mock_groq.call_count

        await process_webhook_payload(payload)
        cnt_2 = mock_groq.call_count
        assert cnt_2 == cnt_1


@pytest.mark.asyncio
async def test_duplicate_retry_reuses_existing_internal_message_id(db):
    _seed_company(db)
    payload = _make_payload(ext_id="wamid.internal-id-001")

    with patch("routers.webhook.send_whatsapp_message", new_callable=AsyncMock) as mock_send, \
         patch("brain.groq_client.chat.completions.create", new_callable=AsyncMock) as mock_groq:
        mock_send.return_value = {"success": True, "wa_message_id": "wamid.out-id"}
        mock_groq.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"reply": "اختبار الهوية", "lead": {}}'))]
        )

        await process_webhook_payload(payload)
        inc_msg = db.query(Message).filter(Message.company_id == "wh_idemp_company", Message.direction == "incoming").first()
        orig_internal_id = inc_msg.internal_message_id

        await process_webhook_payload(payload)
        inc_msgs = db.query(Message).filter(Message.company_id == "wh_idemp_company", Message.direction == "incoming").all()
        assert len(inc_msgs) == 1
        assert inc_msgs[0].internal_message_id == orig_internal_id


@pytest.mark.asyncio
async def test_duplicate_retry_preserves_company_scope(db):
    _seed_company(db, company_id="company_A")
    _seed_company(db, company_id="company_B")

    payload_A = _make_payload(ext_id="wamid.shared-001")
    payload_B = _make_payload(ext_id="wamid.shared-001")

    mock_groq_resp = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"reply": "رد", "lead": {}}'))]
    )

    with patch("routers.webhook.send_whatsapp_message", new_callable=AsyncMock) as mock_send, \
         patch("brain.groq_client.chat.completions.create", new_callable=AsyncMock) as mock_groq:
        mock_send.return_value = {"success": True, "wa_message_id": "wamid.out-A"}
        mock_groq.return_value = mock_groq_resp

        # Process company A
        webhook_module.META_COMPANY_ID = "company_A"
        await process_webhook_payload(payload_A)
        assert db.query(Message).filter(Message.company_id == "company_A").count() == 2

        # Duplicate call to company A
        await process_webhook_payload(payload_A)
        assert db.query(Message).filter(Message.company_id == "company_A").count() == 2


@pytest.mark.asyncio
async def test_duplicate_retry_does_not_mutate_existing_message_rows(db):
    _seed_company(db)
    payload = _make_payload(ext_id="wamid.no-mut-001")

    with patch("routers.webhook.send_whatsapp_message", new_callable=AsyncMock) as mock_send, \
         patch("brain.groq_client.chat.completions.create", new_callable=AsyncMock) as mock_groq:
        mock_send.return_value = {"success": True, "wa_message_id": "wamid.out-nomut"}
        mock_groq.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"reply": "رد ثابت", "lead": {}}'))]
        )

        await process_webhook_payload(payload)
        msg_1 = db.query(Message).filter(Message.company_id == "wh_idemp_company", Message.direction == "incoming").first()
        updated_at_1 = msg_1.updated_at

        await process_webhook_payload(payload)
        db.refresh(msg_1)
        assert msg_1.updated_at == updated_at_1


@pytest.mark.asyncio
async def test_missing_external_message_id_preserves_current_behavior(db):
    _seed_company(db)
    payload = _make_payload(ext_id=None)

    with patch("routers.webhook.send_whatsapp_message", new_callable=AsyncMock) as mock_send, \
         patch("brain.groq_client.chat.completions.create", new_callable=AsyncMock) as mock_groq:
        mock_send.return_value = {"success": True, "wa_message_id": "wamid.out-noid"}
        mock_groq.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"reply": "رد بدون ID خارجي", "lead": {}}'))]
        )

        await process_webhook_payload(payload)
        assert mock_groq.call_count >= 1


@pytest.mark.asyncio
async def test_different_external_message_ids_process_normally(db):
    _seed_company(db)
    payload_1 = _make_payload(ext_id="wamid.diff-001", body="رسالة أولى")
    payload_2 = _make_payload(ext_id="wamid.diff-002", body="رسالة ثانية")

    with patch("routers.webhook.send_whatsapp_message", new_callable=AsyncMock) as mock_send, \
         patch("brain.groq_client.chat.completions.create", new_callable=AsyncMock) as mock_groq:
        mock_send.return_value = {"success": True, "wa_message_id": "wamid.out-diff"}
        mock_groq.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"reply": "رد", "lead": {}}'))]
        )

        await process_webhook_payload(payload_1)
        groq_1 = mock_groq.call_count

        await process_webhook_payload(payload_2)
        groq_2 = mock_groq.call_count
        assert groq_2 > groq_1  # Second unique message triggers AI normally!


@pytest.mark.asyncio
async def test_duplicate_webhook_current_customer_message_does_not_reenter_brain(db):
    _seed_company(db)
    payload = _make_payload(ext_id="wamid.no-reenter-001")

    async def fake_get_ai_response(db, user_input, user_id, company_id, background_tasks=None, incoming_wa_message_id=None, **kwargs):
        inc_msg = Message(
            company_id=company_id,
            user_id=user_id,
            direction="incoming",
            sender="user",
            message=user_input,
            wa_message_id=incoming_wa_message_id,
            internal_message_id="internal-in-001",
        )
        out_msg = Message(
            company_id=company_id,
            user_id=user_id,
            direction="outgoing",
            sender="assistant",
            message="رد تجريبي",
            wa_message_id="wamid.out-reenter",
            internal_message_id="internal-out-001",
            delivery_status="sent",
        )
        db.add(inc_msg)
        db.add(out_msg)
        db.commit()
        return ("رد تجريبي", "internal-out-001")

    with patch("routers.webhook.send_whatsapp_message", new_callable=AsyncMock) as mock_send, \
         patch("routers.webhook.get_ai_response", side_effect=fake_get_ai_response) as mock_brain:
        mock_send.return_value = {"success": True, "wa_message_id": "wamid.out-reenter"}

        await process_webhook_payload(payload)
        assert mock_brain.call_count == 1

        await process_webhook_payload(payload)
        assert mock_brain.call_count == 1  # get_ai_response was NOT entered again!


@pytest.mark.asyncio
async def test_duplicate_with_existing_incoming_but_no_reply(db):
    _seed_company(db)
    payload = _make_payload(ext_id="wamid.no-reply-001")

    # Manually seed an incoming message without an outgoing reply that is marked completed/skipped
    inc_msg = Message(
        company_id="wh_idemp_company",
        user_id="201000000001",
        direction="incoming",
        sender="user",
        message="رسالة بدون رد",
        wa_message_id="wamid.no-reply-001",
        internal_message_id="inc-no-reply-uuid",
        processing_status="completed",
    )
    db.add(inc_msg)
    db.commit()

    with patch("routers.webhook.send_whatsapp_message", new_callable=AsyncMock) as mock_send, \
         patch("brain.get_ai_response", new_callable=AsyncMock) as mock_brain:
        await process_webhook_payload(payload)
        assert mock_brain.call_count == 0  # Does NOT regenerate AI!
        assert mock_send.call_count == 0
