"""
next_best_action_service.py — Canonical Next Best Sales Action & Conversation Strategy Policy
=============================================================================================
Provides one canonical, evidence-backed, tenant-safe decision layer for VELOR backend.

Key Principles:
1. Deterministic-first action selection based on SalesStateSnapshot, current customer input,
   buyer intents, intent strength, confidence, momentum, and evidence.
2. Hard Priority Ordering:
   Priority 1: Human Takeover / Auto Reply Control -> PAUSE_FOR_HUMAN_TAKEOVER
   Priority 2: Explicit Rejection / Cancellation -> RESPECT_REJECTION
   Priority 3: Support / Post-Sale Intent -> ROUTE_POST_SALE_SUPPORT
   Priority 4: Active Purchase Execution -> FACILITATE_PURCHASE / COLLECT_ORDER_DETAILS
   Priority 5: Current Explicit Question -> ANSWER_CURRENT_QUESTION / COMPARE_OPTIONS / PROVIDE_PRODUCT_INFORMATION
   Priority 6: Unresolved Factual Safety -> REQUEST_MISSING_INFORMATION / CLARIFY_CUSTOMER_NEED
   Priority 7: State & Intent Strategy Matrix
   Priority 8: Optional Advancement
3. Bounded enums for Action, StrategyMode, QuestionPolicy, CtaPolicy, PressureCeiling, ResponseStep, ProhibitedAction.
4. Tenant isolation across all lookups.
"""

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy.orm import Session

from services.sales_state_service import (
    BuyerIntent,
    IntentStrength,
    Momentum,
    PrimarySalesState,
    ReasonCode,
    SalesStateSnapshot,
    evaluate_sales_state,
    _fold_arabic,
    _matches_any,
)

log = logging.getLogger("adam.next_best_action")

MODEL_VERSION = "velor_nba_v2_commercial_execution"


class NextBestSalesAction(str, Enum):
    NO_ACTION = "NO_ACTION"
    ACKNOWLEDGE_AND_HOLD = "ACKNOWLEDGE_AND_HOLD"
    ANSWER_CURRENT_QUESTION = "ANSWER_CURRENT_QUESTION"
    CLARIFY_CUSTOMER_NEED = "CLARIFY_CUSTOMER_NEED"
    ASK_ONE_DECISION_CRITERION = "ASK_ONE_DECISION_CRITERION"
    PROVIDE_PRODUCT_INFORMATION = "PROVIDE_PRODUCT_INFORMATION"
    COMPARE_OPTIONS = "COMPARE_OPTIONS"
    CLARIFY_OBJECTION = "CLARIFY_OBJECTION"
    RESPOND_TO_SUPPORTED_CONCERN = "RESPOND_TO_SUPPORTED_CONCERN"
    NEGOTIATE_WITHIN_TRUSTED_TERMS = "NEGOTIATE_WITHIN_TRUSTED_TERMS"
    FACILITATE_PURCHASE = "FACILITATE_PURCHASE"
    COLLECT_ORDER_DETAILS = "COLLECT_ORDER_DETAILS"
    CONFIRM_NEXT_STEP = "CONFIRM_NEXT_STEP"
    REQUEST_MISSING_INFORMATION = "REQUEST_MISSING_INFORMATION"
    RESPECT_REJECTION = "RESPECT_REJECTION"
    WAIT_FOR_CUSTOMER = "WAIT_FOR_CUSTOMER"
    REACTIVATION_RESPONSE = "REACTIVATION_RESPONSE"
    ROUTE_POST_SALE_SUPPORT = "ROUTE_POST_SALE_SUPPORT"
    OFFER_HUMAN_HANDOFF = "OFFER_HUMAN_HANDOFF"
    PAUSE_FOR_HUMAN_TAKEOVER = "PAUSE_FOR_HUMAN_TAKEOVER"


class StrategyMode(str, Enum):
    HOLD = "HOLD"
    ANSWER_ONLY = "ANSWER_ONLY"
    ANSWER_THEN_CLARIFY = "ANSWER_THEN_CLARIFY"
    DISCOVER_NEED = "DISCOVER_NEED"
    INFORM_AND_ADVANCE = "INFORM_AND_ADVANCE"
    COMPARE_AND_NARROW = "COMPARE_AND_NARROW"
    CLARIFY_CONCERN = "CLARIFY_CONCERN"
    SUPPORT_DECISION = "SUPPORT_DECISION"
    PURCHASE_EXECUTION = "PURCHASE_EXECUTION"
    RESPECT_AND_CLOSE = "RESPECT_AND_CLOSE"
    REACTIVATION_CONTEXT = "REACTIVATION_CONTEXT"
    POST_SALE_SUPPORT = "POST_SALE_SUPPORT"
    HUMAN_HANDOFF = "HUMAN_HANDOFF"


class QuestionPolicy(str, Enum):
    NO_QUESTION = "NO_QUESTION"
    ONE_REQUIRED_CLARIFIER = "ONE_REQUIRED_CLARIFIER"
    ONE_OPTIONAL_QUESTION = "ONE_OPTIONAL_QUESTION"
    ONE_DECISION_QUESTION = "ONE_DECISION_QUESTION"


class CtaPolicy(str, Enum):
    NONE = "NONE"
    SOFT = "SOFT"
    DIRECT = "DIRECT"
    EXECUTION_ONLY = "EXECUTION_ONLY"


class PressureCeiling(str, Enum):
    NONE = "NONE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"


class ResponseStep(str, Enum):
    ACKNOWLEDGE = "ACKNOWLEDGE"
    ANSWER_EXPLICIT_REQUEST = "ANSWER_EXPLICIT_REQUEST"
    STATE_SUPPORTED_FACTS = "STATE_SUPPORTED_FACTS"
    ASK_ONE_CLARIFIER = "ASK_ONE_CLARIFIER"
    ASK_ONE_DECISION_CRITERION = "ASK_ONE_DECISION_CRITERION"
    COMPARE_RELEVANT_OPTIONS = "COMPARE_RELEVANT_OPTIONS"
    ADDRESS_SUPPORTED_CONCERN = "ADDRESS_SUPPORTED_CONCERN"
    CONFIRM_SELECTION = "CONFIRM_SELECTION"
    REQUEST_REQUIRED_ORDER_DETAIL = "REQUEST_REQUIRED_ORDER_DETAIL"
    PROVIDE_TRUSTED_NEXT_STEP = "PROVIDE_TRUSTED_NEXT_STEP"
    OFFER_OPTIONAL_CONTINUATION = "OFFER_OPTIONAL_CONTINUATION"
    SOFT_CTA = "SOFT_CTA"
    DIRECT_EXECUTION_CTA = "DIRECT_EXECUTION_CTA"
    RESPECT_REJECTION = "RESPECT_REJECTION"
    STOP_SELLING = "STOP_SELLING"


class ProhibitedAction(str, Enum):
    PUSH_FOR_PAYMENT = "PUSH_FOR_PAYMENT"
    CREATE_URGENCY = "CREATE_URGENCY"
    CREATE_SCARCITY = "CREATE_SCARCITY"
    OFFER_UNTRUSTED_DISCOUNT = "OFFER_UNTRUSTED_DISCOUNT"
    PROVIDE_UNTRUSTED_PAYMENT_DESTINATION = "PROVIDE_UNTRUSTED_PAYMENT_DESTINATION"
    CONTINUE_SELLING_AFTER_REJECTION = "CONTINUE_SELLING_AFTER_REJECTION"
    RESET_PURCHASE_TO_DISCOVERY = "RESET_PURCHASE_TO_DISCOVERY"
    FORCE_SALES_ON_SUPPORT = "FORCE_SALES_ON_SUPPORT"


class ActionReasonCode(str, Enum):
    CURRENT_EXPLICIT_QUESTION = "CURRENT_EXPLICIT_QUESTION"
    EXPLICIT_COMPARISON_REQUEST = "EXPLICIT_COMPARISON_REQUEST"
    EXPLICIT_PAYMENT_NEXT_STEP = "EXPLICIT_PAYMENT_NEXT_STEP"
    EXPLICIT_REJECTION = "EXPLICIT_REJECTION"
    LOW_CONFIDENCE_INTERPRETATION = "LOW_CONFIDENCE_INTERPRETATION"
    PROGRESSING_MOMENTUM = "PROGRESSING_MOMENTUM"
    REGRESSING_MOMENTUM = "REGRESSING_MOMENTUM"
    PRICE_OBJECTION_PRESENT = "PRICE_OBJECTION_PRESENT"
    NEGOTIATION_INTENT = "NEGOTIATION_INTENT"
    SUPPORT_INTENT = "SUPPORT_INTENT"
    UNRESOLVED_FACTUAL_REQUIREMENT = "UNRESOLVED_FACTUAL_REQUIREMENT"
    NO_TRUSTED_COMMERCIAL_TERM = "NO_TRUSTED_COMMERCIAL_TERM"
    HUMAN_TAKEOVER_ACTIVE = "HUMAN_TAKEOVER_ACTIVE"
    AUTO_REPLY_DISABLED = "AUTO_REPLY_DISABLED"
    REACTIVATION_EVENT = "REACTIVATION_EVENT"
    RECOMMENDATION_CLARIFICATION_REQUIRED = "RECOMMENDATION_CLARIFICATION_REQUIRED"


@dataclass
class ActionDecision:
    company_id: str
    lead_id: Optional[int]
    conversation_id: Optional[str]
    primary_action: str
    strategy_mode: str
    secondary_actions: List[str] = field(default_factory=list)
    response_steps: List[str] = field(default_factory=list)
    question_policy: str = QuestionPolicy.ONE_OPTIONAL_QUESTION.value
    cta_policy: str = CtaPolicy.SOFT.value
    pressure_ceiling: str = PressureCeiling.LOW.value
    confidence: float = 0.8
    state_snapshot_ref: Optional[str] = None
    evidence_refs: List[str] = field(default_factory=list)
    reason_codes: List[str] = field(default_factory=list)
    prohibited_actions: List[str] = field(default_factory=list)
    observed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    policy_version: str = MODEL_VERSION
    commercial_objective: str = "DO_NOT_ADVANCE"
    selling_strategy: str = "DO_NOT_PUSH"
    next_move: str = "ACKNOWLEDGE_AND_HOLD"
    owner_explanation: str = ""
    escalation_required: bool = False
    escalation: Dict[str, Any] = field(default_factory=dict)
    decision_evidence: List[Dict[str, Any]] = field(default_factory=list)

    def __post_init__(self):
        self.confidence = max(0.0, min(1.0, float(self.confidence)))

        valid_actions = {a.value for a in NextBestSalesAction}
        if self.primary_action not in valid_actions:
            log.warning("Invalid primary_action %s, falling back to ACKNOWLEDGE_AND_HOLD", self.primary_action)
            self.primary_action = NextBestSalesAction.ACKNOWLEDGE_AND_HOLD.value

        cleaned_secondaries = []
        for sec in self.secondary_actions:
            if sec in valid_actions and sec not in cleaned_secondaries:
                cleaned_secondaries.append(sec)
        self.secondary_actions = cleaned_secondaries

        valid_modes = {s.value for s in StrategyMode}
        if self.strategy_mode not in valid_modes:
            self.strategy_mode = StrategyMode.INFORM_AND_ADVANCE.value

        valid_q = {q.value for q in QuestionPolicy}
        if self.question_policy not in valid_q:
            self.question_policy = QuestionPolicy.ONE_OPTIONAL_QUESTION.value

        valid_cta = {c.value for c in CtaPolicy}
        if self.cta_policy not in valid_cta:
            self.cta_policy = CtaPolicy.SOFT.value

        valid_press = {p.value for p in PressureCeiling}
        if self.pressure_ceiling not in valid_press:
            self.pressure_ceiling = PressureCeiling.LOW.value

        valid_steps = {s.value for s in ResponseStep}
        self.response_steps = [s for s in self.response_steps if s in valid_steps]

        valid_prohibited = {p.value for p in ProhibitedAction}
        self.prohibited_actions = [p for p in self.prohibited_actions if p in valid_prohibited]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ActionDecision":
        return cls(
            company_id=data.get("company_id", ""),
            lead_id=data.get("lead_id"),
            conversation_id=data.get("conversation_id"),
            primary_action=data.get("primary_action", NextBestSalesAction.ACKNOWLEDGE_AND_HOLD.value),
            strategy_mode=data.get("strategy_mode", StrategyMode.INFORM_AND_ADVANCE.value),
            secondary_actions=data.get("secondary_actions", []),
            response_steps=data.get("response_steps", []),
            question_policy=data.get("question_policy", QuestionPolicy.ONE_OPTIONAL_QUESTION.value),
            cta_policy=data.get("cta_policy", CtaPolicy.SOFT.value),
            pressure_ceiling=data.get("pressure_ceiling", PressureCeiling.LOW.value),
            confidence=data.get("confidence", 0.8),
            state_snapshot_ref=data.get("state_snapshot_ref"),
            evidence_refs=data.get("evidence_refs", []),
            reason_codes=data.get("reason_codes", []),
            prohibited_actions=data.get("prohibited_actions", []),
            observed_at=data.get("observed_at", datetime.now(timezone.utc).isoformat()),
            policy_version=data.get("policy_version", MODEL_VERSION),
            commercial_objective=data.get("commercial_objective", "DO_NOT_ADVANCE"),
            selling_strategy=data.get("selling_strategy", "DO_NOT_PUSH"),
            next_move=data.get("next_move", "ACKNOWLEDGE_AND_HOLD"),
            owner_explanation=data.get("owner_explanation", ""),
            escalation_required=bool(data.get("escalation_required", False)),
            escalation=data.get("escalation", {}),
            decision_evidence=data.get("decision_evidence", []),
        )


def _is_support_intent(raw_text: str) -> bool:
    return _matches_any(
        raw_text,
        [
            r"الطلب\s+وصل\s+ناقص",
            r"الطلب\s+تالف",
            r"عايز\s+أرجع",
            r"عايز\s+ارجع",
            r"عايز\s+استبدال",
            r"مشكلة\s+في\s+المنتج",
            r"فين\s+الشحنة",
            r"تأخير\s+الشحن",
            r"دعم\s+فني",
            r"خدمة\s+العملاء",
            r"where\s+is\s+my\s+shipment",
            r"my\s+order\s+arrived\s+incomplete",
            r"refund",
            r"return\s+product",
            r"customer\s+support",
        ],
    )


def _evaluate_base_next_best_action(
    db: Session,
    company_id: str,
    lead_id: Optional[int],
    sales_snapshot: Optional[SalesStateSnapshot] = None,
    current_message_text: str = "",
    evidence_refs: Optional[List[str]] = None,
    human_takeover_active: bool = False,
    auto_reply_disabled: bool = False,
    objection_snapshot: Optional[Any] = None,
    recommendation_decision: Optional[Any] = None,
    preference_memory: Optional[Any] = None,
    relationship_snapshot: Optional[Any] = None,
) -> ActionDecision:
    """
    Main entry point for Next Best Sales Action & Strategy Policy evaluation.
    Deterministically converts buyer state, intents, explicit requests, evidence, objection snapshot, and recommendation decision into ActionDecision.
    """

    # Ensure sales_snapshot is present
    if not sales_snapshot:
        sales_snapshot = evaluate_sales_state(
            db, company_id, lead_id, current_message_text, evidence_refs=evidence_refs
        )

    raw_text = current_message_text or ""
    primary_state = sales_snapshot.primary_state
    buyer_intents = set(sales_snapshot.buyer_intents)
    confidence = sales_snapshot.confidence
    intent_strength = sales_snapshot.intent_strength
    momentum = sales_snapshot.momentum

    reason_codes: List[str] = list(sales_snapshot.reason_codes or [])
    safe_evidence_refs: List[str] = list(sales_snapshot.evidence_refs or [])

    if objection_snapshot and getattr(objection_snapshot, "objection_present", False):
        if ActionReasonCode.PRICE_OBJECTION_PRESENT.value not in reason_codes:
            reason_codes.append(ActionReasonCode.PRICE_OBJECTION_PRESENT.value)

    # Priority 1: Human Takeover / Auto Reply Gate
    if human_takeover_active or auto_reply_disabled:
        reason = ActionReasonCode.HUMAN_TAKEOVER_ACTIVE.value if human_takeover_active else ActionReasonCode.AUTO_REPLY_DISABLED.value
        return ActionDecision(
            company_id=company_id,
            lead_id=lead_id,
            conversation_id=sales_snapshot.conversation_id,
            primary_action=NextBestSalesAction.PAUSE_FOR_HUMAN_TAKEOVER.value,
            strategy_mode=StrategyMode.HUMAN_HANDOFF.value,
            question_policy=QuestionPolicy.NO_QUESTION.value,
            cta_policy=CtaPolicy.NONE.value,
            pressure_ceiling=PressureCeiling.NONE.value,
            confidence=1.0,
            state_snapshot_ref=sales_snapshot.primary_state,
            evidence_refs=safe_evidence_refs,
            reason_codes=[reason],
            prohibited_actions=[
                ProhibitedAction.PUSH_FOR_PAYMENT.value,
                ProhibitedAction.CONTINUE_SELLING_AFTER_REJECTION.value,
            ],
            policy_version=MODEL_VERSION,
        )

    # Priority 2: Explicit Rejection / Cancellation
    if primary_state == PrimarySalesState.LOST.value or BuyerIntent.CANCELLATION_OR_REJECTION.value in buyer_intents:
        reason_codes.append(ActionReasonCode.EXPLICIT_REJECTION.value)
        return ActionDecision(
            company_id=company_id,
            lead_id=lead_id,
            conversation_id=sales_snapshot.conversation_id,
            primary_action=NextBestSalesAction.RESPECT_REJECTION.value,
            strategy_mode=StrategyMode.RESPECT_AND_CLOSE.value,
            response_steps=[ResponseStep.RESPECT_REJECTION.value, ResponseStep.STOP_SELLING.value],
            question_policy=QuestionPolicy.NO_QUESTION.value,
            cta_policy=CtaPolicy.NONE.value,
            pressure_ceiling=PressureCeiling.NONE.value,
            confidence=max(confidence, 0.95),
            state_snapshot_ref=primary_state,
            evidence_refs=safe_evidence_refs,
            reason_codes=list(set(reason_codes)),
            prohibited_actions=[
                ProhibitedAction.PUSH_FOR_PAYMENT.value,
                ProhibitedAction.CREATE_URGENCY.value,
                ProhibitedAction.CREATE_SCARCITY.value,
                ProhibitedAction.OFFER_UNTRUSTED_DISCOUNT.value,
                ProhibitedAction.CONTINUE_SELLING_AFTER_REJECTION.value,
            ],
            policy_version=MODEL_VERSION,
        )

    # Priority 3: Support / Post-Sale Intent
    if BuyerIntent.SUPPORT_OR_POST_SALE.value in buyer_intents or _is_support_intent(raw_text):
        reason_codes.append(ActionReasonCode.SUPPORT_INTENT.value)
        return ActionDecision(
            company_id=company_id,
            lead_id=lead_id,
            conversation_id=sales_snapshot.conversation_id,
            primary_action=NextBestSalesAction.ROUTE_POST_SALE_SUPPORT.value,
            strategy_mode=StrategyMode.POST_SALE_SUPPORT.value,
            response_steps=[ResponseStep.ACKNOWLEDGE.value, ResponseStep.STATE_SUPPORTED_FACTS.value],
            question_policy=QuestionPolicy.NO_QUESTION.value,
            cta_policy=CtaPolicy.NONE.value,
            pressure_ceiling=PressureCeiling.NONE.value,
            confidence=max(confidence, 0.90),
            state_snapshot_ref=primary_state,
            evidence_refs=safe_evidence_refs,
            reason_codes=list(set(reason_codes)),
            prohibited_actions=[
                ProhibitedAction.PUSH_FOR_PAYMENT.value,
                ProhibitedAction.FORCE_SALES_ON_SUPPORT.value,
                ProhibitedAction.CREATE_URGENCY.value,
            ],
            policy_version=MODEL_VERSION,
        )

    # Priority 4: Active Purchase Execution (Explicit current message payment commitment or COMMITTING state with payment inquiry)
    is_explicit_payment_msg = _matches_any(
        raw_text,
        [
            r"ابعتلي\s+رقم\s+الدفع",
            r"ابعت(لي)?\s+(ال)?دفع",
            r"ارسل\s+رقم\s+الدفع",
            r"ابعثلي\s+رقم\s+الدفع",
            r"رقم\s+الحساب",
            r"احول\s+فين",
            r"أحول\s+فين",
            r"أحول\s+على\s+رقم\s+إيه",
            r"send\s+(me\s+)?payment\s+(link|number|details)",
            r"where\s+do\s+i\s+pay",
            r"how\s+to\s+pay",
            r"هحول\s+دلوقتي",
            r"تمام\s+هات\s+واحد",
            r"خلاص\s+هطلب",
        ],
    )

    if is_explicit_payment_msg or primary_state in {PrimarySalesState.COMMITTING.value, PrimarySalesState.READY_TO_BUY.value}:
        reason_codes.append(ActionReasonCode.EXPLICIT_PAYMENT_NEXT_STEP.value)
        return ActionDecision(
            company_id=company_id,
            lead_id=lead_id,
            conversation_id=sales_snapshot.conversation_id,
            primary_action=NextBestSalesAction.FACILITATE_PURCHASE.value,
            strategy_mode=StrategyMode.PURCHASE_EXECUTION.value,
            secondary_actions=[NextBestSalesAction.COLLECT_ORDER_DETAILS.value],
            response_steps=[
                ResponseStep.CONFIRM_SELECTION.value,
                ResponseStep.PROVIDE_TRUSTED_NEXT_STEP.value,
                ResponseStep.REQUEST_REQUIRED_ORDER_DETAIL.value,
            ],
            question_policy=QuestionPolicy.ONE_REQUIRED_CLARIFIER.value,
            cta_policy=CtaPolicy.EXECUTION_ONLY.value,
            pressure_ceiling=PressureCeiling.MEDIUM.value,
            confidence=max(confidence, 0.90),
            state_snapshot_ref=primary_state,
            evidence_refs=safe_evidence_refs,
            reason_codes=list(set(reason_codes)),
            prohibited_actions=[
                ProhibitedAction.RESET_PURCHASE_TO_DISCOVERY.value,
                ProhibitedAction.OFFER_UNTRUSTED_DISCOUNT.value,
                ProhibitedAction.PROVIDE_UNTRUSTED_PAYMENT_DESTINATION.value,
                ProhibitedAction.CREATE_URGENCY.value,
                ProhibitedAction.CREATE_SCARCITY.value,
            ],
            policy_version=MODEL_VERSION,
        )

    # Recommendation Decision Composition: If recommendation requires clarifying questions
    if recommendation_decision and getattr(recommendation_decision, "outcome", None) == "ASK_CLARIFYING_QUESTION":
        reason_codes.append(ActionReasonCode.RECOMMENDATION_CLARIFICATION_REQUIRED.value)
        return ActionDecision(
            company_id=company_id,
            lead_id=lead_id,
            conversation_id=sales_snapshot.conversation_id,
            primary_action=NextBestSalesAction.ASK_ONE_DECISION_CRITERION.value,
            strategy_mode=StrategyMode.DISCOVER_NEED.value,
            secondary_actions=[NextBestSalesAction.CLARIFY_CUSTOMER_NEED.value],
            response_steps=[
                ResponseStep.ACKNOWLEDGE.value,
                ResponseStep.ASK_ONE_DECISION_CRITERION.value,
            ],
            question_policy=QuestionPolicy.ONE_DECISION_QUESTION.value,
            cta_policy=CtaPolicy.SOFT.value,
            pressure_ceiling=PressureCeiling.LOW.value,
            confidence=max(confidence, 0.85),
            state_snapshot_ref=primary_state,
            evidence_refs=safe_evidence_refs,
            reason_codes=list(set(reason_codes)),
            prohibited_actions=[
                ProhibitedAction.PUSH_FOR_PAYMENT.value,
                ProhibitedAction.CREATE_URGENCY.value,
                ProhibitedAction.CREATE_SCARCITY.value,
                ProhibitedAction.OFFER_UNTRUSTED_DISCOUNT.value,
            ],
            policy_version=MODEL_VERSION,
        )

    # Priority 5: Current Explicit Customer Question / Request
    is_comparison_req = _matches_any(raw_text, [r"قارنلي", r"قارن\s+بين", r"ايه\s+الفرق", r"مقارنة", r"compare"])
    if is_comparison_req or BuyerIntent.PRODUCT_COMPARISON.value in buyer_intents or primary_state == PrimarySalesState.COMPARING.value:
        reason_codes.append(ActionReasonCode.EXPLICIT_COMPARISON_REQUEST.value)
        return ActionDecision(
            company_id=company_id,
            lead_id=lead_id,
            conversation_id=sales_snapshot.conversation_id,
            primary_action=NextBestSalesAction.COMPARE_OPTIONS.value,
            strategy_mode=StrategyMode.COMPARE_AND_NARROW.value,
            secondary_actions=[NextBestSalesAction.ASK_ONE_DECISION_CRITERION.value],
            response_steps=[
                ResponseStep.ANSWER_EXPLICIT_REQUEST.value,
                ResponseStep.COMPARE_RELEVANT_OPTIONS.value,
                ResponseStep.ASK_ONE_DECISION_CRITERION.value,
            ],
            question_policy=QuestionPolicy.ONE_DECISION_QUESTION.value,
            cta_policy=CtaPolicy.SOFT.value,
            pressure_ceiling=PressureCeiling.LOW.value,
            confidence=max(confidence, 0.88),
            state_snapshot_ref=primary_state,
            evidence_refs=safe_evidence_refs,
            reason_codes=list(set(reason_codes)),
            prohibited_actions=[
                ProhibitedAction.PUSH_FOR_PAYMENT.value,
                ProhibitedAction.CREATE_URGENCY.value,
                ProhibitedAction.CREATE_SCARCITY.value,
                ProhibitedAction.OFFER_UNTRUSTED_DISCOUNT.value,
            ],
            policy_version=MODEL_VERSION,
        )

    is_price_req = _matches_any(raw_text, [r"بكام", r"\bكام\b", r"السعر", r"اسعار", r"التكلفة", r"price", r"cost", r"how much"])
    active_objection = primary_state == PrimarySalesState.OBJECTING.value or BuyerIntent.PRICE_OBJECTION.value in buyer_intents
    if not active_objection and (is_price_req or BuyerIntent.PRICE_INQUIRY.value in buyer_intents or BuyerIntent.AVAILABILITY_CHECK.value in buyer_intents):
        reason_codes.append(ActionReasonCode.CURRENT_EXPLICIT_QUESTION.value)
        return ActionDecision(
            company_id=company_id,
            lead_id=lead_id,
            conversation_id=sales_snapshot.conversation_id,
            primary_action=NextBestSalesAction.ANSWER_CURRENT_QUESTION.value,
            strategy_mode=StrategyMode.ANSWER_THEN_CLARIFY.value,
            secondary_actions=[NextBestSalesAction.PROVIDE_PRODUCT_INFORMATION.value],
            response_steps=[
                ResponseStep.ANSWER_EXPLICIT_REQUEST.value,
                ResponseStep.STATE_SUPPORTED_FACTS.value,
                ResponseStep.OFFER_OPTIONAL_CONTINUATION.value,
            ],
            question_policy=QuestionPolicy.ONE_OPTIONAL_QUESTION.value,
            cta_policy=CtaPolicy.SOFT.value,
            pressure_ceiling=PressureCeiling.LOW.value,
            confidence=max(confidence, 0.85),
            state_snapshot_ref=primary_state,
            evidence_refs=safe_evidence_refs,
            reason_codes=list(set(reason_codes)),
            prohibited_actions=[
                ProhibitedAction.PUSH_FOR_PAYMENT.value,
                ProhibitedAction.CREATE_URGENCY.value,
                ProhibitedAction.CREATE_SCARCITY.value,
                ProhibitedAction.OFFER_UNTRUSTED_DISCOUNT.value,
            ],
            policy_version=MODEL_VERSION,
        )

    # Priority 6: Objections & Negotiation
    if active_objection:
        reason_codes.append(ActionReasonCode.PRICE_OBJECTION_PRESENT.value)
        return ActionDecision(
            company_id=company_id,
            lead_id=lead_id,
            conversation_id=sales_snapshot.conversation_id,
            primary_action=NextBestSalesAction.RESPOND_TO_SUPPORTED_CONCERN.value,
            strategy_mode=StrategyMode.CLARIFY_CONCERN.value,
            secondary_actions=[NextBestSalesAction.CLARIFY_OBJECTION.value],
            response_steps=[
                ResponseStep.ACKNOWLEDGE.value,
                ResponseStep.ADDRESS_SUPPORTED_CONCERN.value,
                ResponseStep.ASK_ONE_CLARIFIER.value,
            ],
            question_policy=QuestionPolicy.ONE_OPTIONAL_QUESTION.value,
            cta_policy=CtaPolicy.SOFT.value,
            pressure_ceiling=PressureCeiling.LOW.value,
            confidence=max(confidence, 0.80),
            state_snapshot_ref=primary_state,
            evidence_refs=safe_evidence_refs,
            reason_codes=list(set(reason_codes)),
            prohibited_actions=[
                ProhibitedAction.PUSH_FOR_PAYMENT.value,
                ProhibitedAction.OFFER_UNTRUSTED_DISCOUNT.value,
                ProhibitedAction.CREATE_URGENCY.value,
            ],
            policy_version=MODEL_VERSION,
        )

    if primary_state == PrimarySalesState.NEGOTIATING.value or BuyerIntent.NEGOTIATION.value in buyer_intents:
        reason_codes.append(ActionReasonCode.NEGOTIATION_INTENT.value)
        return ActionDecision(
            company_id=company_id,
            lead_id=lead_id,
            conversation_id=sales_snapshot.conversation_id,
            primary_action=NextBestSalesAction.NEGOTIATE_WITHIN_TRUSTED_TERMS.value,
            strategy_mode=StrategyMode.SUPPORT_DECISION.value,
            response_steps=[
                ResponseStep.ACKNOWLEDGE.value,
                ResponseStep.STATE_SUPPORTED_FACTS.value,
                ResponseStep.SOFT_CTA.value,
            ],
            question_policy=QuestionPolicy.ONE_OPTIONAL_QUESTION.value,
            cta_policy=CtaPolicy.SOFT.value,
            pressure_ceiling=PressureCeiling.LOW.value,
            confidence=max(confidence, 0.82),
            state_snapshot_ref=primary_state,
            evidence_refs=safe_evidence_refs,
            reason_codes=list(set(reason_codes)),
            prohibited_actions=[
                ProhibitedAction.OFFER_UNTRUSTED_DISCOUNT.value,
                ProhibitedAction.PUSH_FOR_PAYMENT.value,
            ],
            policy_version=MODEL_VERSION,
        )

    # Priority 7: State & Intent Strategy Matrix
    if primary_state == PrimarySalesState.BROWSING.value:
        return ActionDecision(
            company_id=company_id,
            lead_id=lead_id,
            conversation_id=sales_snapshot.conversation_id,
            primary_action=NextBestSalesAction.PROVIDE_PRODUCT_INFORMATION.value,
            strategy_mode=StrategyMode.INFORM_AND_ADVANCE.value,
            response_steps=[
                ResponseStep.ANSWER_EXPLICIT_REQUEST.value,
                ResponseStep.OFFER_OPTIONAL_CONTINUATION.value,
            ],
            question_policy=QuestionPolicy.ONE_OPTIONAL_QUESTION.value,
            cta_policy=CtaPolicy.SOFT.value if intent_strength != IntentStrength.LOW.value else CtaPolicy.NONE.value,
            pressure_ceiling=PressureCeiling.LOW.value,
            confidence=confidence,
            state_snapshot_ref=primary_state,
            evidence_refs=safe_evidence_refs,
            reason_codes=list(set(reason_codes)),
            prohibited_actions=[
                ProhibitedAction.PUSH_FOR_PAYMENT.value,
                ProhibitedAction.CREATE_URGENCY.value,
                ProhibitedAction.CREATE_SCARCITY.value,
            ],
            policy_version=MODEL_VERSION,
        )

    if primary_state == PrimarySalesState.NEED_DISCOVERY.value:
        return ActionDecision(
            company_id=company_id,
            lead_id=lead_id,
            conversation_id=sales_snapshot.conversation_id,
            primary_action=NextBestSalesAction.CLARIFY_CUSTOMER_NEED.value,
            strategy_mode=StrategyMode.DISCOVER_NEED.value,
            response_steps=[
                ResponseStep.ACKNOWLEDGE.value,
                ResponseStep.ASK_ONE_CLARIFIER.value,
            ],
            question_policy=QuestionPolicy.ONE_REQUIRED_CLARIFIER.value,
            cta_policy=CtaPolicy.NONE.value,
            pressure_ceiling=PressureCeiling.LOW.value,
            confidence=confidence,
            state_snapshot_ref=primary_state,
            evidence_refs=safe_evidence_refs,
            reason_codes=list(set(reason_codes)),
            prohibited_actions=[
                ProhibitedAction.PUSH_FOR_PAYMENT.value,
                ProhibitedAction.CREATE_URGENCY.value,
            ],
            policy_version=MODEL_VERSION,
        )

    if primary_state == PrimarySalesState.STALLED.value:
        return ActionDecision(
            company_id=company_id,
            lead_id=lead_id,
            conversation_id=sales_snapshot.conversation_id,
            primary_action=NextBestSalesAction.WAIT_FOR_CUSTOMER.value,
            strategy_mode=StrategyMode.HOLD.value,
            response_steps=[ResponseStep.ACKNOWLEDGE.value],
            question_policy=QuestionPolicy.NO_QUESTION.value,
            cta_policy=CtaPolicy.NONE.value,
            pressure_ceiling=PressureCeiling.NONE.value,
            confidence=confidence,
            state_snapshot_ref=primary_state,
            evidence_refs=safe_evidence_refs,
            reason_codes=list(set(reason_codes)),
            prohibited_actions=[
                ProhibitedAction.PUSH_FOR_PAYMENT.value,
                ProhibitedAction.CREATE_URGENCY.value,
            ],
            policy_version=MODEL_VERSION,
        )

    if primary_state == PrimarySalesState.WON.value:
        return ActionDecision(
            company_id=company_id,
            lead_id=lead_id,
            conversation_id=sales_snapshot.conversation_id,
            primary_action=NextBestSalesAction.ACKNOWLEDGE_AND_HOLD.value,
            strategy_mode=StrategyMode.HOLD.value,
            response_steps=[ResponseStep.ACKNOWLEDGE.value],
            question_policy=QuestionPolicy.NO_QUESTION.value,
            cta_policy=CtaPolicy.NONE.value,
            pressure_ceiling=PressureCeiling.NONE.value,
            confidence=confidence,
            state_snapshot_ref=primary_state,
            evidence_refs=safe_evidence_refs,
            reason_codes=list(set(reason_codes)),
            prohibited_actions=[
                ProhibitedAction.PUSH_FOR_PAYMENT.value,
                ProhibitedAction.RESET_PURCHASE_TO_DISCOVERY.value,
            ],
            policy_version=MODEL_VERSION,
        )

    # Fallback default
    return ActionDecision(
        company_id=company_id,
        lead_id=lead_id,
        conversation_id=sales_snapshot.conversation_id,
        primary_action=NextBestSalesAction.PROVIDE_PRODUCT_INFORMATION.value,
        strategy_mode=StrategyMode.INFORM_AND_ADVANCE.value,
        response_steps=[
            ResponseStep.ANSWER_EXPLICIT_REQUEST.value,
            ResponseStep.OFFER_OPTIONAL_CONTINUATION.value,
        ],
        question_policy=QuestionPolicy.ONE_OPTIONAL_QUESTION.value,
        cta_policy=CtaPolicy.SOFT.value,
        pressure_ceiling=PressureCeiling.LOW.value,
        confidence=confidence,
        state_snapshot_ref=primary_state,
        evidence_refs=safe_evidence_refs,
        reason_codes=list(set(reason_codes)),
        prohibited_actions=[
            ProhibitedAction.PUSH_FOR_PAYMENT.value,
        ],
        policy_version=MODEL_VERSION,
    )


def evaluate_next_best_action(
    db: Session,
    company_id: str,
    lead_id: Optional[int],
    sales_snapshot: Optional[SalesStateSnapshot] = None,
    current_message_text: str = "",
    evidence_refs: Optional[List[str]] = None,
    human_takeover_active: bool = False,
    auto_reply_disabled: bool = False,
    objection_snapshot: Optional[Any] = None,
    recommendation_decision: Optional[Any] = None,
    preference_memory: Optional[Any] = None,
    relationship_snapshot: Optional[Any] = None,
) -> ActionDecision:
    """Canonical NBA entry point, enriched by the bounded commercial execution contract."""
    decision = _evaluate_base_next_best_action(
        db=db,
        company_id=company_id,
        lead_id=lead_id,
        sales_snapshot=sales_snapshot,
        current_message_text=current_message_text,
        evidence_refs=evidence_refs,
        human_takeover_active=human_takeover_active,
        auto_reply_disabled=auto_reply_disabled,
        objection_snapshot=objection_snapshot,
        recommendation_decision=recommendation_decision,
        preference_memory=preference_memory,
        relationship_snapshot=relationship_snapshot,
    )
    from services.commercial_intelligence_service import enrich_action_decision

    return enrich_action_decision(
        db=db,
        company_id=company_id,
        lead_id=lead_id,
        decision=decision,
        sales_snapshot=sales_snapshot,
        current_message_text=current_message_text,
        objection_snapshot=objection_snapshot,
        recommendation_decision=recommendation_decision,
        preference_memory=preference_memory,
        relationship_snapshot=relationship_snapshot,
    )
