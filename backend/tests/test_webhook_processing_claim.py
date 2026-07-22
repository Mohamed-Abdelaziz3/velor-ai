import asyncio
import threading
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from database import Company, Lead, LeadEvidence, Message, UsageStats, hash_api_key
import routers.webhook as webhook_module
from routers.webhook import process_webhook_payload
from services.processing_claim import (
    acquire_inbound_processing_claim,
    finalize_inbound_processing_claim,
    ClaimResult,
)


@pytest.fixture(autouse=True)
def _setup_webhook_env(monkeypatch):
    monkeypatch.setattr(webhook_module, "ENABLE_META_WEBHOOK", True)
    monkeypatch.setattr(webhook_module, "META_COMPANY_ID", "claim_test_co")


def _seed_company(db, company_id="claim_test_co", auto_reply=True):
    db.query(Message).filter(Message.company_id == company_id).delete()
    db.query(LeadEvidence).filter(LeadEvidence.company_id == company_id).delete()
    db.query(Lead).filter(Lead.company_id == company_id).delete()
    db.query(UsageStats).filter(UsageStats.company_id == company_id).delete()
    db.query(Company).filter(Company.company_id == company_id).delete()
    db.commit()

    company = Company(
        company_id=company_id,
        company_name="Claim Test Company",
        email=f"{company_id}@test.com",
        password="password123",
        api_key_hash=hash_api_key(f"{company_id}-key"),
        plan="PRO",
        bot_auto_reply_enabled=auto_reply,
    )
    db.add(company)
    db.commit()
    return company


def _make_payload(ext_id="wamid.claim-001", body="مرحبا أود الاستفسار", phone="201000000001"):
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"phone_number_id": "123456"},
                            "contacts": [{"profile": {"name": "Claim Customer"}, "wa_id": phone}],
                            "messages": [
                                {
                                    "from": phone,
                                    "id": ext_id,
                                    "timestamp": "1700000000",
                                    "type": "text",
                                    "text": {"body": body},
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }


@pytest.mark.asyncio
async def test_concurrent_duplicate_webhooks_have_one_processing_owner(db):
    _seed_company(db)
    payload = _make_payload(ext_id="wamid.concurrent-owner-001")

    provider_calls = []

    async def blocking_get_ai_response(*args, **kwargs):
        await asyncio.sleep(0.1)
        provider_calls.append(1)
        return ("رد تجريبي للأصلي", "internal-msg-claim-owner")

    with patch("routers.webhook.send_whatsapp_message", new_callable=AsyncMock) as mock_send, patch(
        "routers.webhook.get_ai_response", side_effect=blocking_get_ai_response
    ):
        mock_send.return_value = {"success": True, "wa_message_id": "wamid.out-claim-owner"}

        task1 = asyncio.create_task(process_webhook_payload(payload))
        task2 = asyncio.create_task(process_webhook_payload(payload))

        await asyncio.gather(task1, task2)

    assert len(provider_calls) == 1
    incoming = db.query(Message).filter(Message.company_id == "claim_test_co", Message.direction == "incoming").all()
    assert len(incoming) == 1


@pytest.mark.asyncio
async def test_concurrent_duplicate_webhooks_generate_one_logical_reply(db):
    _seed_company(db)
    payload = _make_payload(ext_id="wamid.concurrent-reply-001")

    async def slow_get_ai_response(*args, **kwargs):
        await asyncio.sleep(0.1)
        from database import save_message
        save_message(db, "claim_test_co", "1000000001", "assistant", "رد وحيد", "internal-msg-one-reply", "outgoing")
        return ("رد وحيد", "internal-msg-one-reply")

    with patch("routers.webhook.send_whatsapp_message", new_callable=AsyncMock) as mock_send, patch(
        "routers.webhook.get_ai_response", side_effect=slow_get_ai_response
    ):
        mock_send.return_value = {"success": True, "wa_message_id": "wamid.out-one-reply"}

        await asyncio.gather(
            process_webhook_payload(payload),
            process_webhook_payload(payload),
        )

    outgoing = db.query(Message).filter(Message.company_id == "claim_test_co", Message.direction == "outgoing").all()
    assert len(outgoing) == 1


@pytest.mark.asyncio
async def test_duplicate_integrity_error_never_triggers_ai_fallback(db):
    _seed_company(db)
    payload = _make_payload(ext_id="wamid.integrity-fallback-001")

    fallback_called = False

    def fake_heuristic(*args, **kwargs):
        nonlocal fallback_called
        fallback_called = True
        return {"reply": "fallback text"}

    async def fake_ai(*args, **kwargs):
        from database import save_message
        save_message(db, "claim_test_co", "1000000001", "assistant", "رد سليم", "internal-msg-integrity-ok", "outgoing")
        return ("رد سليم", "internal-msg-integrity-ok")

    with patch("brain._heuristic_ai_payload", side_effect=fake_heuristic), patch(
        "routers.webhook.send_whatsapp_message", new_callable=AsyncMock
    ) as mock_send, patch("routers.webhook.get_ai_response", side_effect=fake_ai):
        mock_send.return_value = {"success": True, "wa_message_id": "wamid.out-integrity"}

        await asyncio.gather(
            process_webhook_payload(payload),
            process_webhook_payload(payload),
        )

    assert not fallback_called


@pytest.mark.asyncio
async def test_crash_after_incoming_persistence_is_retryable(db):
    _seed_company(db)
    payload = _make_payload(ext_id="wamid.crash-retry-001")

    inc_msg = Message(
        company_id="claim_test_co",
        user_id="1000000001",
        direction="incoming",
        sender="user",
        message="رسالة قبل الكراش",
        wa_message_id="wamid.crash-retry-001",
        internal_message_id="inc-crash-001",
        processing_status="failed",
        processing_started_at=datetime.now(timezone.utc) - timedelta(seconds=70),
    )
    db.add(inc_msg)
    db.commit()

    async def fake_ai(*args, **kwargs):
        from database import save_message
        save_message(db, "claim_test_co", "1000000001", "assistant", "رد التعافي", "internal-msg-recovered", "outgoing")
        return ("رد التعافي", "internal-msg-recovered")

    with patch("routers.webhook.send_whatsapp_message", new_callable=AsyncMock) as mock_send, patch(
        "routers.webhook.get_ai_response", side_effect=fake_ai
    ) as mock_brain:
        mock_send.return_value = {"success": True, "wa_message_id": "wamid.out-crash-rec"}

        await process_webhook_payload(payload)

        assert mock_brain.call_count == 1
        outgoing = db.query(Message).filter(Message.company_id == "claim_test_co", Message.direction == "outgoing").all()
        assert len(outgoing) == 1


@pytest.mark.asyncio
async def test_retryable_partial_attempt_recovers_customer_message(db):
    _seed_company(db)
    payload = _make_payload(ext_id="wamid.partial-rec-001")

    inc_msg = Message(
        company_id="claim_test_co",
        user_id="201000000001",
        direction="incoming",
        sender="user",
        message="رسالة العميل المستعادة",
        wa_message_id="wamid.partial-rec-001",
        internal_message_id="inc-partial-rec-001",
        processing_status="failed",
    )
    db.add(inc_msg)
    db.commit()

    async def fake_ai(*args, **kwargs):
        return ("تم الاسترجاع بنجاح", "internal-msg-partial-rec")

    with patch("routers.webhook.send_whatsapp_message", new_callable=AsyncMock) as mock_send, patch(
        "routers.webhook.get_ai_response", side_effect=fake_ai
    ):
        mock_send.return_value = {"success": True, "wa_message_id": "wamid.out-partial-rec"}

        await process_webhook_payload(payload)

    db.refresh(inc_msg)
    assert inc_msg.processing_status == "completed"


@pytest.mark.asyncio
async def test_active_processing_duplicate_does_not_reenter_ai(db):
    _seed_company(db)
    payload = _make_payload(ext_id="wamid.active-dup-001")

    inc_msg = Message(
        company_id="claim_test_co",
        user_id="201000000001",
        direction="incoming",
        sender="user",
        message="رسالة قيد المعالجة",
        wa_message_id="wamid.active-dup-001",
        internal_message_id="inc-active-dup-001",
        processing_status="processing",
        processing_started_at=datetime.now(timezone.utc),
    )
    db.add(inc_msg)
    db.commit()

    with patch("routers.webhook.get_ai_response", new_callable=AsyncMock) as mock_brain:
        await process_webhook_payload(payload)
        assert mock_brain.call_count == 0


@pytest.mark.asyncio
async def test_retryable_attempt_reclaimed_by_only_one_worker(db):
    _seed_company(db)
    ext_id = "wamid.one-reclaimer-001"

    inc_msg = Message(
        company_id="claim_test_co",
        user_id="201000000001",
        direction="incoming",
        sender="user",
        message="رسالة التنافس علي الاسترجاع",
        wa_message_id=ext_id,
        internal_message_id="inc-reclaim-race-001",
        processing_status="failed",
        processing_started_at=datetime.now(timezone.utc) - timedelta(seconds=120),
    )
    db.add(inc_msg)
    db.commit()

    res1, msg1 = acquire_inbound_processing_claim(db, "claim_test_co", "201000000001", ext_id, "رسالة التنافس علي الاسترجاع")
    res2, msg2 = acquire_inbound_processing_claim(db, "claim_test_co", "201000000001", ext_id, "رسالة التنافس علي الاسترجاع")

    assert (res1 == ClaimResult.RETRYABLE_RECLAIMED and res2 == ClaimResult.ALREADY_PROCESSING) or (
        res2 == ClaimResult.RETRYABLE_RECLAIMED and res1 == ClaimResult.ALREADY_PROCESSING
    )


@pytest.mark.asyncio
async def test_intentional_skip_is_not_retried(db):
    _seed_company(db)
    payload = _make_payload(ext_id="wamid.skip-no-retry-001")

    inc_msg = Message(
        company_id="claim_test_co",
        user_id="201000000001",
        direction="incoming",
        sender="user",
        message="رسالة مستبعدة عمداً",
        wa_message_id="wamid.skip-no-retry-001",
        internal_message_id="inc-skip-001",
        processing_status="skipped",
    )
    db.add(inc_msg)
    db.commit()

    with patch("routers.webhook.get_ai_response", new_callable=AsyncMock) as mock_brain:
        await process_webhook_payload(payload)
        assert mock_brain.call_count == 0


@pytest.mark.asyncio
async def test_human_takeover_skip_remains_suppressed(db):
    _seed_company(db)
    payload = _make_payload(ext_id="wamid.human-skip-001")

    lead = Lead(
        company_id="claim_test_co",
        phone="201000000001",
        whatsapp_number="1000000001",
        name="Human Lead",
        is_paused=True,
    )
    db.add(lead)
    db.commit()

    with patch("routers.webhook.get_ai_response", new_callable=AsyncMock) as mock_brain:
        await process_webhook_payload(payload)
        assert mock_brain.call_count == 0

        # Now send duplicate webhook
        await process_webhook_payload(payload)
        assert mock_brain.call_count == 0


@pytest.mark.asyncio
async def test_auto_reply_disabled_skip_remains_suppressed(db):
    _seed_company(db, auto_reply=False)
    payload = _make_payload(ext_id="wamid.auto-off-skip-001")

    with patch("routers.webhook.get_ai_response", new_callable=AsyncMock) as mock_brain:
        await process_webhook_payload(payload)
        assert mock_brain.call_count == 0

        # Duplicate webhook
        await process_webhook_payload(payload)
        assert mock_brain.call_count == 0


@pytest.mark.asyncio
async def test_completed_pending_reply_reuses_cached_text(db):
    _seed_company(db)
    payload = _make_payload(ext_id="wamid.completed-pending-001")

    inc_msg = Message(
        company_id="claim_test_co",
        user_id="1000000001",
        direction="incoming",
        sender="user",
        message="سؤال سابق",
        wa_message_id="wamid.completed-pending-001",
        internal_message_id="inc-pending-001",
        processing_status="completed",
    )
    out_msg = Message(
        company_id="claim_test_co",
        user_id="1000000001",
        direction="outgoing",
        sender="assistant",
        message="رد معلق مسبق",
        internal_message_id="out-pending-001",
        delivery_status="pending",
    )
    db.add_all([inc_msg, out_msg])
    db.commit()

    with patch("routers.webhook.send_whatsapp_message", new_callable=AsyncMock) as mock_send, patch(
        "routers.webhook.get_ai_response", new_callable=AsyncMock
    ) as mock_brain:
        mock_send.return_value = {"success": True, "wa_message_id": "wamid.out-pending-resend"}

        await process_webhook_payload(payload)

        assert mock_brain.call_count == 0
        assert mock_send.call_count == 1
        mock_send.assert_called_once_with("201000000001", "رد معلق مسبق")


@pytest.mark.asyncio
async def test_completed_failed_reply_reuses_cached_text(db):
    _seed_company(db)
    payload = _make_payload(ext_id="wamid.completed-failed-001")

    inc_msg = Message(
        company_id="claim_test_co",
        user_id="1000000001",
        direction="incoming",
        sender="user",
        message="سؤال سابق فشل إرساله",
        wa_message_id="wamid.completed-failed-001",
        internal_message_id="inc-failed-001",
        processing_status="completed",
    )
    out_msg = Message(
        company_id="claim_test_co",
        user_id="1000000001",
        direction="outgoing",
        sender="assistant",
        message="رد سابق فشل إرساله",
        internal_message_id="out-failed-001",
        delivery_status="failed",
    )
    db.add_all([inc_msg, out_msg])
    db.commit()

    with patch("routers.webhook.send_whatsapp_message", new_callable=AsyncMock) as mock_send, patch(
        "routers.webhook.get_ai_response", new_callable=AsyncMock
    ) as mock_brain:
        mock_send.return_value = {"success": True, "wa_message_id": "wamid.out-failed-resend"}

        await process_webhook_payload(payload)

        assert mock_brain.call_count == 0
        assert mock_send.call_count == 1


@pytest.mark.asyncio
async def test_completed_sent_reply_does_not_resend(db):
    _seed_company(db)
    payload = _make_payload(ext_id="wamid.completed-sent-001")

    inc_msg = Message(
        company_id="claim_test_co",
        user_id="1000000001",
        direction="incoming",
        sender="user",
        message="سؤال تم إرساله",
        wa_message_id="wamid.completed-sent-001",
        internal_message_id="inc-sent-001",
        processing_status="completed",
    )
    out_msg = Message(
        company_id="claim_test_co",
        user_id="1000000001",
        direction="outgoing",
        sender="assistant",
        message="رد تم إرساله",
        wa_message_id="wamid.out-sent-001",
        internal_message_id="out-sent-001",
        delivery_status="sent",
    )
    db.add_all([inc_msg, out_msg])
    db.commit()

    with patch("routers.webhook.send_whatsapp_message", new_callable=AsyncMock) as mock_send, patch(
        "routers.webhook.get_ai_response", new_callable=AsyncMock
    ) as mock_brain:
        await process_webhook_payload(payload)

        assert mock_brain.call_count == 0
        assert mock_send.call_count == 0


@pytest.mark.asyncio
async def test_completed_delivered_reply_does_not_resend(db):
    _seed_company(db)
    payload = _make_payload(ext_id="wamid.completed-deliv-001")

    inc_msg = Message(
        company_id="claim_test_co",
        user_id="1000000001",
        direction="incoming",
        sender="user",
        message="سؤال تم تسليمه",
        wa_message_id="wamid.completed-deliv-001",
        internal_message_id="inc-deliv-001",
        processing_status="completed",
    )
    out_msg = Message(
        company_id="claim_test_co",
        user_id="1000000001",
        direction="outgoing",
        sender="assistant",
        message="رد تم تسليمه",
        wa_message_id="wamid.out-deliv-001",
        internal_message_id="out-deliv-001",
        delivery_status="delivered",
    )
    db.add_all([inc_msg, out_msg])
    db.commit()

    with patch("routers.webhook.send_whatsapp_message", new_callable=AsyncMock) as mock_send, patch(
        "routers.webhook.get_ai_response", new_callable=AsyncMock
    ) as mock_brain:
        await process_webhook_payload(payload)

        assert mock_brain.call_count == 0
        assert mock_send.call_count == 0


@pytest.mark.asyncio
async def test_completed_read_reply_does_not_resend(db):
    _seed_company(db)
    payload = _make_payload(ext_id="wamid.completed-read-001")

    inc_msg = Message(
        company_id="claim_test_co",
        user_id="1000000001",
        direction="incoming",
        sender="user",
        message="سؤال قُرئ",
        wa_message_id="wamid.completed-read-001",
        internal_message_id="inc-read-001",
        processing_status="completed",
    )
    out_msg = Message(
        company_id="claim_test_co",
        user_id="1000000001",
        direction="outgoing",
        sender="assistant",
        message="رد قُرئ",
        wa_message_id="wamid.out-read-001",
        internal_message_id="out-read-001",
        delivery_status="read",
    )
    db.add_all([inc_msg, out_msg])
    db.commit()

    with patch("routers.webhook.send_whatsapp_message", new_callable=AsyncMock) as mock_send, patch(
        "routers.webhook.get_ai_response", new_callable=AsyncMock
    ) as mock_brain:
        await process_webhook_payload(payload)

        assert mock_brain.call_count == 0
        assert mock_send.call_count == 0


@pytest.mark.asyncio
async def test_processing_owner_only_schedules_background_tasks(db):
    _seed_company(db)
    payload = _make_payload(ext_id="wamid.owner-tasks-001")

    async def fake_ai(*args, **kwargs):
        return ("رد مهمات", "internal-msg-owner-tasks")

    with patch("routers.webhook.send_whatsapp_message", new_callable=AsyncMock) as mock_send, patch(
        "routers.webhook.get_ai_response", side_effect=fake_ai
    ) as mock_brain:
        mock_send.return_value = {"success": True, "wa_message_id": "wamid.out-tasks"}

        await asyncio.gather(
            process_webhook_payload(payload),
            process_webhook_payload(payload),
        )

        assert mock_brain.call_count == 1


@pytest.mark.asyncio
async def test_processing_owner_only_mutates_usage(db):
    _seed_company(db)
    payload = _make_payload(ext_id="wamid.usage-owner-001")

    async def fake_ai(*args, **kwargs):
        return ("رد الاستهلاك", "internal-msg-usage-owner")

    with patch("routers.webhook.send_whatsapp_message", new_callable=AsyncMock) as mock_send, patch(
        "routers.webhook.get_ai_response", side_effect=fake_ai
    ):
        mock_send.return_value = {"success": True, "wa_message_id": "wamid.out-usage"}

        await asyncio.gather(
            process_webhook_payload(payload),
            process_webhook_payload(payload),
        )

    stats = db.query(UsageStats).filter(UsageStats.company_id == "claim_test_co").first()
    assert stats.messages_count == 1


@pytest.mark.asyncio
async def test_processing_owner_only_persists_evidence(db):
    _seed_company(db)
    payload = _make_payload(ext_id="wamid.evid-owner-001")

    async def fake_ai(*args, **kwargs):
        return ("رد الأدلة", "internal-msg-evid-owner")

    with patch("routers.webhook.send_whatsapp_message", new_callable=AsyncMock) as mock_send, patch(
        "routers.webhook.get_ai_response", side_effect=fake_ai
    ):
        mock_send.return_value = {"success": True, "wa_message_id": "wamid.out-evid"}

        await asyncio.gather(
            process_webhook_payload(payload),
            process_webhook_payload(payload),
        )

    ev_count = db.query(LeadEvidence).filter(LeadEvidence.company_id == "claim_test_co").count()
    assert ev_count <= 1


@pytest.mark.asyncio
async def test_processing_owner_only_mutates_lead(db):
    _seed_company(db)
    payload = _make_payload(ext_id="wamid.lead-owner-001")

    async def fake_ai(*args, **kwargs):
        return ("رد العميل", "internal-msg-lead-owner")

    with patch("routers.webhook.send_whatsapp_message", new_callable=AsyncMock) as mock_send, patch(
        "routers.webhook.get_ai_response", side_effect=fake_ai
    ):
        mock_send.return_value = {"success": True, "wa_message_id": "wamid.out-lead"}

        await asyncio.gather(
            process_webhook_payload(payload),
            process_webhook_payload(payload),
        )

    leads = db.query(Lead).filter(Lead.company_id == "claim_test_co").all()
    assert len(leads) == 1


@pytest.mark.asyncio
async def test_different_external_message_ids_process_independently(db):
    _seed_company(db)
    payload1 = _make_payload(ext_id="wamid.indep-001", body="سؤال 1")
    payload2 = _make_payload(ext_id="wamid.indep-002", body="سؤال 2")

    async def fake_ai(*args, **kwargs):
        return ("رد عادي", "internal-msg-indep")

    with patch("routers.webhook.send_whatsapp_message", new_callable=AsyncMock) as mock_send, patch(
        "routers.webhook.get_ai_response", side_effect=fake_ai
    ) as mock_brain:
        mock_send.return_value = {"success": True, "wa_message_id": "wamid.out-indep"}

        await process_webhook_payload(payload1)
        await process_webhook_payload(payload2)

        assert mock_brain.call_count == 2


@pytest.mark.asyncio
async def test_missing_external_message_id_preserves_current_behavior(db):
    _seed_company(db)
    payload = _make_payload(ext_id=None, body="بدون معرف خاريجي")

    async def fake_ai(*args, **kwargs):
        return ("رد بدون معرف", "internal-msg-no-ext")

    with patch("routers.webhook.send_whatsapp_message", new_callable=AsyncMock) as mock_send, patch(
        "routers.webhook.get_ai_response", side_effect=fake_ai
    ) as mock_brain:
        mock_send.return_value = {"success": True, "wa_message_id": "wamid.out-no-ext"}

        await process_webhook_payload(payload)

        assert mock_brain.call_count == 1


@pytest.mark.asyncio
async def test_company_scope_preserved(db):
    _seed_company(db, company_id="co_scope_1")
    _seed_company(db, company_id="co_scope_2")

    ext_id1 = "wamid.co1-ext-id-001"
    ext_id2 = "wamid.co2-ext-id-002"

    res1, msg1 = acquire_inbound_processing_claim(db, "co_scope_1", "1000000001", ext_id1, "رسالة لشركة 1")
    res2, msg2 = acquire_inbound_processing_claim(db, "co_scope_2", "1000000001", ext_id2, "رسالة لشركة 2")

    assert res1 == ClaimResult.CLAIM_ACQUIRED
    assert res2 == ClaimResult.CLAIM_ACQUIRED


@pytest.mark.asyncio
async def test_legacy_completed_row_remains_safe(db):
    _seed_company(db)
    ext_id = "wamid.legacy-completed-001"

    inc_msg = Message(
        company_id="claim_test_co",
        user_id="201000000001",
        direction="incoming",
        sender="user",
        message="رسالة قديمة",
        wa_message_id=ext_id,
        internal_message_id="inc-legacy-001",
        processing_status="completed",
    )
    out_msg = Message(
        company_id="claim_test_co",
        user_id="201000000001",
        direction="outgoing",
        sender="assistant",
        message="رد قديم",
        internal_message_id="out-legacy-001",
        delivery_status="sent",
    )
    db.add_all([inc_msg, out_msg])
    db.commit()

    payload = _make_payload(ext_id=ext_id)

    with patch("routers.webhook.send_whatsapp_message", new_callable=AsyncMock) as mock_send, patch(
        "routers.webhook.get_ai_response", new_callable=AsyncMock
    ) as mock_brain:
        await process_webhook_payload(payload)
        assert mock_brain.call_count == 0
        assert mock_send.call_count == 0


@pytest.mark.asyncio
async def test_legacy_no_reply_row_uses_explicit_compatibility_contract(db):
    _seed_company(db)
    ext_id = "wamid.legacy-noreply-001"

    inc_msg = Message(
        company_id="claim_test_co",
        user_id="201000000001",
        direction="incoming",
        sender="user",
        message="رسالة قديمة بدون رد",
        wa_message_id=ext_id,
        internal_message_id="inc-legacy-noreply-001",
        processing_status="completed",
    )
    db.add(inc_msg)
    db.commit()

    payload = _make_payload(ext_id=ext_id)

    with patch("routers.webhook.send_whatsapp_message", new_callable=AsyncMock) as mock_send, patch(
        "routers.webhook.get_ai_response", new_callable=AsyncMock
    ) as mock_brain:
        await process_webhook_payload(payload)
        assert mock_brain.call_count == 0


@pytest.mark.asyncio
async def test_first_message_side_effects_preserved_on_claim_acquisition(db):
    _seed_company(db)
    ext_id = "wamid.side-effect-001"
    lead = Lead(
        company_id="claim_test_co",
        phone="201000000001",
        whatsapp_number="1000000001",
        name="Side Effect Lead",
        conversation_count=0,
    )
    db.add(lead)
    db.commit()

    res, msg = acquire_inbound_processing_claim(db, "claim_test_co", "1000000001", ext_id, "رسالة تجربة الآثار الجانبية")
    assert res == ClaimResult.CLAIM_ACQUIRED

    db.refresh(lead)
    assert lead.conversation_count == 1
    assert lead.last_message == "رسالة تجربة الآثار الجانبية"
    assert lead.last_message_sender == "user"
    assert lead.last_contact_date is not None


def test_superseded_attempt_cannot_finalize_or_commit_assistant_and_intelligence(db):
    _seed_company(db)
    user_id = "1000000001"
    ext_id = "wamid.stale-attempt-001"
    lead = Lead(
        company_id="claim_test_co",
        phone=user_id,
        whatsapp_number=user_id,
        name="Stale Attempt Lead",
        interest="initial",
        temperature="cold",
        status="new",
        lead_score=5,
        conversation_state="GREETING",
    )
    db.add(lead)
    db.commit()

    result_1, incoming = acquire_inbound_processing_claim(db, "claim_test_co", user_id, ext_id, "I need a chair")
    assert result_1 == ClaimResult.CLAIM_ACQUIRED
    attempt_1 = incoming.processing_attempts

    assert finalize_inbound_processing_claim(
        db,
        incoming.internal_message_id,
        "failed",
        expected_attempts=attempt_1,
    )

    result_2, reclaimed = acquire_inbound_processing_claim(db, "claim_test_co", user_id, ext_id, "I need a chair")
    assert result_2 == ClaimResult.RETRYABLE_RECLAIMED
    attempt_2 = reclaimed.processing_attempts
    assert attempt_2 == attempt_1 + 1

    assert not finalize_inbound_processing_claim(
        db,
        incoming.internal_message_id,
        "completed",
        expected_attempts=attempt_1,
    )
    db.expire_all()
    current_incoming = db.query(Message).filter(Message.internal_message_id == incoming.internal_message_id).one()
    assert current_incoming.processing_status == "processing"
    assert current_incoming.processing_attempts == attempt_2

    from brain import _thread_finalize_response

    stale_lead_update = {
        "name": "Stale Attempt Lead",
        "phone": user_id,
        "customer_provided_phone": None,
        "interest": "stale premium chair",
        "temperature": "hot",
        "is_hot_deal": True,
        "needs_human_intervention": False,
        "lead_score": 95,
        "status": "ready",
        "ai_summary": "stale summary",
        "last_message_preview": "I need a chair",
        "conversation_state": "CLOSING",
        "escalation_score": 0,
    }
    stale_result = _thread_finalize_response(
        "claim_test_co",
        user_id,
        "stale assistant reply",
        stale_lead_update,
        incoming.internal_message_id,
        attempt_1,
    )
    assert stale_result == (False, None, None)
    db.expire_all()
    refreshed_lead = db.query(Lead).filter(Lead.id == lead.id).one()
    assert refreshed_lead.interest == "initial"
    assert refreshed_lead.temperature == "cold"
    assert refreshed_lead.ai_summary is None
    assert refreshed_lead.conversation_state == "GREETING"
    scoped_outgoing = db.query(Message).filter(
        Message.company_id == "claim_test_co",
        Message.user_id == user_id,
        Message.sender == "assistant",
        Message.direction == "outgoing",
    )
    assert scoped_outgoing.count() == 0

    fresh_lead_update = dict(stale_lead_update)
    fresh_lead_update["interest"] = "fresh ergonomic chair"
    fresh_result = _thread_finalize_response(
        "claim_test_co",
        user_id,
        "fresh assistant reply",
        fresh_lead_update,
        incoming.internal_message_id,
        attempt_2,
    )
    assert fresh_result[1] is not None
    assert finalize_inbound_processing_claim(
        db,
        incoming.internal_message_id,
        "completed",
        expected_attempts=attempt_2,
    )
    db.expire_all()
    refreshed_lead = db.query(Lead).filter(Lead.id == lead.id).one()
    assert refreshed_lead.interest == "fresh ergonomic chair"
    assert refreshed_lead.ai_summary == "stale summary"
    outgoing = scoped_outgoing.all()
    assert len(outgoing) == 1
    assert outgoing[0].message == "fresh assistant reply"


@pytest.mark.asyncio
async def test_unrelated_integrity_error_is_not_swallowed(db):
    _seed_company(db)
    from sqlalchemy.exc import IntegrityError

    with patch.object(db, "flush", side_effect=IntegrityError("stmt", "params", Exception("Foreign key violation"))):
        with pytest.raises(IntegrityError):
            acquire_inbound_processing_claim(db, "claim_test_co", "1000000001", "wamid.unrelated-err-001", "test")
