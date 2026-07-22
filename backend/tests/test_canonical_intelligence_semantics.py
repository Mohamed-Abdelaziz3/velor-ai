import json
import uuid

from database import Company, Lead, Message, hash_api_key
from services.customer_communication_service import (
    LanguageMode,
    evaluate_adaptive_communication_policy,
    evaluate_customer_communication_profile,
)
from services.customer_memory_service import RelationshipContinuity, evaluate_customer_preference_memory, evaluate_relationship_context
from services.next_best_action_service import NextBestSalesAction, evaluate_next_best_action
from services.objection_intelligence_service import ObjectionExplicitness, ObjectionType, evaluate_objection_intelligence
from services.product_context_service import ProductContext
from services.recommendation_intelligence_service import (
    ExclusionReasonCode,
    NeedType,
    RecommendationOutcome,
    extract_customer_needs,
    evaluate_recommendation_decision,
)
from services.sales_state_service import BuyerIntent, IntentStrength, PrimarySalesState, evaluate_sales_state


def _seed_company_and_web_chat_lead(db):
    company_id = f"semantic_{uuid.uuid4().hex[:8]}"
    visitor_id = f"wc_v_{uuid.uuid4().hex[:12]}"
    company = Company(
        company_id=company_id,
        company_name="Semantic Test Company",
        email=f"{company_id}@example.com",
        password="hashed",
        api_key_hash=hash_api_key(f"{company_id}-api-key"),
        plan="PRO",
        is_web_chat_enabled=True,
        public_chat_slug=f"{company_id}-slug",
    )
    lead = Lead(
        company_id=company_id,
        name="Web Chat Customer",
        phone=None,
        whatsapp_number=None,
        channel_type="VELOR_WEB_CHAT",
        external_customer_id=visitor_id,
        conversation_count=0,
    )
    db.add_all([company, lead])
    db.commit()
    db.refresh(lead)
    return company, lead, visitor_id


def _record_customer_turn(db, company_id, lead, visitor_id, text):
    msg = Message(
        company_id=company_id,
        user_id=visitor_id,
        sender="user",
        direction="incoming",
        message=text,
        internal_message_id=f"semantic-{uuid.uuid4().hex}",
        public_message_id=f"pub-{uuid.uuid4().hex}",
        delivery_status="received",
        processing_status="completed",
    )
    lead.conversation_count = (lead.conversation_count or 0) + 1
    lead.last_message = text
    lead.last_message_sender = "user"
    db.add(msg)
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return msg


def test_web_chat_canonical_intelligence_progresses_semantically_across_commercial_turns(db):
    company, lead, visitor_id = _seed_company_and_web_chat_lead(db)
    catalog = [
        ProductContext(
            name="Arvena Ergo One",
            price=6900,
            currency="EGP",
            category="chair",
            description="ergonomic office chair with mesh back, lumbar support, and comfort for 8 hours",
            colors=["black"],
            warranty="1 year",
        ),
        ProductContext(
            name="Arvena Ergo Pro",
            price=10900,
            currency="EGP",
            category="chair",
            description="premium ergonomic office chair with mesh back, headrest, lumbar support, and advanced adjustments",
            colors=["black"],
            warranty="1 year",
        ),
    ]

    history = []
    snapshots = {}
    objection_snapshot = None

    turn_1 = "I'm just browsing office chairs."
    _record_customer_turn(db, company.company_id, lead, visitor_id, turn_1)
    snapshots["browse"] = evaluate_sales_state(db, company.company_id, lead.id, turn_1)
    assert snapshots["browse"].primary_state == PrimarySalesState.BROWSING.value
    assert snapshots["browse"].intent_strength == IntentStrength.LOW.value
    assert BuyerIntent.PURCHASE_COMMITMENT.value not in snapshots["browse"].buyer_intents

    history.append({"role": "user", "content": turn_1})
    turn_2 = "My budget max 7000 EGP; I sit around 8 hours and need a black mesh chair with lumbar support."
    _record_customer_turn(db, company.company_id, lead, visitor_id, turn_2)
    snapshots["needs"] = evaluate_sales_state(db, company.company_id, lead.id, turn_2)
    need_snapshot = extract_customer_needs(turn_2, company.company_id, str(lead.id), recent_messages=history)
    assert any(item.need_type == NeedType.BUDGET_CEILING and item.value == 7000 for item in need_snapshot.hard_constraints)
    assert any(item.need_type == NeedType.PRODUCT_CATEGORY and item.value == "chair" for item in need_snapshot.hard_constraints)
    assert any(item.need_type == NeedType.COLOR_PREFERENCE and item.value == "black" for item in need_snapshot.soft_preferences)

    recommendation = evaluate_recommendation_decision(
        db,
        company.company_id,
        str(lead.id),
        need_snapshot,
        sales_snapshot=snapshots["needs"],
        user_input=turn_2,
        products=catalog,
    )
    assert recommendation.outcome in {RecommendationOutcome.RECOMMEND_ONE, RecommendationOutcome.RECOMMEND_MULTIPLE}
    assert recommendation.recommended_products[0].product_name == "Arvena Ergo One"
    excluded = {row.product_name: [code.value for code in row.reason_codes] for row in recommendation.excluded_products}
    assert ExclusionReasonCode.OUTSIDE_BUDGET.value in excluded["Arvena Ergo Pro"]

    preference_snapshot = evaluate_customer_preference_memory(db, company.company_id, lead.id, turn_2, recent_messages=history)
    assert preference_snapshot.effective_for_current_context
    relationship = evaluate_relationship_context(db, company.company_id, lead.id, turn_2, recent_messages=history, preference_snapshot=preference_snapshot)
    assert relationship.continuity_status != RelationshipContinuity.REPEAT_BUYER

    communication = evaluate_customer_communication_profile(db, company.company_id, lead.id, turn_2, recent_messages=history)
    communication_policy = evaluate_adaptive_communication_policy(company.company_id, lead.id, communication)
    assert communication_policy.language_mode == LanguageMode.ENGLISH

    history.append({"role": "user", "content": turn_2})
    turn_3 = "Compare Ergo One and Ergo Pro."
    _record_customer_turn(db, company.company_id, lead, visitor_id, turn_3)
    snapshots["compare"] = evaluate_sales_state(db, company.company_id, lead.id, turn_3)
    compare_action = evaluate_next_best_action(db, company.company_id, lead.id, snapshots["compare"], turn_3)
    assert snapshots["compare"].primary_state == PrimarySalesState.COMPARING.value
    assert BuyerIntent.PRODUCT_COMPARISON.value in snapshots["compare"].buyer_intents
    assert compare_action.primary_action == NextBestSalesAction.COMPARE_OPTIONS.value

    history.append({"role": "user", "content": turn_3})
    turn_4 = "How much is Ergo Pro?"
    _record_customer_turn(db, company.company_id, lead, visitor_id, turn_4)
    snapshots["price"] = evaluate_sales_state(db, company.company_id, lead.id, turn_4)
    assert snapshots["price"].primary_state == PrimarySalesState.EVALUATING.value
    assert BuyerIntent.PRICE_INQUIRY.value in snapshots["price"].buyer_intents

    history.append({"role": "user", "content": turn_4})
    turn_5 = "10900 is too expensive."
    _record_customer_turn(db, company.company_id, lead, visitor_id, turn_5)
    snapshots["objection"] = evaluate_sales_state(db, company.company_id, lead.id, turn_5)
    objection_snapshot = evaluate_objection_intelligence(
        db,
        company.company_id,
        lead.id,
        turn_5,
        sales_snapshot=snapshots["objection"],
        previous_objection_snapshot=objection_snapshot,
    )
    objection_action = evaluate_next_best_action(db, company.company_id, lead.id, snapshots["objection"], turn_5, objection_snapshot=objection_snapshot)
    assert snapshots["objection"].primary_state == PrimarySalesState.OBJECTING.value
    assert snapshots["objection"].primary_state != PrimarySalesState.BROWSING.value
    assert objection_snapshot.primary_objection == ObjectionType.PRICE_TOO_HIGH.value
    assert objection_snapshot.explicitness == ObjectionExplicitness.EXPLICIT.value
    assert objection_snapshot.evidence_refs
    assert objection_action.primary_action == NextBestSalesAction.RESPOND_TO_SUPPORTED_CONCERN.value

    history.append({"role": "user", "content": turn_5})
    turn_6 = "Send me payment details for Ergo One."
    _record_customer_turn(db, company.company_id, lead, visitor_id, turn_6)
    snapshots["purchase"] = evaluate_sales_state(db, company.company_id, lead.id, turn_6)
    purchase_action = evaluate_next_best_action(db, company.company_id, lead.id, snapshots["purchase"], turn_6)
    assert snapshots["purchase"].primary_state == PrimarySalesState.COMMITTING.value
    assert BuyerIntent.PURCHASE_COMMITMENT.value in snapshots["purchase"].buyer_intents
    assert purchase_action.primary_action == NextBestSalesAction.FACILITATE_PURCHASE.value

    db.refresh(lead)
    persisted_sales_state = json.loads(lead.sales_state_snapshot)
    assert persisted_sales_state["primary_state"] == PrimarySalesState.COMMITTING.value
    assert persisted_sales_state["buyer_intents"] == snapshots["purchase"].buyer_intents
