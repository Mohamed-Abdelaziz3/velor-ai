import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from jose import jwt

from database import CommercialEvent, Company, CompanyKnowledge, Lead, Message, hash_api_key
from services.commercial_intelligence_service import (
    CommercialEventType,
    build_business_commercial_intelligence,
    derive_commercial_event_specs,
)
from services.sales_state_service import PrimarySalesState


def _create_company(db, *, products):
    company_id = f"actionable_{uuid.uuid4().hex[:10]}"
    db.add(
        Company(
            company_id=company_id,
            company_name="Actionable Intelligence Proof",
            email=f"{company_id}@example.com",
            password="hashed",
            api_key_hash=hash_api_key(f"{company_id}-key"),
        )
    )
    db.add(
        CompanyKnowledge(
            company_id=company_id,
            system_prompt="Use catalog truth only.",
            products_data=json.dumps(products),
            knowledge_base="Shipping and warranty are not supplied.",
        )
    )
    db.commit()
    return company_id


def _add_lead(db, company_id, name, *, channel="VELOR_WEB_CHAT"):
    lead = Lead(
        company_id=company_id,
        name=name,
        phone=f"01{uuid.uuid4().int % 10**9:09d}",
        channel_type=channel,
        external_customer_id=f"actionable-{uuid.uuid4().hex}",
        is_test=False,
    )
    db.add(lead)
    db.flush()
    return lead


def _add_event(
    db,
    company_id,
    lead,
    event_type,
    *,
    product=None,
    channel="VELOR_WEB_CHAT",
    observed_at=None,
    objection_type=None,
    provenance="actionable_intelligence_test",
):
    source_id = f"actionable:{lead.id}:{event_type}:{uuid.uuid4().hex}"
    db.add(
        CommercialEvent(
            company_id=company_id,
            lead_id=lead.id,
            source_message_internal_id=source_id,
            channel=channel,
            event_type=event_type,
            product_ref=product,
            stage="TEST_STAGE",
            objection_type=objection_type,
            source_text=f"Evidence for {event_type}",
            evidence_json="{}",
            provenance=provenance,
            event_hash=hashlib.sha256(f"{company_id}|{source_id}".encode()).hexdigest(),
            observed_at=observed_at or datetime.now(timezone.utc),
        )
    )


def _tenant_token(company_id):
    return jwt.encode(
        {"company_id": company_id, "role": "tenant", "token_type": "access"},
        "super-secret-test-key-32-chars-long",
        algorithm="HS256",
    )


def test_derivation_uses_sales_state_objection_taxonomy_and_catalog_availability(db):
    company_id = _create_company(
        db,
        products=[
            {"name": "Out Chair", "aliases": ["Chair Zero"], "price": 1000, "stock": 0},
            {"name": "In Desk", "price": 2500, "stock": 4},
        ],
    )
    lead = _add_lead(db, company_id, "Derivation proof")
    db.commit()

    objection = SimpleNamespace(
        objection_present=True,
        explicitness="EXPLICIT",
        primary_objection="TRUST_CREDIBILITY",
        confidence=0.92,
        root_cause_hypothesis="NEEDS_PROOF",
        root_cause_confidence=0.61,
        reason_codes=["ASKED_FOR_PROOF"],
    )
    specs = derive_commercial_event_specs(
        db,
        company_id,
        lead.id,
        "Do you have Out Chair? I do not trust the quality claim.",
        "This generated text must not become evidence.",
        SimpleNamespace(),
        SimpleNamespace(primary_state=PrimarySalesState.EVALUATING),
        objection_snapshot=objection,
    )
    by_type = {item["event_type"]: item for item in specs}

    assert CommercialEventType.PRODUCT_CONSIDERED.value in by_type
    assert by_type[CommercialEventType.PRODUCT_REQUESTED_OUT_OF_STOCK.value]["stock_state"] == "out_of_stock"
    objection_event = by_type[CommercialEventType.OBJECTION_EXPRESSED.value]
    assert objection_event["objection_type"] == "TRUST_CREDIBILITY"
    assert objection_event["root_cause_truth_class"] == "HYPOTHESIS"
    assert objection_event["reason_codes"] == ["ASKED_FOR_PROOF"]

    generic_question = derive_commercial_event_specs(
        db,
        company_id,
        lead.id,
        "Why is Out Chair so expensive?",
        "It costs 1000.",
        SimpleNamespace(),
        SimpleNamespace(primary_state=PrimarySalesState.OBJECTING),
    )
    assert CommercialEventType.PRODUCT_REQUESTED_OUT_OF_STOCK.value not in {
        item["event_type"] for item in generic_question
    }
    negated_request = derive_commercial_event_specs(
        db,
        company_id,
        lead.id,
        "مش عايز Out Chair",
        "تمام.",
        SimpleNamespace(),
        SimpleNamespace(primary_state=PrimarySalesState.BROWSING),
    )
    assert CommercialEventType.PRODUCT_REQUESTED_OUT_OF_STOCK.value not in {
        item["event_type"] for item in negated_request
    }

    unlisted = derive_commercial_event_specs(
        db,
        company_id,
        lead.id,
        "Do you carry Falcon Standing Desk?",
        "No.",
        SimpleNamespace(),
        SimpleNamespace(primary_state=None),
    )
    unlisted_event = next(item for item in unlisted if item["event_type"] == CommercialEventType.PRODUCT_REQUESTED_UNLISTED.value)
    assert unlisted_event["product_ref"] == "Falcon Standing Desk"
    assert unlisted_event["catalog_match_status"] == "unlisted"

    generic = derive_commercial_event_specs(
        db,
        company_id,
        lead.id,
        "I like modern offices.",
        "Thanks.",
        SimpleNamespace(),
        None,
    )
    assert CommercialEventType.PRODUCT_REQUESTED_UNLISTED.value not in {item["event_type"] for item in generic}


def test_actionable_aggregation_counts_distinct_conversations_and_current_unavailable_demand(db):
    company_id = _create_company(
        db,
        products=[
            {"name": "Out Chair", "price": 1000, "stock": 0},
            {"name": "In Desk", "price": 2500, "stock": 5},
        ],
    )
    now = datetime.now(timezone.utc)
    intent_lead = _add_lead(db, company_id, "Intent customer", channel="WHATSAPP_QR")
    stalled_lead = _add_lead(db, company_id, "Stalled customer")
    execution_lead = _add_lead(db, company_id, "Execution customer", channel="WHATSAPP_CLOUD")

    for event_type in (
        CommercialEventType.PRODUCT_ASKED_ABOUT.value,
        CommercialEventType.PRODUCT_REQUESTED_OUT_OF_STOCK.value,
        CommercialEventType.OBJECTION_EXPRESSED.value,
        CommercialEventType.PURCHASE_INTENT_EXPRESSED.value,
    ):
        _add_event(
            db,
            company_id,
            intent_lead,
            event_type,
            product="Out Chair",
            channel="WHATSAPP_QR",
            observed_at=now,
            objection_type="TRUST_CREDIBILITY" if event_type == CommercialEventType.OBJECTION_EXPRESSED.value else None,
        )

    for event_type in (
        CommercialEventType.PRODUCT_ASKED_ABOUT.value,
        CommercialEventType.CONVERSATION_STALLED.value,
    ):
        _add_event(db, company_id, stalled_lead, event_type, product="Out Chair", observed_at=now)

    for event_type in (
        CommercialEventType.PRODUCT_ASKED_ABOUT.value,
        CommercialEventType.PRODUCT_SELECTED.value,
        CommercialEventType.PURCHASE_COMMITMENT.value,
        CommercialEventType.PURCHASE_EXECUTION_REQUEST.value,
        CommercialEventType.WAITING_ON_US.value,
    ):
        _add_event(
            db,
            company_id,
            execution_lead,
            event_type,
            product="In Desk",
            channel="WHATSAPP_CLOUD",
            observed_at=now,
        )
    db.add(
        Message(
            internal_message_id=f"current-waiting-{uuid.uuid4().hex}",
            company_id=company_id,
            user_id=execution_lead.phone,
            sender="user",
            direction="incoming",
            message="How do I complete the next step?",
            delivery_status="received",
            processing_status="completed",
            created_at=now,
        )
    )
    db.commit()

    data = build_business_commercial_intelligence(db, company_id, days=30)
    summary = data["summary"]
    assert summary["source_conversations"] == 3
    assert summary["demand_conversations"] == 3
    assert summary["progressed_conversations"] == 2
    assert summary["demand_without_progress"] == 1
    assert summary["purchase_intent"] == 1
    assert summary["purchase_commitment"] == 1
    assert summary["purchase_execution"] == 1
    assert summary["objection"] == 1
    assert summary["stalled"] == 1
    assert summary["knowledge_gap"] == 0
    assert summary["waiting_on_us"] == 1
    assert summary["current_unavailable_demand"] == 1
    assert summary["confirmed_orders"] is None
    assert summary["paid_outcomes"] is None

    products = {item["product"]: item for item in data["products"]}
    out_chair = products["Out Chair"]
    assert out_chair["demand_conversations"] == 2
    assert out_chair["progressed_conversations"] == 1
    assert out_chair["progression_rate"] == 0.5
    assert out_chair["demand_gap"] == 1
    assert out_chair["current_catalog_stock_state"] == "out_of_stock"
    assert out_chair["current_unavailable_demand"] == 1
    assert out_chair["friction_counts"] == {
        "objection": 1,
        "stalled": 1,
        "knowledge_gap": 0,
        "waiting_on_us": 0,
        "unavailable_request": 1,
    }
    assert products["In Desk"]["current_catalog_stock_state"] == "available"

    today = now.date().isoformat()
    today_row = next(item for item in data["daily_trend"] if item["date"] == today)
    assert today_row["demand_conversations"] == 3
    assert today_row["progressed_conversations"] == 2
    assert today_row["demand_without_progress"] == 1

    queue = data["opportunity_queue"]
    assert queue[0]["lead_id"] == execution_lead.id
    assert queue[0]["status"] == CommercialEventType.WAITING_ON_US.value
    assert queue[0]["reason_code"] == "UNKNOWN_INCIDENT"
    assert queue[0]["source"]["lead_id"] == execution_lead.id
    assert queue[0]["evidence"]
    assert queue[0]["action"]
    assert queue[0]["outcome_scope"] == "current_owner_attention_projection"
    assert {item["outcome_scope"] for item in queue}.issubset(
        {"current_owner_attention_projection", "conversation_progress_only"}
    )


def test_days_channel_and_tenant_filters_are_enforced_by_service_and_route(client, db):
    company_id = _create_company(db, products=[{"name": "Filter Product", "stock": 2}])
    other_company_id = _create_company(db, products=[{"name": "Other Tenant Product", "stock": 2}])
    now = datetime.now(timezone.utc)

    whatsapp_lead = _add_lead(db, company_id, "WhatsApp customer", channel="WHATSAPP_QR")
    web_lead = _add_lead(db, company_id, "Web customer")
    old_lead = _add_lead(db, company_id, "Old customer", channel="WHATSAPP_QR")
    other_lead = _add_lead(db, other_company_id, "Other tenant", channel="WHATSAPP_QR")
    _add_event(
        db,
        company_id,
        whatsapp_lead,
        CommercialEventType.PRODUCT_ASKED_ABOUT.value,
        product="Filter Product",
        channel="WHATSAPP_QR",
        observed_at=now,
    )
    _add_event(
        db,
        company_id,
        web_lead,
        CommercialEventType.PRODUCT_ASKED_ABOUT.value,
        product="Filter Product",
        channel="VELOR_WEB_CHAT",
        observed_at=now,
    )
    _add_event(
        db,
        company_id,
        old_lead,
        CommercialEventType.PRODUCT_ASKED_ABOUT.value,
        product="Filter Product",
        channel="WHATSAPP_QR",
        observed_at=now - timedelta(days=45),
    )
    _add_event(
        db,
        other_company_id,
        other_lead,
        CommercialEventType.PRODUCT_ASKED_ABOUT.value,
        product="Other Tenant Product",
        channel="WHATSAPP_QR",
        observed_at=now,
    )
    db.add(
        Message(
            internal_message_id=f"old-current-wait-{uuid.uuid4().hex}",
            company_id=company_id,
            user_id=old_lead.phone,
            sender="user",
            direction="incoming",
            message="This old message is still unanswered.",
            delivery_status="received",
            processing_status="completed",
            created_at=now - timedelta(days=45),
        )
    )
    db.commit()

    service_data = build_business_commercial_intelligence(db, company_id, days=30, channel="whatsapp")
    assert service_data["window_days"] == 30
    assert service_data["channel"] == "whatsapp"
    assert service_data["summary"]["source_conversations"] == 1
    serialized = json.dumps(service_data)
    assert "WhatsApp customer" in serialized
    assert "Web customer" not in serialized
    assert "Old customer" not in serialized
    assert "Other tenant" not in serialized
    assert "Other Tenant Product" not in serialized
    assert service_data["summary"]["waiting_on_us"] == 0
    assert service_data["scope_metadata"]["current_owner_attention"]["days_filter_applied"] is True

    response = client.get(
        "/api/v1/intelligence/business-insights?days=30&channel=whatsapp",
        cookies={"access_token": _tenant_token(company_id)},
    )
    assert response.status_code == 200
    route_data = response.json()["data"]
    assert route_data["filters"] == {
        "days": 30,
        "channel": "whatsapp",
        "tenant_scope": company_id,
    }
    assert route_data["summary"]["source_conversations"] == 1

    too_many_days = client.get(
        "/api/v1/intelligence/business-insights?days=366&channel=all",
        cookies={"access_token": _tenant_token(company_id)},
    )
    invalid_channel = client.get(
        "/api/v1/intelligence/business-insights?days=30&channel=email",
        cookies={"access_token": _tenant_token(company_id)},
    )
    assert too_many_days.status_code == 422
    assert invalid_channel.status_code == 422


def test_cross_day_progress_resolves_backlog_and_replenished_stock_is_not_currently_unavailable(db):
    company_id = _create_company(
        db,
        products=[{"name": "Restocked Chair", "stock": 8}],
    )
    lead = _add_lead(db, company_id, "Restocked customer")
    now = datetime.now(timezone.utc)
    demand_at = now - timedelta(days=2)
    _add_event(
        db,
        company_id,
        lead,
        CommercialEventType.PRODUCT_ASKED_ABOUT.value,
        product="Restocked Chair",
        observed_at=demand_at,
    )
    _add_event(
        db,
        company_id,
        lead,
        CommercialEventType.PRODUCT_REQUESTED_OUT_OF_STOCK.value,
        product="Restocked Chair",
        observed_at=demand_at,
    )
    _add_event(
        db,
        company_id,
        lead,
        CommercialEventType.PRODUCT_SELECTED.value,
        product="Restocked Chair",
        observed_at=now,
    )
    db.commit()

    data = build_business_commercial_intelligence(db, company_id, days=7)
    product = next(item for item in data["products"] if item["product"] == "Restocked Chair")
    assert product["progressed_conversations"] == 1
    assert product["demand_gap"] == 0
    assert product["current_catalog_stock_state"] == "available"
    assert product["current_unavailable_demand"] == 0
    assert data["summary"]["current_unavailable_demand"] == 0
    assert all(
        item["reason_code"] != CommercialEventType.PRODUCT_REQUESTED_OUT_OF_STOCK.value
        for item in data["opportunity_queue"]
    )

    by_date = {item["date"]: item for item in data["daily_trend"]}
    demand_day = demand_at.date().isoformat()
    middle_day = (demand_at.date() + timedelta(days=1)).isoformat()
    current_day = now.date().isoformat()
    assert by_date[demand_day]["demand_without_progress_backlog"] == 1
    assert by_date[middle_day]["demand_without_progress_backlog"] == 1
    assert by_date[current_day]["demand_without_progress_backlog"] == 0
    assert by_date[current_day]["cumulative_progressed_conversations"] == 1


def test_progression_before_newer_demand_does_not_resolve_that_demand(db):
    company_id = _create_company(db, products=[{"name": "Timeline Chair", "stock": 5}])
    lead = _add_lead(db, company_id, "Timeline customer")
    now = datetime.now(timezone.utc)
    _add_event(
        db,
        company_id,
        lead,
        CommercialEventType.PURCHASE_INTENT_EXPRESSED.value,
        product="Timeline Chair",
        observed_at=now - timedelta(days=2),
    )
    _add_event(
        db,
        company_id,
        lead,
        CommercialEventType.PRODUCT_ASKED_ABOUT.value,
        product="Timeline Chair",
        observed_at=now - timedelta(days=1),
    )
    db.commit()

    data = build_business_commercial_intelligence(db, company_id, days=7)
    product = next(item for item in data["products"] if item["product"] == "Timeline Chair")
    assert product["progressed_conversations"] == 0
    assert product["demand_without_progress"] == 1
    assert data["summary"]["progressed_conversations"] == 0
    assert data["summary"]["demand_without_progress"] == 1
    demand_day = (now - timedelta(days=1)).date().isoformat()
    assert next(item for item in data["daily_trend"] if item["date"] == demand_day)[
        "demand_without_progress_backlog"
    ] == 1


def test_event_opportunity_uses_latest_state_and_terminal_outcome_resolves_older_actions(db):
    company_id = _create_company(db, products=[{"name": "State Chair", "stock": 5}])
    stalled_lead = _add_lead(db, company_id, "Later stalled")
    resolved_lead = _add_lead(db, company_id, "Later resolved")
    now = datetime.now(timezone.utc)

    for event_type, observed_at in (
        (CommercialEventType.PRODUCT_ASKED_ABOUT.value, now - timedelta(hours=4)),
        (CommercialEventType.PURCHASE_EXECUTION_REQUEST.value, now - timedelta(hours=3)),
        (CommercialEventType.CONVERSATION_STALLED.value, now - timedelta(hours=1)),
    ):
        _add_event(
            db,
            company_id,
            stalled_lead,
            event_type,
            product="State Chair",
            observed_at=observed_at,
        )

    for event_type, observed_at in (
        (CommercialEventType.PRODUCT_ASKED_ABOUT.value, now - timedelta(hours=4)),
        (CommercialEventType.PURCHASE_INTENT_EXPRESSED.value, now - timedelta(hours=3)),
        (CommercialEventType.CONFIRMED_ORDER.value, now - timedelta(hours=1)),
    ):
        _add_event(
            db,
            company_id,
            resolved_lead,
            event_type,
            product="State Chair",
            observed_at=observed_at,
            provenance=("provider_verified:test_orders" if event_type == CommercialEventType.CONFIRMED_ORDER.value else "actionable_intelligence_test"),
        )
    db.commit()

    data = build_business_commercial_intelligence(db, company_id, days=7)
    by_lead = {item["lead_id"]: item for item in data["opportunity_queue"]}
    assert by_lead[stalled_lead.id]["reason_code"] == CommercialEventType.CONVERSATION_STALLED.value
    assert resolved_lead.id not in by_lead


def test_current_owner_reply_clears_historical_waiting_and_suppresses_action_queue(db):
    company_id = _create_company(db, products=[{"name": "Answered Chair", "stock": 3}])
    lead = _add_lead(db, company_id, "Answered customer", channel="VELOR_WEB_CHAT")
    now = datetime.now(timezone.utc)
    incoming_id = f"answered-in-{uuid.uuid4().hex}"
    db.add_all(
        [
            Message(
                internal_message_id=incoming_id,
                company_id=company_id,
                user_id=lead.external_customer_id,
                sender="user",
                direction="incoming",
                message="Can you help me with Answered Chair?",
                delivery_status="received",
                processing_status="completed",
                created_at=now - timedelta(minutes=2),
            ),
            Message(
                internal_message_id=f"answered-out-{uuid.uuid4().hex}",
                company_id=company_id,
                user_id=lead.external_customer_id,
                sender="owner",
                direction="outgoing",
                message="Yes, here are the verified details.",
                delivery_status="sent",
                processing_status="completed",
                created_at=now - timedelta(minutes=1),
            ),
        ]
    )
    _add_event(
        db,
        company_id,
        lead,
        CommercialEventType.PRODUCT_ASKED_ABOUT.value,
        product="Answered Chair",
        observed_at=now - timedelta(minutes=2),
    )
    _add_event(
        db,
        company_id,
        lead,
        CommercialEventType.WAITING_ON_US.value,
        product="Answered Chair",
        observed_at=now - timedelta(minutes=2),
    )
    db.commit()

    data = build_business_commercial_intelligence(db, company_id, days=7)
    assert data["summary"]["waiting_on_us"] == 0
    assert data["opportunity_queue"] == []
    assert not any(item["type"] == "OWNER_RESPONSE_LEAKAGE" for item in data["insights"])
