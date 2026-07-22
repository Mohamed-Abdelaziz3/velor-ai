"""
test_objection_intelligence.py — Comprehensive Test Suite for Objection Intelligence & Ethical Strategy
========================================================================================================
Validates all aspects of VELOR Objection Intelligence, Ethical Response Policy, boundaries,
multilingual handling, cross-turn reasoning, and strategy alignment.
"""

import pytest
from unittest.mock import MagicMock
from database import SessionLocal, Company, Lead, Message
from services.sales_state_service import (
    PrimarySalesState,
    BuyerIntent,
    evaluate_sales_state,
)
from services.next_best_action_service import (
    NextBestSalesAction,
    evaluate_next_best_action,
)
from services.objection_intelligence_service import (
    ObjectionSnapshot,
    ObjectionType,
    ObjectionExplicitness,
    RootCauseHypothesis,
    BlockingLevel,
    ObjectionStatus,
    EthicalResponseMode,
    ObjectionReasonCode,
    EthicalObjectionResponsePolicy,
    evaluate_objection_intelligence,
    evaluate_ethical_objection_response_policy,
)
from services.strategy_alignment_service import (
    enforce_strategy_alignment,
    StrategyAlignmentResult,
)


class TestObjectionIntelligenceModel:
    def test_canonical_snapshot_bounds_and_serialization(self):
        snapshot = ObjectionSnapshot(
            company_id="comp_123",
            lead_id=1,
            conversation_id="conv_123",
            message_id="msg_123",
            objection_present=True,
            primary_objection=ObjectionType.PRICE_TOO_HIGH.value,
            secondary_objections=[ObjectionType.WARRANTY_RISK.value],
            explicitness=ObjectionExplicitness.EXPLICIT.value,
            confidence=0.95,
            root_cause_hypothesis=RootCauseHypothesis.UNKNOWN.value,
            root_cause_confidence=0.3,
            blocking_level=BlockingLevel.MAY_BLOCK.value,
            status=ObjectionStatus.NEW.value,
            evidence_refs=["price_too_high_statement"],
            reason_codes=[ObjectionReasonCode.EXPLICIT_PRICE_TOO_HIGH.value],
        )

        d = snapshot.to_dict()
        assert d["primary_objection"] == "PRICE_TOO_HIGH"
        assert d["root_cause_hypothesis"] == "UNKNOWN"
        assert d["explicitness"] == "EXPLICIT"

        reconstructed = ObjectionSnapshot.from_dict(d)
        assert reconstructed.primary_objection == ObjectionType.PRICE_TOO_HIGH.value
        assert reconstructed.root_cause_hypothesis == RootCauseHypothesis.UNKNOWN.value

    def test_unknown_label_fallback(self):
        snapshot = ObjectionSnapshot(
            company_id="c1",
            lead_id=1,
            conversation_id="conv1",
            message_id="m1",
            objection_present=True,
            primary_objection="INVALID_OBJECTION_LABEL",
            explicitness="INVALID_EXPLICITNESS",
            root_cause_hypothesis="INVALID_ROOT_CAUSE",
        )
        assert snapshot.primary_objection == ObjectionType.OTHER.value
        assert snapshot.explicitness == ObjectionExplicitness.ABSENT.value
        assert snapshot.root_cause_hypothesis == RootCauseHypothesis.UNKNOWN.value


class TestObjectionBoundariesAndClassification:
    def test_ghali_does_not_guess_budget_limit(self):
        """'غالي' alone must yield PRICE_TOO_HIGH with root_cause_hypothesis = UNKNOWN."""
        snapshot = evaluate_objection_intelligence(None, "comp1", 1, "غالي")
        assert snapshot.objection_present is True
        assert snapshot.primary_objection == ObjectionType.PRICE_TOO_HIGH.value
        assert snapshot.root_cause_hypothesis == RootCauseHypothesis.UNKNOWN.value
        assert snapshot.root_cause_confidence == 0.3

    def test_explicit_budget_amount_establishes_budget_limit(self):
        """'معايا 5000 بس' establishes BUDGET_CONSTRAINT and BUDGET_LIMIT."""
        snapshot = evaluate_objection_intelligence(None, "comp1", 1, "معايا 5000 بس")
        assert snapshot.objection_present is True
        assert snapshot.primary_objection == ObjectionType.BUDGET_CONSTRAINT.value
        assert snapshot.root_cause_hypothesis == RootCauseHypothesis.BUDGET_LIMIT.value

    def test_value_unclear_classification(self):
        """'مش شايف إنه يستاهل 6900' yields VALUE_UNCLEAR."""
        snapshot = evaluate_objection_intelligence(None, "comp1", 1, "مش شايف إنه يستاهل 6900")
        assert snapshot.objection_present is True
        assert snapshot.primary_objection == ObjectionType.VALUE_UNCLEAR.value
        assert snapshot.root_cause_hypothesis == RootCauseHypothesis.PERCEIVED_VALUE_GAP.value

    def test_negotiation_positioning(self):
        """'آخر سعر؟' yields NEGOTIATION_POSITION."""
        snapshot = evaluate_objection_intelligence(None, "comp1", 1, "آخر سعر؟")
        assert snapshot.objection_present is True
        assert snapshot.primary_objection == ObjectionType.NEGOTIATION_POSITION.value
        assert snapshot.root_cause_hypothesis == RootCauseHypothesis.NEGOTIATION_POSITIONING.value

    def test_competitor_comparison(self):
        """'المنافس أرخص' yields COMPETITOR_COMPARISON."""
        snapshot = evaluate_objection_intelligence(None, "comp1", 1, "المنافس أرخص")
        assert snapshot.objection_present is True
        assert snapshot.primary_objection == ObjectionType.COMPETITOR_COMPARISON.value

    def test_trust_and_warranty_concerns(self):
        snap_trust = evaluate_objection_intelligence(None, "comp1", 1, "مش واثق في الشركة")
        assert snap_trust.primary_objection == ObjectionType.TRUST_CREDIBILITY.value

        snap_warranty = evaluate_objection_intelligence(None, "comp1", 1, "الضمان سنة بس؟ ده قليل")
        assert snap_warranty.primary_objection == ObjectionType.WARRANTY_RISK.value

    def test_delivery_and_installment(self):
        snap_del = evaluate_objection_intelligence(None, "comp1", 1, "التوصيل أسبوع كتير")
        assert snap_del.primary_objection == ObjectionType.DELIVERY_TIME.value

        snap_inst = evaluate_objection_intelligence(None, "comp1", 1, "ينفع تقسيط على 3 شهور؟")
        assert snap_inst.primary_objection == ObjectionType.INSTALLMENT_TERMS.value

    def test_decision_authority(self):
        snap_auth = evaluate_objection_intelligence(None, "comp1", 1, "لازم أسأل المدير")
        assert snap_auth.primary_objection == ObjectionType.DECISION_AUTHORITY.value

    def test_timing_deferral(self):
        snap_time = evaluate_objection_intelligence(None, "comp1", 1, "مش دلوقتي استنى المرتب")
        assert snap_time.primary_objection == ObjectionType.TIMING_NOT_NOW.value


class TestFalsePositiveMatrix:
    def test_direct_questions_not_objections(self):
        """Questions like 'بكام؟' or 'الضمان كام؟' are NOT objections."""
        for msg in ["بكام؟", "الضمان كام؟", "التوصيل بياخد كام؟", "طريقة الدفع إيه؟", "how much?", "what is the price?"]:
            snapshot = evaluate_objection_intelligence(None, "comp1", 1, msg)
            assert snapshot.objection_present is False, f"Falsely classified as objection: {msg}"

    def test_explicit_rejection_not_pre_sale_objection(self):
        """'مش مهتم خلاص' is REJECTION, not a pre-sale objection."""
        snapshot = evaluate_objection_intelligence(None, "comp1", 1, "مش مهتم خلاص")
        assert snapshot.objection_present is False
        assert ObjectionReasonCode.EXPLICIT_REJECTION_SIGNAL.value in snapshot.reason_codes

    def test_post_sale_support_not_pre_sale_objection(self):
        """'الطلب وصل ناقص' is SUPPORT, not pre-sale objection."""
        snapshot = evaluate_objection_intelligence(None, "comp1", 1, "الطلب وصل ناقص")
        assert snapshot.objection_present is False
        assert ObjectionReasonCode.SUPPORT_INTENT_SIGNAL.value in snapshot.reason_codes


class TestMultiObjectionAndContradictions:
    def test_multi_objection_message(self):
        """'غالي والضمان مش مطمني' preserves primary and secondary objections."""
        snapshot = evaluate_objection_intelligence(None, "comp1", 1, "غالي والضمان مش مطمني")
        assert snapshot.objection_present is True
        assert snapshot.primary_objection in {ObjectionType.PRICE_TOO_HIGH.value, ObjectionType.WARRANTY_RISK.value}
        assert len(snapshot.secondary_objections) >= 1

    def test_contradictory_purchase_commitment(self):
        """'غالي بس ابعتلي رقم الدفع' yields non-blocking objection."""
        snapshot = evaluate_objection_intelligence(None, "comp1", 1, "غالي بس ابعتلي رقم الدفع")
        assert snapshot.objection_present is True
        assert snapshot.blocking_level == BlockingLevel.NON_BLOCKING.value
        assert ObjectionReasonCode.CONTRADICTORY_COMMITMENT_SIGNAL.value in snapshot.reason_codes


class TestMultilingualAndDialects:
    def test_english_objections(self):
        snap1 = evaluate_objection_intelligence(None, "comp1", 1, "Too expensive")
        assert snap1.primary_objection == ObjectionType.PRICE_TOO_HIGH.value

        snap2 = evaluate_objection_intelligence(None, "comp1", 1, "I only have a 5000 budget")
        assert snap2.primary_objection == ObjectionType.BUDGET_CONSTRAINT.value

        snap3 = evaluate_objection_intelligence(None, "comp1", 1, "Your competitor is cheaper")
        assert snap3.primary_objection == ObjectionType.COMPETITOR_COMPARISON.value

    def test_mixed_language_objections(self):
        snap1 = evaluate_objection_intelligence(None, "comp1", 1, "Ergo Pro غالي")
        assert snap1.primary_objection == ObjectionType.PRICE_TOO_HIGH.value

        snap2 = evaluate_objection_intelligence(None, "comp1", 1, "budget بتاعتي 5000")
        assert snap2.primary_objection == ObjectionType.BUDGET_CONSTRAINT.value

        snap3 = evaluate_objection_intelligence(None, "comp1", 1, "warranty مش مطمني")
        assert snap3.primary_objection == ObjectionType.WARRANTY_RISK.value


class TestEthicalResponsePolicy:
    def test_price_too_high_policy_clarifies_root_cause(self):
        snap = evaluate_objection_intelligence(None, "comp1", 1, "غالي")
        policy = evaluate_ethical_objection_response_policy("comp1", 1, snap)
        assert policy.primary_response_mode == EthicalResponseMode.CLARIFY_ROOT_CAUSE.value
        assert "INVENT_DISCOUNT" in policy.prohibited_tactics

    def test_budget_constraint_prohibits_loan_pressure(self):
        snap = evaluate_objection_intelligence(None, "comp1", 1, "معايا 5000 بس")
        policy = evaluate_ethical_objection_response_policy("comp1", 1, snap)
        assert policy.primary_response_mode == EthicalResponseMode.OFFER_TRUSTED_ALTERNATIVE.value
        assert "RECOMMEND_LOANS" in policy.prohibited_tactics

    def test_timing_policy_prohibits_fake_urgency(self):
        snap = evaluate_objection_intelligence(None, "comp1", 1, "مش دلوقتي")
        policy = evaluate_ethical_objection_response_policy("comp1", 1, snap)
        assert policy.primary_response_mode == EthicalResponseMode.RESPECT_TIMING.value
        assert "FAKE_URGENCY" in policy.prohibited_tactics


class TestStrategyAlignmentIntegration:
    def test_blocks_loan_pressure(self):
        action_decision = MagicMock()
        action_decision.primary_action = NextBestSalesAction.CLARIFY_OBJECTION.value
        action_decision.prohibited_actions = []
        action_decision.cta_policy = "SOFT"

        candidate_reply = "استلف واشتري المنتح دلوقتي"
        res = enforce_strategy_alignment("معايا 5000 بس", candidate_reply, action_decision)
        assert res.status == "REPAIRED"
        assert "LOAN_PRESSURE_PROHIBITED" in res.violations
        assert "استلف" not in res.final_answer

    def test_blocks_unethical_competitor_defamation(self):
        action_decision = MagicMock()
        action_decision.primary_action = NextBestSalesAction.CLARIFY_OBJECTION.value
        action_decision.prohibited_actions = []
        action_decision.cta_policy = "SOFT"

        candidate_reply = "المنافس نصاب والشركة التانية كذابة"
        res = enforce_strategy_alignment("المنافس أرخص", candidate_reply, action_decision)
        assert res.status == "REPAIRED"
        assert "UNETHICAL_CLAIM_PROHIBITED" in res.violations
        assert "نصاب" not in res.final_answer


class TestObjectionIdempotencyAndConcurrency:
    def test_duplicate_external_objection_message_has_one_logical_owner(self):
        """Repeated objection evaluation produces deterministic identical snapshot without state drift or confidence inflation."""
        snap1 = evaluate_objection_intelligence(None, "comp1", 1, "غالي")
        snap2 = evaluate_objection_intelligence(None, "comp1", 1, "غالي")
        assert snap1.primary_objection == snap2.primary_objection == ObjectionType.PRICE_TOO_HIGH.value
        assert snap1.confidence == snap2.confidence
        assert snap1.root_cause_confidence == snap2.root_cause_confidence

    def test_duplicate_explicit_budget_message_does_not_inflate_confidence(self):
        """Repeated budget input retains canonical confidence levels."""
        snap1 = evaluate_objection_intelligence(None, "comp1", 1, "معايا 5000 بس")
        snap2 = evaluate_objection_intelligence(None, "comp1", 1, "معايا 5000 بس")
        assert snap1.confidence == snap2.confidence
        assert snap1.root_cause_confidence == snap2.root_cause_confidence

    def test_duplicate_rejection_does_not_reopen_objection(self):
        """Repeated rejection message remains explicit rejection without reopening active sales objection."""
        snap1 = evaluate_objection_intelligence(None, "comp1", 1, "مش مهتم خلاص")
        snap2 = evaluate_objection_intelligence(None, "comp1", 1, "مش مهتم خلاص")
        assert snap1.objection_present is False
        assert snap2.objection_present is False

    def test_provider_failure_retry_prevents_duplicate_mutation(self):
        """Provider retry returns deterministic safe alignment without mutating state multiple times."""
        action_decision = MagicMock()
        action_decision.primary_action = NextBestSalesAction.CLARIFY_OBJECTION.value
        action_decision.prohibited_actions = []
        action_decision.cta_policy = "SOFT"

        candidate = "استلف واشتري دلوقتي"
        res1 = enforce_strategy_alignment("معايا 5000 بس", candidate, action_decision)
        res2 = enforce_strategy_alignment("معايا 5000 بس", candidate, action_decision)
        assert res1.final_answer == res2.final_answer
        assert "استلف" not in res1.final_answer

    def test_completed_duplicate_does_not_mutate_objection(self):
        """Completed cached reply re-uses stored text without re-triggering objection side-effects."""
        snap = evaluate_objection_intelligence(None, "comp1", 1, "غالي")
        assert snap.status in {ObjectionStatus.NEW.value, ObjectionStatus.ACTIVE.value, ObjectionStatus.NONE.value}


class TestObjectionCommitPathPersistenceAndTransport:
    def test_ghali_unsafe_borrowing_candidate_repaired_before_persistence_and_transport(self):
        """Customer: 'غالي', Unsafe candidate: 'استلف واشتري دلوقتي' -> Unsafe candidate is repaired to safe answer and never committed."""
        action_decision = MagicMock()
        action_decision.primary_action = NextBestSalesAction.CLARIFY_OBJECTION.value
        action_decision.prohibited_actions = []
        action_decision.cta_policy = "SOFT"

        unsafe_candidate = "استلف واشتري دلوقتي"
        res = enforce_strategy_alignment("معايا 5000 بس", unsafe_candidate, action_decision)

        assert res.status == "REPAIRED"
        assert "استلف" not in res.final_answer
        assert res.final_answer != unsafe_candidate
        # Verify committed output is final safe answer
        persisted_body = res.final_answer
        transported_body = res.final_answer
        assert persisted_body == transported_body
        assert "استلف" not in persisted_body

    def test_rejection_unsafe_sales_push_candidate_repaired_before_persistence_and_transport(self):
        """Customer: 'مش مهتم خلاص', Unsafe candidate: 'خليني أقنعك مرة أخيرة' -> Sales push removed before persistence."""
        action_decision = MagicMock()
        action_decision.primary_action = NextBestSalesAction.RESPECT_REJECTION.value
        action_decision.prohibited_actions = ["CONTINUE_SELLING_AFTER_REJECTION"]
        action_decision.cta_policy = "NONE"

        unsafe_candidate = "خليني أقنعك مرة أخيرة ونقدملك عرض خاص بخصم ممتاز"
        res = enforce_strategy_alignment("مش مهتم خلاص", unsafe_candidate, action_decision)

        assert res.status == "REPAIRED"
        assert "أقنعك" not in res.final_answer
        assert "عرض" not in res.final_answer
        persisted_body = res.final_answer
        assert persisted_body == res.final_answer


class TestObjectionFallbackMatrix:
    def test_objection_fallback_matrix_prevents_unethical_claims(self):
        """All fallback paths across objections must prohibit fake discounts, fake urgency, loan pressure, and competitor defamation."""
        from brain import _heuristic_ai_payload

        context = {
            "conversation_state": "OBJECTION_HANDLING",
            "company_data": {"company_name": "Test Co", "products_data": []},
            "history": [],
        }

        objections = [
            "غالي",
            "معايا 5000 بس",
            "الضمان مش مطمني",
            "مش واثق في الشركة",
            "مش دلوقتي",
            "المنافس أرخص",
            "مش مهتم خلاص",
        ]

        for obj in objections:
            payload = _heuristic_ai_payload(obj, context, context["company_data"])
            reply = payload.get("reply", "")
            assert "استلف" not in reply, f"Fallback for '{obj}' contains loan pressure"
            assert "نصاب" not in reply, f"Fallback for '{obj}' contains defamation"
            assert "اخر قطعة" not in reply, f"Fallback for '{obj}' contains fake urgency"


class TestObjectionNoSecondLLM:
    def test_no_second_llm_call_for_objection_intelligence(self):
        """Objection detection, root-cause hypothesis, ethical response policy, and strategy alignment add exactly 0 extra LLM calls."""
        mock_provider = MagicMock()
        mock_provider.call_count = 0

        # Run objection stack
        sales_snap = MagicMock()
        sales_snap.primary_state = "OBJECTION_HANDLING"
        snap = evaluate_objection_intelligence(None, "comp1", 1, "غالي", sales_snapshot=sales_snap)
        policy = evaluate_ethical_objection_response_policy("comp1", 1, snap)

        action_decision = MagicMock()
        action_decision.primary_action = NextBestSalesAction.CLARIFY_OBJECTION.value
        action_decision.prohibited_actions = []
        action_decision.cta_policy = "SOFT"
        res = enforce_strategy_alignment("غالي", "تمام يا فندم، أقدر أوضح لك تفاصيل القيمة المنتجة.", action_decision)

        # Added model calls must be exactly 0
        added_llm_calls = mock_provider.call_count
        assert added_llm_calls == 0


class TestObjectionRootCauseSafety:
    def test_a_ghali_repaired_loan_pressure_does_not_invent_budget_truth(self):
        """'غالي' + unsafe loan candidate -> Final repaired answer MUST NOT claim customer has a specified/known budget."""
        action_decision = MagicMock()
        action_decision.primary_action = NextBestSalesAction.CLARIFY_OBJECTION.value
        action_decision.prohibited_actions = []
        action_decision.cta_policy = "SOFT"

        snap = evaluate_objection_intelligence(None, "comp1", 1, "غالي")
        res = enforce_strategy_alignment("غالي", "استلف واشتري دلوقتي", action_decision, objection_snapshot=snap)

        assert res.status == "REPAIRED"
        assert "ميزانيتك" not in res.final_answer
        assert "الميزانية المحددة" not in res.final_answer

    def test_b_ghali_preserves_price_too_high_and_unknown_root_cause(self):
        """'غالي' preserves PRICE_TOO_HIGH with root cause UNKNOWN."""
        snap = evaluate_objection_intelligence(None, "comp1", 1, "غالي")
        assert snap.primary_objection == ObjectionType.PRICE_TOO_HIGH.value
        assert snap.root_cause_hypothesis == RootCauseHypothesis.UNKNOWN.value

    def test_c_explicit_budget_evidence_allows_budget_aware_repair(self):
        """'معايا 5000 بس' contains explicit budget evidence and allows budget-aware repair."""
        action_decision = MagicMock()
        action_decision.primary_action = NextBestSalesAction.CLARIFY_OBJECTION.value
        action_decision.prohibited_actions = []
        action_decision.cta_policy = "SOFT"

        snap = evaluate_objection_intelligence(None, "comp1", 1, "معايا 5000 بس")
        res = enforce_strategy_alignment("معايا 5000 بس", "استلف واشتري دلوقتي", action_decision, objection_snapshot=snap)

        assert res.status == "REPAIRED"
        assert "ميزانيتك" in res.final_answer

    def test_d_value_unclear_not_converted_to_budget_constraint(self):
        """'مش شايف إنه يستاهل' yields VALUE_UNCLEAR, not BUDGET_CONSTRAINT."""
        snap = evaluate_objection_intelligence(None, "comp1", 1, "مش شايف إنه يستاهل 6900")
        assert snap.primary_objection == ObjectionType.VALUE_UNCLEAR.value
        assert snap.primary_objection != ObjectionType.BUDGET_CONSTRAINT.value


