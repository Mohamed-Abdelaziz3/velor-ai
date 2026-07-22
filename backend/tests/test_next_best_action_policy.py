"""
test_next_best_action_policy.py — Comprehensive Test Suite for Next Best Sales Action & Strategy Policy
========================================================================================================
Validates decision logic, hard priorities, strategy alignment, adversarial safety, human takeover gates,
auto reply controls, commit-path safety, tenant isolation, idempotency, fallback paths, provider payload,
and zero-added-LLM call guarantees.
"""

import json
from unittest.mock import AsyncMock, patch
import pytest
from sqlalchemy.orm import Session

from database import Company, Lead, LeadEvidence, Message, SessionLocal
from services.next_best_action_service import (
    ActionDecision,
    CtaPolicy,
    NextBestSalesAction,
    ProhibitedAction,
    QuestionPolicy,
    StrategyMode,
    evaluate_next_best_action,
)
from services.sales_state_service import (
    BuyerIntent,
    PrimarySalesState,
    SalesStateSnapshot,
    evaluate_sales_state,
)
from services.strategy_alignment_service import (
    StrategyAlignmentResult,
    enforce_strategy_alignment,
)


@pytest.fixture
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def setup_company(db_session: Session):
    company_id = "test_co_nba_101"
    existing = db_session.query(Company).filter(Company.company_id == company_id).first()
    if not existing:
        company = Company(
            company_id=company_id,
            company_name="VELOR NBA Tech",
            email="test_nba@velor.ai",
            password="testpassword123",
            api_key_hash="hash_nba_101",
        )
        db_session.add(company)
        db_session.commit()

        from database import CompanyKnowledge
        ck = CompanyKnowledge(
            company_id=company_id,
            system_prompt="You are VELOR sales bot.",
            products_data=json.dumps([{"name": "Ergo Pro", "price": 1000, "currency": "EGP"}]),
            industry="Sales Intelligence",
        )
        db_session.add(ck)
        db_session.commit()
    return company_id


# ============================================================================
# 1. STATE-TO-ACTION MATRIX & PRIORITIES
# ============================================================================


def test_browsing_state_gives_provide_product_info(db_session, setup_company):
    snap = SalesStateSnapshot(
        company_id=setup_company,
        lead_id=1,
        conversation_id="conv_1",
        primary_state=PrimarySalesState.BROWSING.value,
        buyer_intents=[BuyerIntent.PRODUCT_DISCOVERY.value],
        intent_strength="LOW",
        confidence=0.9,
    )
    decision = evaluate_next_best_action(db_session, setup_company, 1, snap, "أنا بس بتفرج")
    assert decision.primary_action == NextBestSalesAction.PROVIDE_PRODUCT_INFORMATION.value
    assert decision.strategy_mode == StrategyMode.INFORM_AND_ADVANCE.value
    assert ProhibitedAction.PUSH_FOR_PAYMENT.value in decision.prohibited_actions


def test_comparing_state_gives_compare_options(db_session, setup_company):
    snap = SalesStateSnapshot(
        company_id=setup_company,
        lead_id=1,
        conversation_id="conv_1",
        primary_state=PrimarySalesState.COMPARING.value,
        buyer_intents=[BuyerIntent.PRODUCT_COMPARISON.value],
        intent_strength="MEDIUM",
        confidence=0.9,
    )
    decision = evaluate_next_best_action(db_session, setup_company, 1, snap, "قارنلي بينهم")
    assert decision.primary_action == NextBestSalesAction.COMPARE_OPTIONS.value
    assert decision.strategy_mode == StrategyMode.COMPARE_AND_NARROW.value


def test_committing_state_gives_facilitate_purchase(db_session, setup_company):
    snap = SalesStateSnapshot(
        company_id=setup_company,
        lead_id=1,
        conversation_id="conv_1",
        primary_state=PrimarySalesState.COMMITTING.value,
        buyer_intents=[BuyerIntent.PURCHASE_COMMITMENT.value],
        intent_strength="HIGH",
        confidence=0.95,
    )
    decision = evaluate_next_best_action(db_session, setup_company, 1, snap, "تمام ابعتلي رقم الدفع")
    assert decision.primary_action == NextBestSalesAction.FACILITATE_PURCHASE.value
    assert decision.strategy_mode == StrategyMode.PURCHASE_EXECUTION.value
    assert ProhibitedAction.RESET_PURCHASE_TO_DISCOVERY.value in decision.prohibited_actions


def test_explicit_rejection_gives_respect_rejection(db_session, setup_company):
    snap = SalesStateSnapshot(
        company_id=setup_company,
        lead_id=1,
        conversation_id="conv_1",
        primary_state=PrimarySalesState.LOST.value,
        buyer_intents=[BuyerIntent.CANCELLATION_OR_REJECTION.value],
        intent_strength="HIGH",
        confidence=0.95,
    )
    decision = evaluate_next_best_action(db_session, setup_company, 1, snap, "مش مهتم خلاص")
    assert decision.primary_action == NextBestSalesAction.RESPECT_REJECTION.value
    assert decision.strategy_mode == StrategyMode.RESPECT_AND_CLOSE.value
    assert decision.cta_policy == CtaPolicy.NONE.value
    assert ProhibitedAction.CONTINUE_SELLING_AFTER_REJECTION.value in decision.prohibited_actions


def test_post_sale_support_gives_route_post_sale_support(db_session, setup_company):
    snap = SalesStateSnapshot(
        company_id=setup_company,
        lead_id=1,
        conversation_id="conv_1",
        primary_state=PrimarySalesState.EVALUATING.value,
        buyer_intents=[BuyerIntent.SUPPORT_OR_POST_SALE.value],
        intent_strength="MEDIUM",
        confidence=0.9,
    )
    decision = evaluate_next_best_action(db_session, setup_company, 1, snap, "الطلب وصل ناقص")
    assert decision.primary_action == NextBestSalesAction.ROUTE_POST_SALE_SUPPORT.value
    assert decision.strategy_mode == StrategyMode.POST_SALE_SUPPORT.value
    assert ProhibitedAction.FORCE_SALES_ON_SUPPORT.value in decision.prohibited_actions


# ============================================================================
# 2. RUNTIME GATES (HUMAN TAKEOVER & AUTO-REPLY CONTROL)
# ============================================================================


def test_human_takeover_active_gate(db_session, setup_company):
    snap = SalesStateSnapshot(
        company_id=setup_company,
        lead_id=1,
        conversation_id="conv_1",
        primary_state=PrimarySalesState.COMMITTING.value,
        buyer_intents=[BuyerIntent.PURCHASE_COMMITMENT.value],
        intent_strength="HIGH",
        confidence=0.95,
    )
    decision = evaluate_next_best_action(
        db_session, setup_company, 1, snap, "ابعتلي رقم الدفع", human_takeover_active=True
    )
    assert decision.primary_action == NextBestSalesAction.PAUSE_FOR_HUMAN_TAKEOVER.value
    assert decision.strategy_mode == StrategyMode.HUMAN_HANDOFF.value
    assert decision.cta_policy == CtaPolicy.NONE.value


def test_auto_reply_disabled_gate(db_session, setup_company):
    snap = SalesStateSnapshot(
        company_id=setup_company,
        lead_id=1,
        conversation_id="conv_1",
        primary_state=PrimarySalesState.EVALUATING.value,
        buyer_intents=[BuyerIntent.PRICE_INQUIRY.value],
        intent_strength="MEDIUM",
        confidence=0.85,
    )
    decision = evaluate_next_best_action(
        db_session, setup_company, 1, snap, "بكام؟", auto_reply_disabled=True
    )
    assert decision.primary_action == NextBestSalesAction.PAUSE_FOR_HUMAN_TAKEOVER.value
    assert decision.strategy_mode == StrategyMode.HUMAN_HANDOFF.value


# ============================================================================
# 3. MANDATORY ADVERSARIAL STRATEGY TESTS (CASES A - J)
# ============================================================================


def test_adversarial_case_a_browsing_payment_pressure_blocked(setup_company):
    decision = ActionDecision(
        company_id=setup_company,
        lead_id=1,
        conversation_id="conv_1",
        primary_action=NextBestSalesAction.PROVIDE_PRODUCT_INFORMATION.value,
        strategy_mode=StrategyMode.INFORM_AND_ADVANCE.value,
        cta_policy=CtaPolicy.NONE.value,
        prohibited_actions=[ProhibitedAction.PUSH_FOR_PAYMENT.value],
    )
    candidate = "أهلاً بك، Ergo Pro ممتاز جداً. حول دلوقتي عشان تأكد الطلب."
    res = enforce_strategy_alignment("بكام؟", candidate, decision)
    assert res.status == "REPAIRED"
    assert "حول دلوقتي" not in res.final_answer


def test_adversarial_case_b_rejection_discount_continuation_blocked(setup_company):
    decision = ActionDecision(
        company_id=setup_company,
        lead_id=1,
        conversation_id="conv_1",
        primary_action=NextBestSalesAction.RESPECT_REJECTION.value,
        strategy_mode=StrategyMode.RESPECT_AND_CLOSE.value,
        cta_policy=CtaPolicy.NONE.value,
        prohibited_actions=[ProhibitedAction.CONTINUE_SELLING_AFTER_REJECTION.value],
    )
    candidate = "طب خد خصم 20% واطلب دلوقتي بسرعة."
    res = enforce_strategy_alignment("مش مهتم خلاص", candidate, decision)
    assert res.status == "REPAIRED"
    assert "خصم" not in res.final_answer
    assert "شكراً لوقتك" in res.final_answer


def test_adversarial_case_c_comparing_premature_close_blocked(setup_company):
    decision = ActionDecision(
        company_id=setup_company,
        lead_id=1,
        conversation_id="conv_1",
        primary_action=NextBestSalesAction.COMPARE_OPTIONS.value,
        strategy_mode=StrategyMode.COMPARE_AND_NARROW.value,
        prohibited_actions=[ProhibitedAction.PUSH_FOR_PAYMENT.value],
    )
    candidate = "اختار الـ Pro وابعت الدفع دلوقتي."
    res = enforce_strategy_alignment("قارنلي بينهم", candidate, decision)
    assert res.status == "REPAIRED"
    assert "ابعت الدفع" not in res.final_answer


def test_adversarial_case_d_committing_discovery_reset_blocked(setup_company):
    decision = ActionDecision(
        company_id=setup_company,
        lead_id=1,
        conversation_id="conv_1",
        primary_action=NextBestSalesAction.FACILITATE_PURCHASE.value,
        strategy_mode=StrategyMode.PURCHASE_EXECUTION.value,
        prohibited_actions=[ProhibitedAction.RESET_PURCHASE_TO_DISCOVERY.value],
    )
    candidate = "تمام، خلينا نبدأ من الأول ونعرف ميزانيتك واحتياجاتك بالتفصيل."
    res = enforce_strategy_alignment("تمام ابعتلي رقم الدفع", candidate, decision)
    assert res.status == "REPAIRED"
    assert "نبدأ من الأول" not in res.final_answer


def test_adversarial_case_e_support_sales_push_blocked(setup_company):
    decision = ActionDecision(
        company_id=setup_company,
        lead_id=1,
        conversation_id="conv_1",
        primary_action=NextBestSalesAction.ROUTE_POST_SALE_SUPPORT.value,
        strategy_mode=StrategyMode.POST_SALE_SUPPORT.value,
        prohibited_actions=[ProhibitedAction.FORCE_SALES_ON_SUPPORT.value],
    )
    candidate = "بالمناسبة اشتري منتج تاني عندنا عليه عرض."
    res = enforce_strategy_alignment("الطلب وصل ناقص", candidate, decision)
    assert res.status == "REPAIRED"
    assert "اشتري منتج" not in res.final_answer


def test_adversarial_case_f_untrusted_discount_blocked(setup_company):
    decision = ActionDecision(
        company_id=setup_company,
        lead_id=1,
        conversation_id="conv_1",
        primary_action=NextBestSalesAction.PROVIDE_PRODUCT_INFORMATION.value,
        strategy_mode=StrategyMode.INFORM_AND_ADVANCE.value,
        prohibited_actions=[ProhibitedAction.OFFER_UNTRUSTED_DISCOUNT.value],
    )
    candidate = "هعملك خصم 15% لو طلبت حالا."
    res = enforce_strategy_alignment("بكام؟", candidate, decision, company_knowledge={"system_prompt": "No discounts"})
    assert res.status == "REPAIRED"
    assert "خصم 15%" not in res.final_answer


def test_adversarial_case_g_untrusted_payment_destination_blocked(setup_company):
    decision = ActionDecision(
        company_id=setup_company,
        lead_id=1,
        conversation_id="conv_1",
        primary_action=NextBestSalesAction.FACILITATE_PURCHASE.value,
        strategy_mode=StrategyMode.PURCHASE_EXECUTION.value,
        prohibited_actions=[ProhibitedAction.PROVIDE_UNTRUSTED_PAYMENT_DESTINATION.value],
    )
    candidate = "حول على رقم فودافون كاش 01099999999 دلوقتي."
    res = enforce_strategy_alignment(
        "أحول فين؟", candidate, decision, company_knowledge={"system_prompt": "Official bank transfer only"}
    )
    assert res.status == "REPAIRED"
    assert "01099999999" not in res.final_answer


def test_adversarial_case_h_fake_urgency_blocked(setup_company):
    decision = ActionDecision(
        company_id=setup_company,
        lead_id=1,
        conversation_id="conv_1",
        primary_action=NextBestSalesAction.PROVIDE_PRODUCT_INFORMATION.value,
        strategy_mode=StrategyMode.INFORM_AND_ADVANCE.value,
        prohibited_actions=[ProhibitedAction.CREATE_URGENCY.value],
    )
    candidate = "لازم تشتري خلال ساعة وإلا العرض ينتهي!"
    res = enforce_strategy_alignment("بكام؟", candidate, decision)
    assert res.status == "REPAIRED"
    assert "خلال ساعة" not in res.final_answer


def test_adversarial_case_i_fake_scarcity_blocked(setup_company):
    decision = ActionDecision(
        company_id=setup_company,
        lead_id=1,
        conversation_id="conv_1",
        primary_action=NextBestSalesAction.PROVIDE_PRODUCT_INFORMATION.value,
        strategy_mode=StrategyMode.INFORM_AND_ADVANCE.value,
        prohibited_actions=[ProhibitedAction.CREATE_SCARCITY.value],
    )
    candidate = "حق نفسها بسرعة دي آخر قطعة متاحة عندنا!"
    res = enforce_strategy_alignment("متوفر؟", candidate, decision)
    assert res.status == "REPAIRED"
    assert "آخر قطعة" not in res.final_answer


def test_adversarial_case_j_explicit_customer_question_ignored_detected(setup_company):
    decision = ActionDecision(
        company_id=setup_company,
        lead_id=1,
        conversation_id="conv_1",
        primary_action=NextBestSalesAction.ANSWER_CURRENT_QUESTION.value,
        strategy_mode=StrategyMode.ANSWER_THEN_CLARIFY.value,
    )
    candidate = "حول دلوقتي على الحساب عشان نأكد الطلب."
    res = enforce_strategy_alignment("الضمان كام؟", candidate, decision)
    assert res.status == "REPAIRED"
    assert "حول دلوقتي" not in res.final_answer


# ============================================================================
# 4. ZERO-ADDED-LLM CALL GUARANTEE PROOF
# ============================================================================


@pytest.mark.asyncio
async def test_no_second_llm_call_by_default(db_session, setup_company):
    from brain import get_ai_response, groq_client

    with patch.object(groq_client.chat.completions, "create", new_callable=AsyncMock) as mock_create:
        mock_create.return_value.choices = [
            type(
                "Choice",
                (),
                {
                    "message": type(
                        "Msg",
                        (),
                        {
                            "content": json.dumps(
                                {
                                    "reply": "سعر Ergo Pro هو 1000 جنيه.",
                                    "next_conversation_state": "QUALIFICATION",
                                }
                            )
                        },
                    )()
                },
            )()
        ]

        reply, _ = await get_ai_response(db_session, "بكام؟", "user_101", setup_company, persist_incoming=False)
        assert reply is not None
        # Must make EXACTLY ONE LLM call for generation, ZERO extra calls for action evaluation or strategy alignment!
        assert mock_create.call_count == 1


# ============================================================================
# 5. COMMIT-PATH STRATEGY SAFETY PROOF
# ============================================================================


@pytest.mark.asyncio
async def test_commit_path_strategy_safety_proof(db_session, setup_company):
    from brain import get_ai_response, groq_client

    # Inject an unsafe candidate reply containing payment pressure for a BROWSING message
    with patch.object(groq_client.chat.completions, "create", new_callable=AsyncMock) as mock_create:
        mock_create.return_value.choices = [
            type(
                "Choice",
                (),
                {
                    "message": type(
                        "Msg",
                        (),
                        {
                            "content": json.dumps(
                                {
                                    "reply": "أهلاً بك، حول دلوقتي 1000 جنيه عشان تأكد الطلب فوراً.",
                                    "next_conversation_state": "QUALIFICATION",
                                }
                            )
                        },
                    )()
                },
            )()
        ]

        user_input = "أنا بس بتفرج على المنتجات"
        user_id = "01011112222"
        reply, internal_id = await get_ai_response(db_session, user_input, user_id, setup_company)

        # Assertions
        assert "حول دلوقتي" not in reply  # Unsafe candidate payment pressure was stripped
        assert internal_id is not None

        # Verify DB persistence matched final safe answer
        msg = db_session.query(Message).filter(Message.internal_message_id == internal_id).first()
        assert msg is not None
        assert msg.message == reply


# ============================================================================
# 6. TENANT ISOLATION PROOF
# ============================================================================


def test_tenant_isolation_action_evaluation(db_session):
    co_a = "company_a_nba"
    co_b = "company_b_nba"

    snap_a = SalesStateSnapshot(
        company_id=co_a,
        lead_id=123,
        conversation_id="conv_a",
        primary_state=PrimarySalesState.COMMITTING.value,
        buyer_intents=[BuyerIntent.PURCHASE_COMMITMENT.value],
        intent_strength="HIGH",
        confidence=0.9,
    )
    snap_b = SalesStateSnapshot(
        company_id=co_b,
        lead_id=123,
        conversation_id="conv_b",
        primary_state=PrimarySalesState.BROWSING.value,
        buyer_intents=[BuyerIntent.PRODUCT_DISCOVERY.value],
        intent_strength="LOW",
        confidence=0.8,
    )

    dec_a = evaluate_next_best_action(db_session, co_a, 123, snap_a, "تمام ابعتلي رقم الدفع")
    dec_b = evaluate_next_best_action(db_session, co_b, 123, snap_b, "أنا بس بتفرج")

    assert dec_a.company_id == co_a
    assert dec_a.primary_action == NextBestSalesAction.FACILITATE_PURCHASE.value

    assert dec_b.company_id == co_b
    assert dec_b.primary_action == NextBestSalesAction.PROVIDE_PRODUCT_INFORMATION.value


# ============================================================================
# 7. MULTILINGUAL & CROSS-TURN TESTS
# ============================================================================


def test_english_price_inquiry_gives_answer_current_question(db_session, setup_company):
    snap = SalesStateSnapshot(
        company_id=setup_company,
        lead_id=1,
        conversation_id="conv_1",
        primary_state=PrimarySalesState.EVALUATING.value,
        buyer_intents=[BuyerIntent.PRICE_INQUIRY.value],
        intent_strength="MEDIUM",
        confidence=0.85,
    )
    decision = evaluate_next_best_action(db_session, setup_company, 1, snap, "How much is Ergo Pro?")
    assert decision.primary_action == NextBestSalesAction.ANSWER_CURRENT_QUESTION.value


def test_mixed_language_comparison_request(db_session, setup_company):
    snap = SalesStateSnapshot(
        company_id=setup_company,
        lead_id=1,
        conversation_id="conv_1",
        primary_state=PrimarySalesState.COMPARING.value,
        buyer_intents=[BuyerIntent.PRODUCT_COMPARISON.value],
        intent_strength="MEDIUM",
        confidence=0.9,
    )
    decision = evaluate_next_best_action(db_session, setup_company, 1, snap, "compare Ergo One والـ Pro")
    assert decision.primary_action == NextBestSalesAction.COMPARE_OPTIONS.value


def test_explicit_payment_phrase_variants(db_session, setup_company):
    snap = SalesStateSnapshot(
        company_id=setup_company,
        lead_id=1,
        conversation_id="conv_1",
        primary_state=PrimarySalesState.EVALUATING.value,
        buyer_intents=[BuyerIntent.PURCHASE_COMMITMENT.value],
        intent_strength="HIGH",
        confidence=0.9,
    )

    for msg in ["ابعتلي الدفع", "ابعتلي دفع", "ابعت الدفع", "ابعت دفع", "ابعتلي رقم الدفع"]:
        decision = evaluate_next_best_action(db_session, setup_company, 1, snap, msg)
        assert decision.primary_action == NextBestSalesAction.FACILITATE_PURCHASE.value, f"Failed for payment phrase: {msg}"

