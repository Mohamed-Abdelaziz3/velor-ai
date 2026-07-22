import json
import uuid
from datetime import datetime, timedelta, timezone

from jose import jwt
from sqlalchemy import event

from database import CommercialEvent, Company, Lead, LeadEvidence, Message, hash_api_key
from services.follow_up_service import create_follow_up
from services.owner_attention_projection_service import PROJECTION_CLASSES, get_commercial_queue, get_owner_attention_projection


def _token(company_id):
    return jwt.encode(
        {"company_id": company_id, "role": "tenant", "token_type": "access"},
        "super-secret-test-key-32-chars-long",
        algorithm="HS256",
    )


def _company(db, company_id=None, auto_reply=True):
    company_id = company_id or f"attention_{uuid.uuid4().hex[:8]}"
    company = Company(
        company_id=company_id,
        company_name=f"{company_id} Company",
        email=f"{company_id}@example.com",
        password="hashed",
        api_key_hash=hash_api_key(f"{company_id}-api-key"),
        plan="PRO",
        bot_auto_reply_enabled=auto_reply,
    )
    db.add(company)
    db.commit()
    return company


def _lead(db, company_id, name="Customer", user_id=None, paused=False, sales_state=None, is_test=False):
    user_id = user_id or f"wc_v_{uuid.uuid4().hex[:10]}"
    lead = Lead(
        company_id=company_id,
        name=name,
        phone=None,
        channel_type="VELOR_WEB_CHAT",
        external_customer_id=user_id,
        is_paused=paused,
        is_test=is_test,
        stage="Information Gathering",
        sales_state_snapshot=json.dumps(sales_state or {}),
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead


def _message(db, company_id, lead, text, sender="user", minutes_ago=0, status="completed"):
    created_at = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    msg = Message(
        company_id=company_id,
        user_id=lead.external_customer_id,
        sender=sender,
        direction="incoming" if sender == "user" else "outgoing",
        message=text,
        internal_message_id=f"msg-{uuid.uuid4().hex}",
        public_message_id=f"pub-{uuid.uuid4().hex}",
        delivery_status="received" if sender == "user" else "sent",
        processing_status=status,
        created_at=created_at,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


def _evidence(db, company_id, lead, message, evidence_type, normalized_value=None):
    row = LeadEvidence(
        company_id=company_id,
        lead_id=lead.id,
        message_id=message.id,
        message_internal_id=message.internal_message_id,
        evidence_type=evidence_type,
        source="message",
        source_text=message.message,
        normalized_value=normalized_value,
        confidence=0.92,
        metadata_json="{}",
        evidence_hash=f"{evidence_type}-{uuid.uuid4().hex}",
        created_at=message.created_at,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _classes(payload):
    return {item["projection_class"] for item in payload["items"]}


def _assert_semantic_projection(item):
    for key in ["what", "why", "what_changed", "what_next", "reason_code", "freshness", "evidence"]:
        assert item.get(key) not in (None, "", [])
    assert item["freshness"]["label"] in {"fresh", "recent", "stale"}
    assert item["freshness"]["age_seconds"] >= 0
    assert item["evidence"][0]["source_message_internal_id"]


def test_attention_endpoint_emits_only_launch_projection_classes(client, db):
    company = _company(db, "attention_endpoint")
    lead = _lead(db, company.company_id, paused=True)
    _message(db, company.company_id, lead, "Can someone answer?", minutes_ago=2)

    res = client.get("/api/engine/attention?limit=10", cookies={"access_token": _token(company.company_id)})
    data = res.json()

    assert res.status_code == 200
    assert data["success"] is True
    assert set(data["classes"]) == PROJECTION_CLASSES
    assert _classes(data) == {"WAITING_ON_US"}
    assert data["items"][0]["reason_code"] == "HUMAN_TAKEOVER_ACTIVE"
    _assert_semantic_projection(data["items"][0])


def test_waiting_on_us_requires_unanswered_customer_message(db):
    company = _company(db, "attention_waiting_answered")
    lead = _lead(db, company.company_id, paused=True)
    _message(db, company.company_id, lead, "Are you there?", sender="user", minutes_ago=3)
    _message(db, company.company_id, lead, "Yes, I am here.", sender="owner", minutes_ago=1)

    data = get_owner_attention_projection(db, company.company_id, limit=10)

    assert "WAITING_ON_US" not in _classes(data)


def test_waiting_reason_codes_cover_disabled_failed_and_deterministically_stuck_processing(db):
    disabled_company = _company(db, "attention_auto_disabled", auto_reply=False)
    disabled_lead = _lead(db, disabled_company.company_id)
    _message(db, disabled_company.company_id, disabled_lead, "Need a manual answer", minutes_ago=3)

    failed_company = _company(db, "attention_processing_failed")
    failed_lead = _lead(db, failed_company.company_id)
    _message(db, failed_company.company_id, failed_lead, "The processor failed", minutes_ago=3, status="failed")

    stuck_company = _company(db, "attention_processing_stuck")
    stuck_lead = _lead(db, stuck_company.company_id)
    fresh_lead = _lead(db, stuck_company.company_id)
    _message(db, stuck_company.company_id, stuck_lead, "Still processing", minutes_ago=3, status="processing")
    _message(db, stuck_company.company_id, fresh_lead, "Just started", minutes_ago=0, status="processing")

    assert get_owner_attention_projection(db, disabled_company.company_id)["items"][0]["reason_code"] == "AUTO_REPLY_DISABLED"
    assert get_owner_attention_projection(db, failed_company.company_id)["items"][0]["reason_code"] == "PROCESSING_FAILURE"
    stuck_items = get_owner_attention_projection(db, stuck_company.company_id)["items"]
    assert {(item["lead_id"], item["reason_code"]) for item in stuck_items} == {
        (stuck_lead.id, "PROCESSING_STUCK")
    }


def test_purchase_movement_reasons_remain_distinct_and_never_claim_an_order(db):
    company = _company(db, "attention_purchase_steps")
    expected = {
        "PURCHASE_EXECUTION_REQUEST": "Please create the order now",
        "PURCHASE_COMMITMENT": "I will take this product",
        "PURCHASE_INTENT_EXPRESSED": "I want to buy it",
    }
    leads = {}
    for index, (event_type, text) in enumerate(expected.items()):
        lead = _lead(db, company.company_id, name=event_type)
        message = _message(db, company.company_id, lead, text)
        db.add(CommercialEvent(
            company_id=company.company_id,
            lead_id=lead.id,
            message_id=message.id,
            source_message_internal_id=message.internal_message_id,
            channel="VELOR_WEB_CHAT",
            event_type=event_type,
            source_text=text,
            evidence_json="{}",
            provenance="deterministic_v1",
            event_hash=f"purchase-step-{index}",
            observed_at=message.created_at,
        ))
        leads[lead.id] = event_type
    db.commit()

    items = get_owner_attention_projection(db, company.company_id, limit=100)["items"]
    ready = {item["lead_id"]: item for item in items if item["projection_class"] == "READY_TO_CLOSE"}
    assert {lead_id: item["reason_code"] for lead_id, item in ready.items()} == leads
    serialized = json.dumps(ready)
    assert "CONFIRMED_ORDER" not in serialized
    assert "PAID" not in serialized


def test_compact_queue_is_stable_one_per_lead_and_includes_durable_due_follow_up(db):
    company = _company(db, "attention_compact_queue")
    waiting_lead = _lead(db, company.company_id, paused=True)
    waiting_source = _message(db, company.company_id, waiting_lead, "Owner help needed", minutes_ago=3)
    create_follow_up(
        db,
        company_id=company.company_id,
        lead_id=waiting_lead.id,
        source_type="owner_attention_projection",
        source_identifier=waiting_source.internal_message_id,
        source_message_internal_id=waiting_source.internal_message_id,
        reason_code="HUMAN_TAKEOVER_ACTIVE",
        due_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )

    follow_up_lead = _lead(db, company.company_id)
    follow_up_source = _message(db, company.company_id, follow_up_lead, "Please follow up", minutes_ago=5)
    _message(db, company.company_id, follow_up_lead, "I will follow up.", sender="owner", minutes_ago=4)
    follow_up = create_follow_up(
        db,
        company_id=company.company_id,
        lead_id=follow_up_lead.id,
        source_type="owner_action",
        source_identifier="explicit-owner-follow-up",
        source_message_internal_id=follow_up_source.internal_message_id,
        reason_code="OWNER_PLANNED_FOLLOW_UP",
        due_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )

    first = get_commercial_queue(db, company.company_id, limit=10)["items"]
    second = get_commercial_queue(db, company.company_id, limit=10)["items"]
    assert len(first) == 2
    assert len({item["lead_id"] for item in first}) == 2
    assert [item["queue_item_id"] for item in first] == [item["queue_item_id"] for item in second]
    by_lead = {item["lead_id"]: item for item in first}
    assert by_lead[waiting_lead.id]["category"] == "WAITING_ON_US"
    assert by_lead[follow_up_lead.id]["category"] == "FOLLOW_UP_DUE"
    assert by_lead[follow_up_lead.id]["follow_up_task_id"] == follow_up.id
    assert all(item["workspace_path"] == f"/inbox/{item['lead_id']}" for item in first)


def test_attention_ready_objection_and_regressing_are_evidence_bound(db):
    company = _company(db, "attention_classes")
    ready = _lead(
        db,
        company.company_id,
        name="Ready Lead",
        sales_state={"primary_state": "READY_TO_BUY", "buyer_intents": ["PAYMENT_INQUIRY"]},
    )
    objection = _lead(db, company.company_id, name="Objection Lead")
    regressing = _lead(db, company.company_id, name="Regressing Lead", sales_state={"momentum": "REGRESSING"})

    ready_msg = _message(db, company.company_id, ready, "I want to start today")
    objection_msg = _message(db, company.company_id, objection, "This is too expensive")
    regressing_msg = _message(db, company.company_id, regressing, "Maybe later")
    _evidence(db, company.company_id, ready, ready_msg, "start_intent")
    _evidence(db, company.company_id, objection, objection_msg, "objection_price")
    _evidence(db, company.company_id, regressing, regressing_msg, "hesitation")

    data = get_owner_attention_projection(db, company.company_id, limit=10)
    by_class = {item["projection_class"]: item for item in data["items"]}
    payload = json.dumps(data)

    assert {"READY_TO_CLOSE", "STUCK_ON_OBJECTION", "REGRESSING"}.issubset(by_class)
    assert by_class["READY_TO_CLOSE"]["reason_code"] == "PAYMENT_INQUIRY"
    assert by_class["STUCK_ON_OBJECTION"]["reason_code"] == "PRICE_OBJECTION_PRESENT"
    assert by_class["REGRESSING"]["reason_code"] in {"REGRESSING_MOMENTUM", "HESITATION_SIGNAL"}
    for cls in ["READY_TO_CLOSE", "STUCK_ON_OBJECTION", "REGRESSING"]:
        _assert_semantic_projection(by_class[cls])
    assert "expected_revenue" not in payload
    assert "deal_value" not in payload


def test_attention_negative_cases_do_not_project_without_real_evidence(db):
    company = _company(db, "attention_negative_cases")

    plain = _lead(db, company.company_id, name="Plain Lead")
    _message(db, company.company_id, plain, "I am browsing chairs", sender="user", minutes_ago=3)
    _message(db, company.company_id, plain, "Happy to help.", sender="assistant", minutes_ago=2)

    fake_ready = _lead(db, company.company_id, name="Fake Ready", sales_state={"primary_state": "BROWSING"})
    fake_ready_msg = _message(db, company.company_id, fake_ready, "I am just looking", sender="user", minutes_ago=3)
    _evidence(db, company.company_id, fake_ready, fake_ready_msg, "product_mention")
    _message(db, company.company_id, fake_ready, "Here is the catalog.", sender="assistant", minutes_ago=2)

    fake_regressing = _lead(db, company.company_id, name="Fake Regressing", sales_state={"momentum": "STABLE"})
    fake_regressing_msg = _message(db, company.company_id, fake_regressing, "Maybe this chair works", sender="user", minutes_ago=3)
    _evidence(db, company.company_id, fake_regressing, fake_regressing_msg, "product_mention")
    _message(db, company.company_id, fake_regressing, "This one may fit.", sender="assistant", minutes_ago=2)

    data = get_owner_attention_projection(db, company.company_id, limit=10)

    assert data["items"] == []
    assert data["message"] == "No launch attention items have enough evidence right now."


def test_attention_projection_excludes_test_leads(db):
    company = _company(db, "attention_test_lead_exclusion")
    test_lead = _lead(
        db,
        company.company_id,
        name="Synthetic customer",
        paused=True,
        is_test=True,
        sales_state={"primary_state": "READY_TO_BUY", "buyer_intents": ["PAYMENT_INQUIRY"]},
    )
    message = _message(db, company.company_id, test_lead, "I want to buy now")
    _evidence(db, company.company_id, test_lead, message, "start_intent")

    data = get_owner_attention_projection(db, company.company_id, limit=10)

    assert data["items"] == []
    assert "Synthetic customer" not in json.dumps(data)


def test_attention_queue_query_count_is_constant_and_tenant_scoped(db):
    company = _company(db, "attention_query_bound")
    other = _company(db, "attention_query_other")

    for index in range(12):
        lead = _lead(
            db,
            company.company_id,
            name=f"Bounded {index}",
            user_id=f"wc_v_bound_{index}",
            paused=True,
        )
        _message(db, company.company_id, lead, f"Need help {index}", minutes_ago=index)

    # A colliding channel identifier in another tenant must never enter this
    # company's prefetch maps or its queue payload.
    foreign = _lead(
        db,
        other.company_id,
        name="FOREIGN_PRIVATE_CUSTOMER",
        user_id="wc_v_bound_0",
        paused=True,
    )
    _message(db, other.company_id, foreign, "FOREIGN_PRIVATE_MESSAGE")

    statement_count = 0

    def count_statement(*_args):
        nonlocal statement_count
        statement_count += 1

    event.listen(db.bind, "before_cursor_execute", count_statement)
    try:
        data = get_owner_attention_projection(db, company.company_id, limit=10)
    finally:
        event.remove(db.bind, "before_cursor_execute", count_statement)

    serialized = json.dumps(data)
    assert statement_count <= 8
    assert len(data["items"]) == 10
    assert "FOREIGN_PRIVATE_CUSTOMER" not in serialized
    assert "FOREIGN_PRIVATE_MESSAGE" not in serialized
