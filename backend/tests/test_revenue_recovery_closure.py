import json
import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from jose import jwt

from database import CommercialEvent, Company, Lead, Message, SystemEvent, hash_api_key
from services.follow_up_service import (
    cancel_for_terminal_lead,
    complete_reply_required_tasks,
    create_follow_up,
    list_follow_ups,
    supersede_for_new_customer_turn,
    sync_follow_ups_from_attention,
    transition_follow_up,
)
from services.owner_attention_projection_service import get_commercial_queue
from services.pilot_telemetry_service import record_client_product_events, record_pilot_event
from services.recovery_impact_service import build_recovery_impact
from services.trusted_outcome_contract import (
    TrustedOutcome,
    UntrustedOutcomeError,
    validate_trusted_outcome,
)


def _token(company_id):
    return jwt.encode(
        {"company_id": company_id, "role": "tenant", "token_type": "access"},
        "super-secret-test-key-32-chars-long",
        algorithm="HS256",
    )


def _company(db, prefix):
    company_id = f"{prefix}_{uuid.uuid4().hex[:8]}"
    row = Company(
        company_id=company_id,
        company_name=company_id,
        email=f"{company_id}@example.com",
        password="hashed",
        api_key_hash=hash_api_key(f"{company_id}-key"),
        plan="PRO",
    )
    db.add(row)
    db.commit()
    return row


def _lead(db, company_id, *, paused=False, channel="VELOR_WEB_CHAT", is_test=False):
    identifier = f"wc_v_{uuid.uuid4().hex[:10]}"
    row = Lead(
        company_id=company_id,
        name="Recovery Customer",
        phone=None,
        channel_type=channel,
        external_customer_id=identifier,
        is_paused=paused,
        is_test=is_test,
        stage="Information Gathering",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _incoming(db, company_id, lead, internal_id=None):
    row = Message(
        company_id=company_id,
        user_id=lead.external_customer_id,
        sender="user",
        direction="incoming",
        message="Please help me with the next step",
        internal_message_id=internal_id or f"msg-{uuid.uuid4().hex}",
        public_message_id=f"pub-{uuid.uuid4().hex}",
        delivery_status="received",
        processing_status="completed",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_follow_up_lifecycle_is_idempotent_tenant_scoped_and_policy_driven(client, db):
    company_a = _company(db, "follow_a")
    company_b = _company(db, "follow_b")
    company_a_id = company_a.company_id
    company_b_id = company_b.company_id
    lead_a = _lead(db, company_a_id)
    lead_b = _lead(db, company_b_id)
    source_a = _incoming(db, company_a_id, lead_a, "follow-source-a")
    source_b = _incoming(db, company_b_id, lead_b, "follow-source-b")
    lead_a_id = lead_a.id
    lead_b_id = lead_b.id
    source_a_internal_id = source_a.internal_message_id
    source_b_internal_id = source_b.internal_message_id
    due = datetime.now(timezone.utc) + timedelta(hours=2)

    task_a = create_follow_up(
        db,
        company_id=company_a_id,
        lead_id=lead_a_id,
        source_type="owner_attention_projection",
        source_identifier=source_a_internal_id,
        source_message_internal_id=source_a_internal_id,
        reason_code="HUMAN_TAKEOVER_ACTIVE",
        due_at=due,
    )
    duplicate = create_follow_up(
        db,
        company_id=company_a_id,
        lead_id=lead_a_id,
        source_type="owner_attention_projection",
        source_identifier=source_a_internal_id,
        source_message_internal_id=source_a_internal_id,
        reason_code="HUMAN_TAKEOVER_ACTIVE",
        due_at=due,
    )
    create_follow_up(
        db,
        company_id=company_b_id,
        lead_id=lead_b_id,
        source_type="owner_attention_projection",
        source_identifier=source_b_internal_id,
        source_message_internal_id=source_b_internal_id,
        reason_code="HUMAN_TAKEOVER_ACTIVE",
        due_at=due,
    )

    assert duplicate.id == task_a.id
    response = client.get(
        "/api/v1/operations/follow-ups",
        cookies={"access_token": _token(company_a_id)},
    )
    assert response.status_code == 200
    assert {row["lead_id"] for row in response.json()["follow_ups"]} == {lead_a_id}

    snoozed = transition_follow_up(
        db,
        company_id=company_a_id,
        task_id=task_a.id,
        target_status="snoozed",
        snoozed_until=datetime.now(timezone.utc) + timedelta(days=1),
    )
    assert snoozed.status == "snoozed"

    lead_a = db.query(Lead).filter(Lead.id == lead_a_id, Lead.company_id == company_a_id).one()
    new_turn = _incoming(db, company_a_id, lead_a, "follow-source-new")
    new_turn_id = new_turn.id
    new_turn_internal_id = new_turn.internal_message_id
    assert supersede_for_new_customer_turn(db, new_turn, commit=True) == 1
    assert list_follow_ups(db, company_a_id, statuses={"superseded"})[0].status == "superseded"

    completed_task = create_follow_up(
        db,
        company_id=company_a_id,
        lead_id=lead_a_id,
        source_type="owner_action",
        source_identifier="complete-via-api",
        reason_code="OWNER_PLANNED_FOLLOW_UP",
        due_at=due,
    )
    completed_response = client.post(
        f"/api/v1/operations/follow-ups/{completed_task.id}/complete",
        cookies={"access_token": _token(company_a_id)},
    )
    assert completed_response.status_code == 200
    assert completed_response.json()["follow_up"]["completed_at"]

    dismissed_task = create_follow_up(
        db,
        company_id=company_a_id,
        lead_id=lead_a_id,
        source_type="owner_action",
        source_identifier="dismiss-via-api",
        reason_code="OWNER_PLANNED_FOLLOW_UP",
        due_at=due,
    )
    cross_tenant_response = client.post(
        f"/api/v1/operations/follow-ups/{dismissed_task.id}/dismiss",
        cookies={"access_token": _token(company_b_id)},
    )
    dismissed_response = client.post(
        f"/api/v1/operations/follow-ups/{dismissed_task.id}/dismiss",
        cookies={"access_token": _token(company_a_id)},
    )
    assert cross_tenant_response.status_code == 404
    assert dismissed_response.status_code == 200
    assert dismissed_response.json()["follow_up"]["dismissed_at"]

    lead_a = db.query(Lead).filter(Lead.id == lead_a_id, Lead.company_id == company_a_id).one()
    reply_task = create_follow_up(
        db,
        company_id=company_a_id,
        lead_id=lead_a_id,
        source_type="owner_attention_projection",
        source_identifier=new_turn_internal_id,
        source_message_internal_id=new_turn_internal_id,
        reason_code="HUMAN_TAKEOVER_ACTIVE",
        due_at=due,
    )
    outbound = Message(
        company_id=company_a_id,
        user_id=lead_a.external_customer_id,
        sender="owner",
        direction="outgoing",
        message="I can help with that next step.",
        internal_message_id="follow-owner-reply",
        delivery_status="sent",
        in_reply_to_message_id=new_turn_id,
    )
    db.add(outbound)
    db.flush()
    assert complete_reply_required_tasks(
        db,
        company_id=company_a_id,
        lead=lead_a,
        outbound_message=outbound,
        source_message_internal_id=new_turn_internal_id,
        commit=True,
    ) == 1
    assert reply_task.id in {
        task.id for task in list_follow_ups(db, company_a_id, statuses={"completed"}, lead_id=lead_a_id)
    }

    reactivation_task = create_follow_up(
        db,
        company_id=company_a_id,
        lead_id=lead_a_id,
        source_type="owner_action",
        source_identifier="snooze-reactivation",
        reason_code="OWNER_PLANNED_FOLLOW_UP",
        due_at=datetime.now(timezone.utc) - timedelta(hours=2),
    )
    transition_follow_up(
        db,
        company_id=company_a_id,
        task_id=reactivation_task.id,
        target_status="snoozed",
        snoozed_until=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    reactivation_task.snoozed_until = datetime.now(timezone.utc) - timedelta(seconds=1)
    reactivation_task.due_at = datetime.now(timezone.utc) - timedelta(hours=2)
    db.commit()
    due_tasks = list_follow_ups(db, company_a_id, due_only=True)
    assert reactivation_task.id in {task.id for task in due_tasks}
    assert db.query(SystemEvent).filter(
        SystemEvent.company_id == company_a_id,
        SystemEvent.event_type == "pilot.follow_up_reactivated",
    ).count() == 1

    terminal_task = create_follow_up(
        db,
        company_id=company_a_id,
        lead_id=lead_a_id,
        source_type="commercial_event",
        source_identifier="terminal-source",
        reason_code="PURCHASE_COMMITMENT",
        due_at=due,
    )
    assert terminal_task is not None
    lead_a.stage = "Won"
    db.commit()
    assert cancel_for_terminal_lead(db, company_id=company_a_id, lead_id=lead_a_id, commit=True) == 2
    assert {task.id for task in list_follow_ups(db, company_a_id, statuses={"cancelled"})} == {
        reactivation_task.id,
        terminal_task.id,
    }

    gap_lead = _lead(db, company_a_id)
    gap_source = _incoming(db, company_a_id, gap_lead, "knowledge-gap-source")
    gap_hash = hashlib.sha256(b"knowledge-gap-source").hexdigest()
    db.add(CommercialEvent(
        company_id=company_a_id,
        lead_id=gap_lead.id,
        message_id=gap_source.id,
        source_message_internal_id=gap_source.internal_message_id,
        channel="VELOR_WEB_CHAT",
        event_type="KNOWLEDGE_GAP_HIT",
        source_text="A source-linked unresolved question",
        evidence_json='{"knowledge_topic":"shipping_policy"}',
        provenance="deterministic_v1",
        event_hash=gap_hash,
    ))
    db.commit()
    assert sync_follow_ups_from_attention(db, company_a_id) >= 1
    gap_task = next(task for task in list_follow_ups(db, company_a_id) if task.lead_id == gap_lead.id)
    transition_follow_up(
        db,
        company_id=company_a_id,
        task_id=gap_task.id,
        target_status="completed",
    )
    assert db.query(SystemEvent).filter(
        SystemEvent.company_id == company_a_id,
        SystemEvent.event_type == "pilot.knowledge_gap_resolved",
    ).count() == 1


def test_product_telemetry_is_source_validated_idempotent_and_financially_honest(db):
    company_a = _company(db, "telemetry_a")
    company_b = _company(db, "telemetry_b")
    lead_a = _lead(db, company_a.company_id, paused=True)
    lead_b = _lead(db, company_b.company_id, paused=True)
    _incoming(db, company_a.company_id, lead_a)
    _incoming(db, company_b.company_id, lead_b)
    item_a = get_commercial_queue(db, company_a.company_id, limit=10)["items"][0]
    item_b = get_commercial_queue(db, company_b.company_id, limit=10)["items"][0]

    shown = {
        "event_name": "opportunity_shown",
        "client_event_id": "render-a-1",
        "metadata": {
            "lead_id": lead_a.id,
            "queue_item_id": item_a["queue_item_id"],
            "surface": "dashboard",
        },
    }
    first = record_client_product_events(db, company_id=company_a.company_id, events=[shown])[0]
    duplicate = record_client_product_events(db, company_id=company_a.company_id, events=[shown])[0]
    assert duplicate.id == first.id
    assert db.query(SystemEvent).filter(
        SystemEvent.company_id == company_a.company_id,
        SystemEvent.event_type == "pilot.opportunity_shown",
    ).count() == 1

    forged = {
        **shown,
        "client_event_id": "forged-cross-tenant",
        "metadata": {"lead_id": lead_a.id, "queue_item_id": item_b["queue_item_id"]},
    }
    with pytest.raises(ValueError, match="invalid_telemetry_queue_item"):
        record_client_product_events(db, company_id=company_a.company_id, events=[forged])

    for event_name in ("opportunity_opened", "owner_action_started"):
        record_client_product_events(db, company_id=company_a.company_id, events=[{
            "event_name": event_name,
            "client_event_id": f"{event_name}-a-1",
            "metadata": {
                "lead_id": lead_a.id,
                "queue_item_id": item_a["queue_item_id"],
                "surface": "workspace",
            },
        }])

    impact = build_recovery_impact(db, company_a.company_id, days=30, channel="all")
    assert impact["metrics"]["unique_active_opportunities_shown"]["value"] == 1
    assert impact["metrics"]["unique_opportunities_opened"]["value"] == 1
    assert impact["metrics"]["owner_actions_started"]["value"] == 1
    assert impact["outcome_status"] == "not_connected"
    assert all(row["value"] is None and row["status"] == "not_connected" for row in impact["financial_outcomes"].values())


def test_recovery_impact_filters_and_persisted_operational_metrics_are_exact(client, db):
    company = _company(db, "impact_exact")
    other = _company(db, "impact_other")
    web_lead = _lead(db, company.company_id, channel="VELOR_WEB_CHAT")
    whatsapp_lead = _lead(db, company.company_id, channel="WHATSAPP")
    test_lead = _lead(db, company.company_id, channel="VELOR_WEB_CHAT", is_test=True)
    other_lead = _lead(db, other.company_id, channel="VELOR_WEB_CHAT")
    now = datetime.now(timezone.utc)

    source_fast = _incoming(db, company.company_id, web_lead, "impact-source-fast")
    source_slow = _incoming(db, company.company_id, web_lead, "impact-source-slow")
    source_fast.created_at = now - timedelta(minutes=40)
    source_slow.created_at = now - timedelta(minutes=35)
    reply_fast = Message(
        company_id=company.company_id,
        user_id=web_lead.external_customer_id,
        sender="owner",
        direction="outgoing",
        message="Linked reply one",
        internal_message_id="impact-reply-fast",
        delivery_status="sent",
        in_reply_to_message_id=source_fast.id,
        created_at=now - timedelta(minutes=30),
    )
    reply_slow = Message(
        company_id=company.company_id,
        user_id=web_lead.external_customer_id,
        sender="owner",
        direction="outgoing",
        message="Linked reply two",
        internal_message_id="impact-reply-slow",
        delivery_status="sent",
        in_reply_to_message_id=source_slow.id,
        created_at=now - timedelta(minutes=5),
    )
    db.add_all([reply_fast, reply_slow])
    db.commit()

    shown = record_pilot_event(
        db,
        event_name="opportunity_shown",
        company_id=company.company_id,
        actor_type="owner",
        entity_id="impact-web-queue",
        source="owner_console",
        idempotency_key="impact-web-shown",
        metadata={"lead_id": web_lead.id, "queue_item_id": "impact-web-queue", "surface": "dashboard"},
    )
    opened = record_pilot_event(
        db,
        event_name="opportunity_opened",
        company_id=company.company_id,
        actor_type="owner",
        entity_id="impact-web-queue",
        source="owner_console",
        idempotency_key="impact-web-opened",
        metadata={"lead_id": web_lead.id, "queue_item_id": "impact-web-queue", "surface": "dashboard"},
    )
    action = record_pilot_event(
        db,
        event_name="owner_action_started",
        company_id=company.company_id,
        actor_type="owner",
        entity_id="impact-web-queue",
        source="owner_console",
        idempotency_key="impact-web-action",
        metadata={"lead_id": web_lead.id, "queue_item_id": "impact-web-queue", "surface": "workspace"},
    )
    shown.created_at = now - timedelta(hours=3)
    opened.created_at = now - timedelta(hours=2, minutes=30)
    action.created_at = now - timedelta(hours=2)

    whatsapp_shown = record_pilot_event(
        db,
        event_name="opportunity_shown",
        company_id=company.company_id,
        actor_type="owner",
        entity_id="impact-wa-queue",
        source="owner_console",
        idempotency_key="impact-wa-shown",
        metadata={"lead_id": whatsapp_lead.id, "queue_item_id": "impact-wa-queue", "surface": "analytics"},
    )
    whatsapp_shown.created_at = now - timedelta(hours=1)
    old_shown = record_pilot_event(
        db,
        event_name="opportunity_shown",
        company_id=company.company_id,
        actor_type="owner",
        entity_id="impact-old-queue",
        source="owner_console",
        idempotency_key="impact-old-shown",
        metadata={"lead_id": web_lead.id, "queue_item_id": "impact-old-queue", "surface": "dashboard"},
    )
    old_shown.created_at = now - timedelta(days=60)
    for excluded_company, excluded_lead, suffix in (
        (company.company_id, test_lead, "test"),
        (other.company_id, other_lead, "tenant"),
    ):
        record_pilot_event(
            db,
            event_name="opportunity_shown",
            company_id=excluded_company,
            actor_type="owner",
            entity_id=f"impact-{suffix}-queue",
            source="owner_console",
            idempotency_key=f"impact-{suffix}-shown",
            metadata={"lead_id": excluded_lead.id, "queue_item_id": f"impact-{suffix}-queue"},
        )
    db.commit()

    on_time = create_follow_up(
        db,
        company_id=company.company_id,
        lead_id=web_lead.id,
        source_type="owner_action",
        source_identifier="impact-on-time",
        reason_code="OWNER_PLANNED_FOLLOW_UP",
        due_at=now + timedelta(hours=2),
    )
    transition_follow_up(
        db,
        company_id=company.company_id,
        task_id=on_time.id,
        target_status="completed",
    )
    create_follow_up(
        db,
        company_id=company.company_id,
        lead_id=web_lead.id,
        source_type="owner_action",
        source_identifier="impact-overdue",
        reason_code="OWNER_PLANNED_FOLLOW_UP",
        due_at=now - timedelta(hours=1),
    )

    for index, (event_name, edited) in enumerate((
        ("suggestion_generated", None),
        ("suggestion_inserted", None),
        ("suggestion_sent", False),
        ("suggestion_sent", True),
        ("suggestion_dismissed", None),
        ("suggestion_stale_blocked", None),
    )):
        metadata = {"lead_id": web_lead.id, "suggestion_id": 1000 + index}
        if edited is not None:
            metadata["edited"] = edited
        record_pilot_event(
            db,
            event_name=event_name,
            company_id=company.company_id,
            actor_type="owner",
            entity_id=f"impact-suggestion-{index}",
            source="test_fixture",
            idempotency_key=f"impact-suggestion-{index}",
            metadata=metadata,
        )

    db.add(CommercialEvent(
        company_id=company.company_id,
        lead_id=web_lead.id,
        source_message_internal_id=source_slow.internal_message_id,
        channel="VELOR_WEB_CHAT",
        event_type="PURCHASE_COMMITMENT",
        source_text="Persisted purchase commitment",
        evidence_json="{}",
        provenance="deterministic_v1",
        event_hash="impact-progress-after-action",
        observed_at=now - timedelta(hours=1),
    ))
    for index in range(2):
        db.add(CommercialEvent(
            company_id=company.company_id,
            lead_id=web_lead.id,
            source_message_internal_id=source_slow.internal_message_id,
            channel="VELOR_WEB_CHAT",
            event_type="KNOWLEDGE_GAP_HIT",
            source_text="Persisted knowledge gap",
            evidence_json="{}",
            provenance="deterministic_v1",
            event_hash=f"impact-gap-{index}",
            observed_at=now - timedelta(minutes=20 - index),
        ))
    db.commit()

    response = client.get(
        "/api/v1/operations/recovery-impact?days=30&channel=web",
        cookies={"access_token": _token(company.company_id)},
    )
    assert response.status_code == 200
    impact = response.json()["data"]
    metrics = {name: value["value"] for name, value in impact["metrics"].items()}
    assert impact["filters_applied"] == {"days": 30, "channel": "web"}
    assert metrics["unique_active_opportunities_shown"] == 1
    assert metrics["unique_opportunities_opened"] == 1
    assert metrics["owner_actions_started"] == 1
    assert metrics["priority_signals_handled_within_24_hours"] == 1
    assert metrics["median_owner_response_time_seconds"] == 1200
    assert metrics["follow_ups_created"] == 2
    assert metrics["follow_ups_completed"] == 1
    assert metrics["follow_ups_completed_on_time"] == 1
    assert metrics["overdue_follow_ups"] == 1
    assert metrics["suggestion_generations"] == 1
    assert metrics["suggestion_insertions"] == 1
    assert metrics["suggestion_sends"] == 2
    assert metrics["suggestion_sends_without_edits"] == 1
    assert metrics["suggestion_sends_with_edits"] == 1
    assert metrics["suggestion_dismissals"] == 1
    assert metrics["stale_suggestion_blocks"] == 1
    assert metrics["conversations_with_subsequent_commercial_progress"] == 1
    assert metrics["unresolved_repeated_knowledge_gaps"] == 1
    assert "not attributed causally" in impact["causality_note"].lower()
    assert all(row["value"] is None for row in impact["financial_outcomes"].values())

    all_channels = build_recovery_impact(db, company.company_id, days=30, channel="all")
    assert all_channels["metrics"]["unique_active_opportunities_shown"]["value"] == 2


def test_legacy_opportunity_route_never_fabricates_money(client, db):
    company = _company(db, "legacy_truth")
    lead = _lead(db, company.company_id, paused=True)
    _incoming(db, company.company_id, lead)

    result = client.get("/api/engine/opportunity", cookies={"access_token": _token(company.company_id)})
    override = client.post(
        "/api/engine/override",
        json={"lead_id": lead.id, "opportunity_value": 5000},
        cookies={"access_token": _token(company.company_id)},
    )

    assert result.status_code == 200
    payload = result.json()
    assert payload["money_left_on_table"] is None
    assert payload["recovered_revenue"] is None
    assert payload["financial_outcomes"]["status"] == "not_connected"
    assert override.status_code == 422


def test_trusted_outcome_seam_rejects_chat_and_unverified_provider_claims():
    occurred_at = datetime.now(timezone.utc) - timedelta(minutes=2)
    received_at = occurred_at + timedelta(minutes=1)
    verified_at = received_at + timedelta(seconds=30)
    outcome = TrustedOutcome(
        company_id="trusted-company",
        lead_id=1,
        lead_binding_method="provider_customer_id",
        outcome_type="PAID",
        provider="future-payment-provider",
        provider_event_id="evt-1",
        provider_object_id="obj-1",
        idempotency_key="trusted-company:future-payment-provider:evt-1",
        occurred_at=occurred_at,
        received_at=received_at,
        verified_at=verified_at,
        signature_verified=True,
        raw_payload_hash="a" * 64,
        provenance="provider_verified:future-payment-provider",
        amount=Decimal("10.00"),
        currency="EGP",
        payment_id="pay-1",
    )
    with pytest.raises(UntrustedOutcomeError, match="conversation evidence"):
        validate_trusted_outcome(outcome, adapter_signature_verified=True, provenance="chat")
    with pytest.raises(ValueError, match="trusted_provider_outcome_required"):
        record_pilot_event(
            None,
            event_name="paid",
            company_id="trusted-company",
            actor_type="system",
            entity_id="pay-1",
            source="chat",
        )
    with pytest.raises(UntrustedOutcomeError, match="authenticity"):
        validate_trusted_outcome(outcome, adapter_signature_verified=False, provenance="provider_verified:future-payment-provider")
    assert validate_trusted_outcome(
        outcome,
        adapter_signature_verified=True,
        provenance="provider_verified:future-payment-provider",
    ) is outcome

    invalid_refund = TrustedOutcome(
        **{
            **outcome.__dict__,
            "refund_amount": Decimal("2.00"),
            "refund_currency": "EGP",
            "reversal_of_provider_event_id": None,
        }
    )
    with pytest.raises(UntrustedOutcomeError, match="reversal reference"):
        validate_trusted_outcome(
            invalid_refund,
            adapter_signature_verified=True,
            provenance="provider_verified:future-payment-provider",
        )
