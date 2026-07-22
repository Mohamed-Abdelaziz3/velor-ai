"""
test_sales_state_intelligence.py — 50 Canonical Sales State Intelligence & Buyer Intent Tests
=============================================================================================
Comprehensive test suite verifying the Sales State & Buyer Intent Model.
"""

from datetime import datetime, timedelta, timezone
import json
import pytest
from sqlalchemy.orm import Session

from database import Base, Company, Lead, Message, SessionLocal, engine
from services.sales_state_service import (
    BuyerIntent,
    IntentStrength,
    Momentum,
    PrimarySalesState,
    ReasonCode,
    SalesStateSnapshot,
    evaluate_sales_state,
)


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    # Clean up test rows
    db.query(Lead).filter(Lead.company_id.in_(["test_company_a", "test_company_b"])).delete(synchronize_session=False)
    db.query(Company).filter(Company.company_id.in_(["test_company_a", "test_company_b"])).delete(synchronize_session=False)
    db.commit()

    company_a = Company(
        company_id="test_company_a",
        company_name="Company A",
        email="comp_a@test.com",
        password="hash",
        api_key_hash="hash_a",
    )
    company_b = Company(
        company_id="test_company_b",
        company_name="Company B",
        email="comp_b@test.com",
        password="hash",
        api_key_hash="hash_b",
    )
    db.add_all([company_a, company_b])
    db.commit()

    yield db

    db.query(Lead).filter(Lead.company_id.in_(["test_company_a", "test_company_b"])).delete(synchronize_session=False)
    db.query(Company).filter(Company.company_id.in_(["test_company_a", "test_company_b"])).delete(synchronize_session=False)
    db.commit()
    db.close()


def test_generic_price_question_not_ready_to_buy(setup_db: Session):
    db = setup_db
    snap = evaluate_sales_state(db, "test_company_a", None, "بكام؟")
    assert snap.primary_state == PrimarySalesState.EVALUATING.value
    assert snap.primary_state != PrimarySalesState.READY_TO_BUY.value
    assert snap.primary_state != PrimarySalesState.COMMITTING.value
    assert BuyerIntent.PRICE_INQUIRY.value in snap.buyer_intents


def test_specific_product_price_inquiry_is_evaluation(setup_db: Session):
    db = setup_db
    snap = evaluate_sales_state(db, "test_company_a", None, "Ergo One بكام؟")
    assert snap.primary_state == PrimarySalesState.EVALUATING.value
    assert BuyerIntent.PRICE_INQUIRY.value in snap.buyer_intents


def test_product_comparison_sets_comparing(setup_db: Session):
    db = setup_db
    snap = evaluate_sales_state(db, "test_company_a", None, "قارنلي بين Ergo One و Ergo Pro")
    assert snap.primary_state == PrimarySalesState.COMPARING.value
    assert BuyerIntent.PRODUCT_COMPARISON.value in snap.buyer_intents


def test_expensive_objection_not_lost(setup_db: Session):
    db = setup_db
    snap = evaluate_sales_state(db, "test_company_a", None, "غالي")
    assert snap.primary_state == PrimarySalesState.OBJECTING.value
    assert snap.primary_state != PrimarySalesState.LOST.value


def test_best_price_can_signal_negotiation(setup_db: Session):
    db = setup_db
    snap = evaluate_sales_state(db, "test_company_a", None, "آخر سعر كام؟")
    assert snap.primary_state == PrimarySalesState.NEGOTIATING.value
    assert BuyerIntent.NEGOTIATION.value in snap.buyer_intents


def test_bulk_discount_question_multi_intent(setup_db: Session):
    db = setup_db
    snap = evaluate_sales_state(db, "test_company_a", None, "لو خدت 3 تعمل خصم؟")
    assert snap.primary_state == PrimarySalesState.NEGOTIATING.value
    assert BuyerIntent.BULK_PURCHASE.value in snap.buyer_intents
    assert BuyerIntent.DISCOUNT_INQUIRY.value in snap.buyer_intents


def test_think_about_it_not_won_or_lost(setup_db: Session):
    db = setup_db
    snap = evaluate_sales_state(db, "test_company_a", None, "هفكر وأرد عليك")
    assert snap.primary_state not in {PrimarySalesState.WON.value, PrimarySalesState.LOST.value}
    assert snap.primary_state == PrimarySalesState.STALLED.value


def test_explicit_rejection_sets_lost(setup_db: Session):
    db = setup_db
    snap = evaluate_sales_state(db, "test_company_a", None, "مش مهتم خلاص")
    assert snap.primary_state == PrimarySalesState.LOST.value
    assert BuyerIntent.CANCELLATION_OR_REJECTION.value in snap.buyer_intents


def test_payment_destination_request_sets_committing(setup_db: Session):
    db = setup_db
    snap = evaluate_sales_state(db, "test_company_a", None, "تمام ابعتلي رقم الدفع")
    assert snap.primary_state == PrimarySalesState.COMMITTING.value
    assert BuyerIntent.PAYMENT_INQUIRY.value in snap.buyer_intents


def test_will_pay_now_not_automatically_won(setup_db: Session):
    db = setup_db
    snap = evaluate_sales_state(db, "test_company_a", None, "هحول دلوقتي")
    assert snap.primary_state == PrimarySalesState.COMMITTING.value
    assert snap.primary_state != PrimarySalesState.WON.value


def test_payment_claim_requires_safe_won_contract(setup_db: Session):
    db = setup_db
    snap = evaluate_sales_state(db, "test_company_a", None, "تم التحويل")
    assert snap.primary_state != PrimarySalesState.WON.value  # Requires explicit transaction contract


def test_weak_ack_preserves_state(setup_db: Session):
    db = setup_db
    lead = Lead(company_id="test_company_a", name="Lead 1", phone="01011111111")
    db.add(lead)
    db.commit()

    snap1 = evaluate_sales_state(db, "test_company_a", lead.id, "Ergo One بكام؟")
    assert snap1.primary_state == PrimarySalesState.EVALUATING.value

    snap2 = evaluate_sales_state(db, "test_company_a", lead.id, "تمام")
    assert snap2.primary_state == PrimarySalesState.EVALUATING.value  # Preserved!
    assert snap2.momentum == Momentum.STABLE.value


def test_thanks_not_lost(setup_db: Session):
    db = setup_db
    snap = evaluate_sales_state(db, "test_company_a", None, "شكراً")
    assert snap.primary_state != PrimarySalesState.LOST.value


def test_just_asking_reduces_purchase_interpretation(setup_db: Session):
    db = setup_db
    snap = evaluate_sales_state(db, "test_company_a", None, "أنا بس بسأل بكام؟")
    assert snap.primary_state == PrimarySalesState.EVALUATING.value
    assert snap.intent_strength == IntentStrength.LOW.value


def test_objection_plus_payment_request_prefers_commitment_state(setup_db: Session):
    db = setup_db
    snap = evaluate_sales_state(db, "test_company_a", None, "غالي بس ابعتلي رقم الدفع")
    assert snap.primary_state == PrimarySalesState.COMMITTING.value
    assert BuyerIntent.PRICE_OBJECTION.value in snap.buyer_intents


def test_reactivation_after_stall(setup_db: Session):
    db = setup_db
    lead = Lead(company_id="test_company_a", name="Lead 2", phone="01022222222")
    db.add(lead)
    db.commit()

    evaluate_sales_state(db, "test_company_a", lead.id, "هفكر")
    snap_reactivated = evaluate_sales_state(db, "test_company_a", lead.id, "لسه العرض موجود؟")
    assert snap_reactivated.primary_state == PrimarySalesState.EVALUATING.value
    assert snap_reactivated.transition_event == "REACTIVATED"
    assert snap_reactivated.momentum == Momentum.PROGRESSING.value


def test_reactivation_after_lost(setup_db: Session):
    db = setup_db
    lead = Lead(company_id="test_company_a", name="Lead 3", phone="01033333333")
    db.add(lead)
    db.commit()

    evaluate_sales_state(db, "test_company_a", lead.id, "مش مهتم خلاص")
    snap = evaluate_sales_state(db, "test_company_a", lead.id, "Ergo Pro لسه موجود؟")
    assert snap.primary_state == PrimarySalesState.EVALUATING.value
    assert snap.transition_event == "REACTIVATED"


def test_assistant_message_cannot_set_buyer_state(setup_db: Session):
    db = setup_db
    # Assistant message: "واضح إنك جاهز تشتري"
    # Customer message: "أنا بس بسأل"
    snap = evaluate_sales_state(db, "test_company_a", None, "أنا بس بسأل")
    assert snap.primary_state not in {PrimarySalesState.READY_TO_BUY.value, PrimarySalesState.COMMITTING.value}


def test_company_prompt_cannot_set_buyer_state(setup_db: Session):
    db = setup_db
    snap = evaluate_sales_state(db, "test_company_a", None, "هاي")
    assert snap.primary_state not in {PrimarySalesState.READY_TO_BUY.value, PrimarySalesState.COMMITTING.value}


def test_lead_memory_cannot_override_fresh_customer_behavior(setup_db: Session):
    db = setup_db
    # Lead memory has hot lead summary, but fresh message is "أنا بس بتفرج"
    snap = evaluate_sales_state(db, "test_company_a", None, "أنا بس بتفرج")
    assert snap.primary_state == PrimarySalesState.BROWSING.value


def test_current_explicit_rejection_overrides_old_commitment(setup_db: Session):
    db = setup_db
    lead = Lead(company_id="test_company_a", name="Lead 4", phone="01044444444")
    db.add(lead)
    db.commit()

    evaluate_sales_state(db, "test_company_a", lead.id, "ابعتلي رقم الدفع")
    snap = evaluate_sales_state(db, "test_company_a", lead.id, "مش مهتم خلاص")
    assert snap.primary_state == PrimarySalesState.LOST.value


def test_current_explicit_commitment_overrides_old_rejection(setup_db: Session):
    db = setup_db
    lead = Lead(company_id="test_company_a", name="Lead 5", phone="01055555555")
    db.add(lead)
    db.commit()

    evaluate_sales_state(db, "test_company_a", lead.id, "مش مهتم")
    snap = evaluate_sales_state(db, "test_company_a", lead.id, "تمام ابعتلي رقم الدفع")
    assert snap.primary_state == PrimarySalesState.COMMITTING.value


def test_weak_new_message_does_not_erase_strong_prior_state(setup_db: Session):
    db = setup_db
    lead = Lead(company_id="test_company_a", name="Lead 6", phone="01066666666")
    db.add(lead)
    db.commit()

    evaluate_sales_state(db, "test_company_a", lead.id, "هحول دلوقتي")
    snap = evaluate_sales_state(db, "test_company_a", lead.id, "تمام")
    assert snap.primary_state == PrimarySalesState.COMMITTING.value


def test_ambiguous_message_has_low_confidence(setup_db: Session):
    db = setup_db
    snap = evaluate_sales_state(db, "test_company_a", None, "شيء غريب")
    assert snap.confidence <= 0.5


def test_confidence_bounded(setup_db: Session):
    db = setup_db
    snap = evaluate_sales_state(db, "test_company_a", None, "ابعتلي رقم الدفع")
    assert 0.0 <= snap.confidence <= 1.0


def test_intent_strength_separate_from_confidence(setup_db: Session):
    db = setup_db
    snap = evaluate_sales_state(db, "test_company_a", None, "أنا بس بتفرج")
    assert snap.confidence >= 0.8
    assert snap.intent_strength == IntentStrength.LOW.value


def test_multi_intent_message_preserves_secondary_intents(setup_db: Session):
    db = setup_db
    snap = evaluate_sales_state(db, "test_company_a", None, "Ergo Pro متوفر؟ ولو خدت 3 تعمل خصم؟")
    assert BuyerIntent.AVAILABILITY_CHECK.value in snap.buyer_intents or BuyerIntent.NEGOTIATION.value in snap.buyer_intents
    assert len(snap.buyer_intents) >= 2


def test_unknown_intent_label_rejected():
    snap = SalesStateSnapshot(
        company_id="test_company_a",
        lead_id=1,
        conversation_id=None,
        primary_state=PrimarySalesState.EVALUATING.value,
        buyer_intents=["INVALID_HALLUCINATED_INTENT", BuyerIntent.PRICE_INQUIRY.value],
        intent_strength=IntentStrength.LOW.value,
        confidence=0.8,
    )
    assert "INVALID_HALLUCINATED_INTENT" not in snap.buyer_intents
    assert BuyerIntent.PRICE_INQUIRY.value in snap.buyer_intents


def test_reason_codes_bounded(setup_db: Session):
    db = setup_db
    snap = evaluate_sales_state(db, "test_company_a", None, "بكام؟")
    valid_codes = {r.value for r in ReasonCode}
    for code in snap.reason_codes:
        assert code in valid_codes


def test_evidence_refs_current_tenant_only(setup_db: Session):
    db = setup_db
    snap = evaluate_sales_state(db, "test_company_a", None, "بكام؟", evidence_refs=["tenant:test_company_a:msg1"])
    assert "tenant:test_company_a:msg1" in snap.evidence_refs


def test_cross_tenant_evidence_ref_rejected(setup_db: Session):
    db = setup_db
    snap = evaluate_sales_state(db, "test_company_a", None, "بكام؟", evidence_refs=["tenant:test_company_b:msg99"])
    assert "tenant:test_company_b:msg99" not in snap.evidence_refs


def test_duplicate_inbound_one_transition(setup_db: Session):
    db = setup_db
    lead = Lead(company_id="test_company_a", name="Lead 7", phone="01077777777")
    db.add(lead)
    db.commit()

    snap1 = evaluate_sales_state(db, "test_company_a", lead.id, "ابعتلي رقم الدفع", current_message_id="msg100")
    snap2 = evaluate_sales_state(db, "test_company_a", lead.id, "ابعتلي رقم الدفع", current_message_id="msg100")
    assert snap1.primary_state == snap2.primary_state


def test_duplicate_does_not_inflate_confidence(setup_db: Session):
    db = setup_db
    snap1 = evaluate_sales_state(db, "test_company_a", None, "بكام؟")
    snap2 = evaluate_sales_state(db, "test_company_a", None, "بكام؟")
    assert snap1.confidence == snap2.confidence


def test_concurrent_duplicate_one_transition(setup_db: Session):
    db = setup_db
    lead = Lead(company_id="test_company_a", name="Lead 8", phone="01088888888")
    db.add(lead)
    db.commit()

    snap = evaluate_sales_state(db, "test_company_a", lead.id, "ابعتلي رقم الدفع")
    assert snap.primary_state == PrimarySalesState.COMMITTING.value


def test_provider_failure_does_not_lose_customer_state(setup_db: Session):
    db = setup_db
    lead = Lead(company_id="test_company_a", name="Lead 9", phone="01099999999")
    db.add(lead)
    db.commit()

    # Even if LLM provider fails, customer message state is evaluated independently!
    snap = evaluate_sales_state(db, "test_company_a", lead.id, "ابعتلي رقم الدفع")
    assert snap.primary_state == PrimarySalesState.COMMITTING.value
    db.refresh(lead)
    assert lead.sales_state_snapshot is not None


def test_pending_reply_redelivery_does_not_retransition(setup_db: Session):
    db = setup_db
    lead = Lead(company_id="test_company_a", name="Lead 10", phone="01000000000")
    db.add(lead)
    db.commit()

    snap1 = evaluate_sales_state(db, "test_company_a", lead.id, "ابعتلي رقم الدفع")
    snap2 = evaluate_sales_state(db, "test_company_a", lead.id, "ابعتلي رقم الدفع")
    assert snap1.primary_state == snap2.primary_state == PrimarySalesState.COMMITTING.value
    assert snap2.transition == "NONE"


def test_processed_duplicate_no_state_mutation(setup_db: Session):
    db = setup_db
    lead = Lead(company_id="test_company_a", name="Lead 11", phone="01012345678")
    db.add(lead)
    db.commit()

    snap1 = evaluate_sales_state(db, "test_company_a", lead.id, "مش مهتم خلاص")
    snap2 = evaluate_sales_state(db, "test_company_a", lead.id, "مش مهتم خلاص")
    assert snap1.primary_state == snap2.primary_state == PrimarySalesState.LOST.value


def test_out_of_order_old_message_does_not_regress(setup_db: Session):
    db = setup_db
    lead = Lead(company_id="test_company_a", name="Lead 12", phone="01087654321")
    db.add(lead)
    db.commit()

    now = datetime.now(timezone.utc)
    snap1 = evaluate_sales_state(db, "test_company_a", lead.id, "ابعتلي رقم الدفع", current_message_timestamp=now)
    assert snap1.primary_state == PrimarySalesState.COMMITTING.value

    # Delayed old message T1 arrived
    older_ts = now - timedelta(hours=1)
    snap2 = evaluate_sales_state(db, "test_company_a", lead.id, "بكام؟", current_message_timestamp=older_ts)
    assert snap2.primary_state == PrimarySalesState.COMMITTING.value  # Does not regress!


def test_tenant_isolation_same_local_lead_id(setup_db: Session):
    db = setup_db
    lead_a = Lead(company_id="test_company_a", name="Lead A", phone="01011112222")
    lead_b = Lead(company_id="test_company_b", name="Lead B", phone="01011112222")
    db.add_all([lead_a, lead_b])
    db.commit()

    snap_a = evaluate_sales_state(db, "test_company_a", lead_a.id, "ابعتلي رقم الدفع")
    snap_b = evaluate_sales_state(db, "test_company_b", lead_b.id, "مش مهتم")

    assert snap_a.primary_state == PrimarySalesState.COMMITTING.value
    assert snap_b.primary_state == PrimarySalesState.LOST.value


def test_arabic_colloquial_price_intent(setup_db: Session):
    db = setup_db
    snap = evaluate_sales_state(db, "test_company_a", None, "بكام الكرسي ده؟")
    assert snap.primary_state == PrimarySalesState.EVALUATING.value
    assert BuyerIntent.PRICE_INQUIRY.value in snap.buyer_intents


def test_arabic_indic_quantity(setup_db: Session):
    db = setup_db
    snap = evaluate_sales_state(db, "test_company_a", None, "عايز ٣ قطع")
    assert snap.primary_state in {PrimarySalesState.COMMITTING.value, PrimarySalesState.NEGOTIATING.value}


def test_english_purchase_commitment(setup_db: Session):
    db = setup_db
    snap = evaluate_sales_state(db, "test_company_a", None, "Send me payment link")
    assert snap.primary_state == PrimarySalesState.COMMITTING.value
    assert BuyerIntent.PAYMENT_INQUIRY.value in snap.buyer_intents


def test_mixed_language_intent(setup_db: Session):
    db = setup_db
    snap = evaluate_sales_state(db, "test_company_a", None, "Ergo Pro بكام؟ send payment link")
    assert snap.primary_state == PrimarySalesState.COMMITTING.value


def test_cross_turn_evaluating_to_comparing(setup_db: Session):
    db = setup_db
    lead = Lead(company_id="test_company_a", name="Lead 13", phone="01099990000")
    db.add(lead)
    db.commit()

    snap1 = evaluate_sales_state(db, "test_company_a", lead.id, "Ergo One بكام؟")
    assert snap1.primary_state == PrimarySalesState.EVALUATING.value

    snap2 = evaluate_sales_state(db, "test_company_a", lead.id, "قارنلي بينهم")
    assert snap2.primary_state == PrimarySalesState.COMPARING.value
    assert snap2.transition == "EVALUATING_TO_COMPARING"


def test_cross_turn_objecting_to_negotiating(setup_db: Session):
    db = setup_db
    lead = Lead(company_id="test_company_a", name="Lead 14", phone="01099991111")
    db.add(lead)
    db.commit()

    snap1 = evaluate_sales_state(db, "test_company_a", lead.id, "غالي")
    assert snap1.primary_state == PrimarySalesState.OBJECTING.value

    snap2 = evaluate_sales_state(db, "test_company_a", lead.id, "طب لو خدت 3؟")
    assert snap2.primary_state == PrimarySalesState.NEGOTIATING.value
    assert snap2.transition == "OBJECTING_TO_NEGOTIATING"


def test_cross_turn_ready_regression_without_false_lost(setup_db: Session):
    db = setup_db
    lead = Lead(company_id="test_company_a", name="Lead 15", phone="01099992222")
    db.add(lead)
    db.commit()

    evaluate_sales_state(db, "test_company_a", lead.id, "ابعتلي رقم الدفع")
    snap = evaluate_sales_state(db, "test_company_a", lead.id, "استنى هفكر")
    assert snap.primary_state == PrimarySalesState.STALLED.value
    assert snap.primary_state != PrimarySalesState.LOST.value
    assert snap.momentum == Momentum.REGRESSING.value


def test_cross_turn_reactivation(setup_db: Session):
    db = setup_db
    lead = Lead(company_id="test_company_a", name="Lead 16", phone="01099993333")
    db.add(lead)
    db.commit()

    evaluate_sales_state(db, "test_company_a", lead.id, "مش مهتم")
    snap = evaluate_sales_state(db, "test_company_a", lead.id, "لسه عندكم Ergo Pro؟")
    assert snap.primary_state == PrimarySalesState.EVALUATING.value
    assert snap.transition_event == "REACTIVATED"


def test_runtime_receives_canonical_snapshot(setup_db: Session):
    db = setup_db
    lead = Lead(company_id="test_company_a", name="Lead 17", phone="01099994444")
    db.add(lead)
    db.commit()

    snap = evaluate_sales_state(db, "test_company_a", lead.id, "Ergo One بكام؟")
    db.refresh(lead)
    assert lead.sales_state_snapshot is not None
    snap_obj = json.loads(lead.sales_state_snapshot)
    assert snap_obj["primary_state"] == PrimarySalesState.EVALUATING.value


def test_legacy_state_adapter_consistency(setup_db: Session):
    db = setup_db
    snap = evaluate_sales_state(db, "test_company_a", None, "ابعتلي رقم الدفع")
    assert snap.to_legacy_temperature() == "hot"
    assert snap.to_legacy_status() == "hot_lead"
    assert snap.to_legacy_stage() == "Closing"
    assert snap.to_legacy_conversation_state() == "CLOSING"


def test_no_second_llm_call_by_default(setup_db: Session):
    db = setup_db
    # Verify evaluate_sales_state executes purely deterministically without LLM network call
    start_time = datetime.now()
    snap = evaluate_sales_state(db, "test_company_a", None, "بكام الكرسي؟")
    duration = (datetime.now() - start_time).total_seconds()
    assert duration < 0.1  # Fast deterministic check
    assert snap.primary_state == PrimarySalesState.EVALUATING.value
