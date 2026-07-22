"""Canonical commercial execution lineage and deterministic business intelligence.

This module adds no LLM call. It enriches the existing Next Best Action decision,
persists structured lineage, derives traceable commercial events, and aggregates
only deterministic counts. It intentionally never infers paid/confirmed outcomes
from conversational purchase intent.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from statistics import median
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy import desc, func
from sqlalchemy.orm import Session


POLICY_VERSION = "velor_commercial_execution_v1"
EVENT_POLICY_VERSION = "velor_commercial_events_v1"
MIN_CLASSIFICATION_SAMPLE = 3


class CommercialObjective(str, Enum):
    DISCOVER_NEED = "DISCOVER_NEED"
    CLARIFY_REQUIREMENT = "CLARIFY_REQUIREMENT"
    QUALIFY_CONSTRAINT = "QUALIFY_CONSTRAINT"
    ESTABLISH_FIT = "ESTABLISH_FIT"
    DIFFERENTIATE_OPTIONS = "DIFFERENTIATE_OPTIONS"
    RESOLVE_OBJECTION = "RESOLVE_OBJECTION"
    REDUCE_RISK = "REDUCE_RISK"
    RESTORE_MOMENTUM = "RESTORE_MOMENTUM"
    ADVANCE_DECISION = "ADVANCE_DECISION"
    FACILITATE_PURCHASE = "FACILITATE_PURCHASE"
    COMPLETE_PURCHASE_STEP = "COMPLETE_PURCHASE_STEP"
    PRESERVE_RELATIONSHIP = "PRESERVE_RELATIONSHIP"
    REQUEST_OWNER_ACTION = "REQUEST_OWNER_ACTION"
    DO_NOT_ADVANCE = "DO_NOT_ADVANCE"


class SellingStrategy(str, Enum):
    DISCOVER_NEED = "DISCOVER_NEED"
    CLARIFY_CRITERION = "CLARIFY_CRITERION"
    QUALIFY_CONSTRAINT = "QUALIFY_CONSTRAINT"
    RECOMMEND_FIT = "RECOMMEND_FIT"
    DIFFERENTIATE_OPTIONS = "DIFFERENTIATE_OPTIONS"
    REANCHOR_VALUE = "REANCHOR_VALUE"
    HANDLE_PRICE_RESISTANCE = "HANDLE_PRICE_RESISTANCE"
    HANDLE_RISK_CONCERN = "HANDLE_RISK_CONCERN"
    HANDLE_TRUST_CONCERN = "HANDLE_TRUST_CONCERN"
    OFFER_TRUSTED_ALTERNATIVE = "OFFER_TRUSTED_ALTERNATIVE"
    REDUCE_DECISION_FRICTION = "REDUCE_DECISION_FRICTION"
    FACILITATE_PURCHASE = "FACILITATE_PURCHASE"
    LOW_PRESSURE_REENGAGEMENT = "LOW_PRESSURE_REENGAGEMENT"
    REQUEST_OWNER_INTERVENTION = "REQUEST_OWNER_INTERVENTION"
    COMMERCIAL_EXCEPTION_ESCALATION = "COMMERCIAL_EXCEPTION_ESCALATION"
    DO_NOT_PUSH = "DO_NOT_PUSH"


class CommercialNextMove(str, Enum):
    ASK_ONE_USE_CASE_QUESTION = "ASK_ONE_USE_CASE_QUESTION"
    ASK_ONE_DECISION_CRITERION = "ASK_ONE_DECISION_CRITERION"
    ASK_BUDGET_OR_VALUE_CLARIFIER = "ASK_BUDGET_OR_VALUE_CLARIFIER"
    PRESENT_HIGHEST_FIT_WITHIN_CONSTRAINT = "PRESENT_HIGHEST_FIT_WITHIN_CONSTRAINT"
    EXPLAIN_NEED_LINKED_DIFFERENCE = "EXPLAIN_NEED_LINKED_DIFFERENCE"
    REANCHOR_TO_EXPLICIT_NEED = "REANCHOR_TO_EXPLICIT_NEED"
    PROVIDE_VERIFIED_PURCHASE_STEP = "PROVIDE_VERIFIED_PURCHASE_STEP"
    ACKNOWLEDGE_WITHOUT_PRESSURE = "ACKNOWLEDGE_WITHOUT_PRESSURE"
    ESCALATE_WITH_CONTEXT = "ESCALATE_WITH_CONTEXT"
    ANSWER_SUPPORTED_REQUEST = "ANSWER_SUPPORTED_REQUEST"
    ACKNOWLEDGE_AND_HOLD = "ACKNOWLEDGE_AND_HOLD"


class ObservedOutcome(str, Enum):
    OBJECTION_PERSISTED = "OBJECTION_PERSISTED"
    OBJECTION_SOFTENED = "OBJECTION_SOFTENED"
    CUSTOMER_PROGRESSED = "CUSTOMER_PROGRESSED"
    CUSTOMER_REGRESSED = "CUSTOMER_REGRESSED"
    CUSTOMER_PROVIDED_MISSING_INFORMATION = "CUSTOMER_PROVIDED_MISSING_INFORMATION"
    COMPARISON_CONTINUED = "COMPARISON_CONTINUED"
    PURCHASE_EXECUTION_STARTED = "PURCHASE_EXECUTION_STARTED"
    PURCHASE_COMMITMENT_APPEARED = "PURCHASE_COMMITMENT_APPEARED"
    OWNER_INTERVENTION_OCCURRED = "OWNER_INTERVENTION_OCCURRED"
    CONVERSATION_STALLED = "CONVERSATION_STALLED"
    WON_EVIDENCE_APPEARED = "WON_EVIDENCE_APPEARED"
    UNKNOWN = "UNKNOWN"


class CommercialEventType(str, Enum):
    PRODUCT_MENTIONED = "PRODUCT_MENTIONED"
    PRODUCT_ASKED_ABOUT = "PRODUCT_ASKED_ABOUT"
    PRODUCT_CONSIDERED = "PRODUCT_CONSIDERED"
    PRODUCT_RECOMMENDED = "PRODUCT_RECOMMENDED"
    PRICE_REVEALED = "PRICE_REVEALED"
    PRODUCT_COMPARED = "PRODUCT_COMPARED"
    PRODUCT_SELECTED = "PRODUCT_SELECTED"
    PRODUCT_REQUESTED_OUT_OF_STOCK = "PRODUCT_REQUESTED_OUT_OF_STOCK"
    PRODUCT_REQUESTED_UNLISTED = "PRODUCT_REQUESTED_UNLISTED"
    OBJECTION_EXPRESSED = "OBJECTION_EXPRESSED"
    ALTERNATIVE_REQUESTED = "ALTERNATIVE_REQUESTED"
    HARD_CONSTRAINT_STATED = "HARD_CONSTRAINT_STATED"
    PURCHASE_INTENT_EXPRESSED = "PURCHASE_INTENT_EXPRESSED"
    PURCHASE_COMMITMENT = "PURCHASE_COMMITMENT"
    PURCHASE_EXECUTION_REQUEST = "PURCHASE_EXECUTION_REQUEST"
    CONFIRMED_ORDER = "CONFIRMED_ORDER"
    PAID = "PAID"
    CONVERSATION_STALLED = "CONVERSATION_STALLED"
    OWNER_INTERVENTION_REQUIRED = "OWNER_INTERVENTION_REQUIRED"
    WAITING_ON_US = "WAITING_ON_US"
    KNOWLEDGE_GAP_HIT = "KNOWLEDGE_GAP_HIT"


_STATE_RANK = {
    "UNKNOWN": 0,
    "BROWSING": 1,
    "NEED_DISCOVERY": 2,
    "EVALUATING": 3,
    "COMPARING": 4,
    "OBJECTING": 4,
    "NEGOTIATING": 5,
    "READY_TO_BUY": 6,
    "COMMITTING": 7,
    "WON": 8,
    "STALLED": 1,
    "LOST": 0,
}


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {key: _jsonable(val) for key, val in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _jsonable(val) for key, val in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "to_dict"):
        return _jsonable(value.to_dict())
    return str(value)


def _contains(text: str, terms: Iterable[str]) -> bool:
    folded = (text or "").casefold()
    return any(term.casefold() in folded for term in terms)


def _catalog_stock_state(value: Any) -> str:
    """Return a conservative current stock state from trusted catalog data."""
    if value is None:
        return "unknown"
    if isinstance(value, bool):
        return "available" if value else "out_of_stock"
    if isinstance(value, (int, float)):
        return "available" if float(value) > 0 else "out_of_stock"

    text = str(value).strip().casefold()
    if not text or text in {"unknown", "n/a", "na", "none", "null", "غير معروف"}:
        return "unknown"
    if text in {
        "false",
        "out of stock",
        "out_of_stock",
        "unavailable",
        "sold out",
        "غير متوفر",
        "نفد",
        "نفدت الكمية",
    }:
        return "out_of_stock"
    if text in {"true", "available", "in stock", "in_stock", "متوفر", "متاح"}:
        return "available"

    numeric = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*(?:units?|pcs?|pieces?)?\s*", text)
    if numeric:
        return "available" if float(numeric.group(1)) > 0 else "out_of_stock"
    return "unknown"


def _is_explicit_product_request(text: str) -> bool:
    value = text or ""
    # A question mark only proves that the customer asked *something*.  It does
    # not prove availability/request intent (for example, "why is X expensive?").
    # Keep this gate deliberately narrow because it feeds the unavailable-demand
    # KPI and therefore must not promote generic product questions into demand.
    if _contains(
        value,
        (
            "مش عايز",
            "مش محتاج",
            "مش هشتري",
            "مش هاخد",
            "لا أريد",
            "لا اريد",
            "لن أشتري",
            "لن اشتري",
            "don't want",
            "do not want",
            "don't need",
            "do not need",
            "won't buy",
            "will not buy",
        ),
    ):
        return False
    return _contains(
        value,
        (
            "do you have",
            "do you sell",
            "in stock",
            "available",
            "i want",
            "i need",
            "buy",
            "order",
            "هل عندكم",
            "هل لديكم",
            "هل يوجد",
            "عندكم",
            "متوفر",
            "موجود",
            "عايز",
            "محتاج",
            "اشتري",
            "أشتري",
            "اطلب",
            "أطلب",
        ),
    )


def _extract_unlisted_product_request(text: str, products: Sequence[Any]) -> Optional[str]:
    """Extract a bounded observed request term only behind an explicit request phrase.

    The returned text is not promoted to a catalog product.  It is merely the
    customer's observed request, used with ``catalog_match_status=unlisted``.
    """
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    if not value:
        return None

    patterns = (
        r"\bdo\s+you\s+(?:have|sell|stock|carry)\s+(?:an?\s+|the\s+)?(?P<name>[^?!.\n]{2,80})",
        r"\bis\s+(?P<name>[^?!.\n]{2,80}?)\s+(?:available|in\s+stock)\b",
        r"(?:هل\s+(?:عندكم|لديكم|يوجد)|عندكم|لديكم)\s+(?:منتج\s+)?(?P<name>[^؟?!.\n]{2,80})",
    )
    candidate = None
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if match:
            candidate = match.group("name")
            break
    if not candidate:
        return None

    candidate = re.sub(
        r"\s+(?:available|in\s+stock|متوفر|متاح|موجود)\s*$",
        "",
        candidate,
        flags=re.IGNORECASE,
    ).strip(" \t\r\n:,-–—\"'")
    if not (2 <= len(candidate) <= 80) or len(candidate.split()) > 10:
        return None
    if not any(char.isalpha() for char in candidate):
        return None
    if candidate.casefold() in {
        "product",
        "a product",
        "the product",
        "item",
        "anything",
        "something",
        "منتج",
        "المنتج",
        "حاجة",
        "حاجه",
        "شيء",
    }:
        return None

    # A catalog name/alias or an exact catalog category is not an unlisted
    # request, even if the full customer sentence did not match initially.
    from services.product_context_service import match_product_mentions

    if match_product_mentions(candidate, products):
        return None
    normalized_candidate = re.sub(r"\s+", " ", candidate).strip().casefold()
    for product in products:
        category = re.sub(r"\s+", " ", str(getattr(product, "category", "") or "")).strip().casefold()
        if category and normalized_candidate == category:
            return None
    return candidate


def _extract_hard_budget(text: str) -> Optional[float]:
    normalized = (text or "").replace(",", "")
    patterns = (
        r"(?:آخري|اخري|أقصى|اقصى|ميزانيتي|ميزانية|حدي|حد أقصى|حد اقصى)\s*(?:هو|حوالي|لحد|:)??\s*(\d{3,8})",
        r"(?:my\s+(?:max|maximum|budget)|budget\s+(?:is|of)|up\s+to)\s*[:=]?\s*(\d{2,8})",
        r"(?:\u0623\u0646\u0627\s+)?(?:\u0622\u062e\u0631\u064a|\u0627\u062e\u0631\u064a|\u0645\u064a\u0632\u0627\u0646\u064a\u062a\u064a|\u0645\u064a\u0632\u0627\u0646\u064a\u0629|\u0645\u0639\u0627\u064a\u0627|\u0633\u0642\u0641\u064a)\s*(?:\u0647\u0648|\u062d\u0648\u0627\u0644\u064a|\u0644\u062d\u062f|:)?\s*(\d{3,8})",
        r"(?:\u0628\u062d\u062f\s+\u0623\u0642\u0635\u0649|\u0628\u062d\u062f\s+\u0627\u0642\u0635\u0649|\u0645\u0634\s+\u0647\u0642\u062f\u0631\s+\u0623\u0639\u062f\u064a|\u0645\u0634\s+\u0647\u0642\u062f\u0631\s+\u0627\u0639\u062f\u064a|\u0641\u064a\s+\u062d\u062f\u0648\u062f|\u0623\u0642\u0644\s+\u0645\u0646|\u0627\u0642\u0644\s+\u0645\u0646)\s*(\d{3,8})",
    )
    for pattern in patterns:
        match = re.search(pattern, normalized, flags=re.IGNORECASE)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                return None
    return None


def _discount_request(text: str) -> bool:
    return _contains(text, ("خصم", "discount", "special price", "سعر خاص"))


def _quantity_request(text: str) -> bool:
    return bool(re.search(r"(?:اشتريت|هاخد|آخد|اخد|عدد|quantity|buy)\s*(?:عدد)?\s*[2-9٢-٩]", text or "", flags=re.IGNORECASE)) or _contains(
        text, ("لو اشتريت 2", "لو اخدت 2", "لو أخدت 2", "bulk", "جملة")
    )


def _purchase_execution_request(text: str) -> bool:
    return _contains(
        text,
        (
            "أعمل إيه", "اعمل ايه", "أطلب إزاي", "اطلب ازاي", "أدفع إزاي", "ادفع ازاي",
            "فين الدفع", "ابعت رابط الدفع", "اخده", "آخده", "هاخده", "how do i order",
            "how do i pay", "where do i pay", "send payment",
        ),
    ) and _contains(text, ("اخد", "آخد", "هاخد", "طلب", "دفع", "order", "pay"))


def _soft_stall(text: str) -> bool:
    return _contains(text, ("هفكر", "افكر", "أفكر", "هشوف", "بعدين", "think about it", "let me think"))


def _comparison_request(text: str) -> bool:
    return _contains(text, ("الفرق", "قارن", "مقارنة", "أنهي أنسب", "انهي انسب", "compare", "difference between", "which is better"))


def _price_objection(text: str, objection_snapshot: Any = None) -> bool:
    if objection_snapshot and getattr(objection_snapshot, "objection_present", False):
        primary = str(getattr(objection_snapshot, "primary_objection", ""))
        if "PRICE" in primary or "BUDGET" in primary:
            return True
    return _contains(text, ("غالي", "مرتفع", "فوق ميزانيتي", "too expensive", "expensive", "over budget"))


def _known_need(recommendation_decision: Any, preference_memory: Any, text: str) -> bool:
    if _contains(text, ("للشغل", "ساعات طويلة", "للظهر", "مكتب", "use it for", "long hours", "for work")):
        return True
    if recommendation_decision:
        outcome = str(getattr(recommendation_decision, "outcome", ""))
        if any(token in outcome for token in ("RECOMMEND", "COMPARE_REQUESTED", "ANSWER_EXPLICIT")):
            return True
    return bool(getattr(preference_memory, "active_preferences", None))


def _recommended_names(recommendation_decision: Any) -> List[str]:
    names: List[str] = []
    for item in getattr(recommendation_decision, "recommended_products", []) or []:
        name = getattr(item, "product_name", None)
        if name and name not in names:
            names.append(str(name))
    return names


def _eligible_budget_products(db: Session, company_id: str, budget: float) -> List[Dict[str, Any]]:
    from services.product_context_service import get_company_products

    eligible = []
    for product in get_company_products(db, company_id):
        if product.price is not None and product.price <= budget:
            eligible.append({"name": product.name, "price": product.price, "currency": product.currency, "category": product.category})
    eligible.sort(key=lambda item: (item["price"], item["name"].casefold()), reverse=True)
    return eligible


def _discount_is_trusted(db: Session, company_id: str, current_text: str) -> Tuple[bool, List[str]]:
    from services.product_context_service import get_company_products, match_product_mentions

    products = get_company_products(db, company_id)
    matches = match_product_mentions(current_text, products)
    candidates = matches or products
    trusted = [product.name for product in candidates if product.quantity_discounts]
    return bool(trusted), trusted


def _set_contract(
    decision: Any,
    objective: CommercialObjective,
    strategy: SellingStrategy,
    move: CommercialNextMove,
    owner_explanation: str,
    evidence: Sequence[Dict[str, Any]],
    escalation: Optional[Dict[str, Any]] = None,
) -> Any:
    decision.commercial_objective = objective.value
    decision.selling_strategy = strategy.value
    decision.next_move = move.value
    decision.owner_explanation = owner_explanation
    decision.decision_evidence = list(evidence)
    decision.escalation_required = bool(escalation)
    decision.escalation = escalation or {}
    decision.policy_version = POLICY_VERSION
    return decision


def enrich_action_decision(
    db: Session,
    company_id: str,
    lead_id: Optional[int],
    decision: Any,
    sales_snapshot: Any,
    current_message_text: str,
    objection_snapshot: Any = None,
    recommendation_decision: Any = None,
    preference_memory: Any = None,
    relationship_snapshot: Any = None,
) -> Any:
    """Add objective/strategy/move to the existing canonical NBA decision."""
    from services.next_best_action_service import (
        CtaPolicy,
        NextBestSalesAction,
        PressureCeiling,
        ProhibitedAction,
        QuestionPolicy,
        ResponseStep,
        StrategyMode,
    )

    text = current_message_text or ""
    state = str(getattr(sales_snapshot, "primary_state", decision.state_snapshot_ref or "UNKNOWN"))
    evidence: List[Dict[str, Any]] = [
        {"type": "current_customer_message", "value": text[:500]},
        {"type": "sales_state", "value": state},
    ]
    for ref in getattr(decision, "evidence_refs", []) or []:
        evidence.append({"type": "evidence_ref", "value": str(ref)})

    # Runtime authority gates always win.
    if decision.primary_action == NextBestSalesAction.PAUSE_FOR_HUMAN_TAKEOVER.value:
        escalation = {
            "type": "HUMAN_TAKEOVER",
            "customer_request": text[:500],
            "why_owner_needed": "التولّي البشري أو إيقاف الرد الآلي مفعّل؛ لا يملك فيلور صلاحية المتابعة تلقائيًا.",
            "known": [f"حالة البيع: {state}"],
            "unknown": ["قرار المالك التالي"],
            "suggested_action": "راجع آخر رسالة وتابع يدويًا من مساحة العميل.",
            "evidence": evidence,
        }
        return _set_contract(decision, CommercialObjective.REQUEST_OWNER_ACTION, SellingStrategy.REQUEST_OWNER_INTERVENTION, CommercialNextMove.ESCALATE_WITH_CONTEXT, "التدخل البشري أعلى قيمة من الرد الآلي الآن.", evidence, escalation)

    trusted_discount, discount_products = _discount_is_trusted(db, company_id, text) if _discount_request(text) else (False, [])
    if _discount_request(text) and not trusted_discount:
        decision.primary_action = NextBestSalesAction.OFFER_HUMAN_HANDOFF.value
        decision.strategy_mode = StrategyMode.HUMAN_HANDOFF.value
        decision.question_policy = QuestionPolicy.NO_QUESTION.value
        decision.cta_policy = CtaPolicy.NONE.value
        decision.pressure_ceiling = PressureCeiling.NONE.value
        if ProhibitedAction.OFFER_UNTRUSTED_DISCOUNT.value not in decision.prohibited_actions:
            decision.prohibited_actions.append(ProhibitedAction.OFFER_UNTRUSTED_DISCOUNT.value)
        escalation = {
            "type": "COMMERCIAL_EXCEPTION",
            "customer_request": text[:500],
            "why_owner_needed": "لا توجد سياسة خصم كمية موثوقة تغطي الطلب.",
            "known": ["العميل طلب خصمًا" + (" لكمية" if _quantity_request(text) else "")],
            "unknown": ["نسبة الخصم أو الاستثناء المسموح", "مدة سريان أي عرض"],
            "suggested_action": "اتخذ قرارًا تجاريًا ثم أرسل عرضًا معتمدًا أو ارفض الاستثناء بوضوح.",
            "evidence": evidence,
        }
        evidence.append({"type": "trusted_discount_policy", "value": "unknown"})
        return _set_contract(decision, CommercialObjective.REQUEST_OWNER_ACTION, SellingStrategy.COMMERCIAL_EXCEPTION_ESCALATION, CommercialNextMove.ESCALATE_WITH_CONTEXT, "العميل يطلب استثناءً تجاريًا غير موجود في البيانات الموثوقة؛ يجب حفظ الزخم من دون اختراع وعد.", evidence, escalation)

    if _purchase_execution_request(text) or decision.primary_action == NextBestSalesAction.FACILITATE_PURCHASE.value:
        decision.primary_action = NextBestSalesAction.FACILITATE_PURCHASE.value
        decision.strategy_mode = StrategyMode.PURCHASE_EXECUTION.value
        decision.cta_policy = CtaPolicy.EXECUTION_ONLY.value
        decision.response_steps = [ResponseStep.CONFIRM_SELECTION.value, ResponseStep.PROVIDE_TRUSTED_NEXT_STEP.value, ResponseStep.REQUEST_REQUIRED_ORDER_DETAIL.value]
        for prohibited in (ProhibitedAction.RESET_PURCHASE_TO_DISCOVERY.value, ProhibitedAction.CREATE_URGENCY.value, ProhibitedAction.OFFER_UNTRUSTED_DISCOUNT.value):
            if prohibited not in decision.prohibited_actions:
                decision.prohibited_actions.append(prohibited)
        evidence.append({"type": "explicit_purchase_execution_request", "value": True})
        return _set_contract(decision, CommercialObjective.COMPLETE_PURCHASE_STEP, SellingStrategy.FACILITATE_PURCHASE, CommercialNextMove.PROVIDE_VERIFIED_PURCHASE_STEP, "العميل انتقل من التقييم إلى التنفيذ؛ المطلوب إتمام خطوة شراء موثوقة لا إعادة البيع له.", evidence)

    budget = _extract_hard_budget(text)
    if budget is not None:
        eligible = _eligible_budget_products(db, company_id, budget)
        decision.primary_action = NextBestSalesAction.PROVIDE_PRODUCT_INFORMATION.value if eligible else NextBestSalesAction.REQUEST_MISSING_INFORMATION.value
        decision.strategy_mode = StrategyMode.SUPPORT_DECISION.value
        decision.question_policy = QuestionPolicy.ONE_OPTIONAL_QUESTION.value if eligible else QuestionPolicy.NO_QUESTION.value
        decision.cta_policy = CtaPolicy.SOFT.value
        decision.pressure_ceiling = PressureCeiling.LOW.value
        evidence.extend((
            {"type": "hard_budget", "value": budget, "authority": "current_explicit_customer_evidence"},
            {"type": "eligible_trusted_products", "value": eligible[:5]},
        ))
        explanation = f"الحد الأقصى الصريح {budget:g} أصبح قيدًا صلبًا. البدائل الأعلى سعرًا مستبعدة قبل ترتيب الملاءمة."
        if not eligible:
            explanation += " لا يوجد بديل موثوق داخل القيد؛ لن يخترع فيلور ملاءمة أو سعرًا."
        return _set_contract(decision, CommercialObjective.ESTABLISH_FIT, SellingStrategy.OFFER_TRUSTED_ALTERNATIVE, CommercialNextMove.PRESENT_HIGHEST_FIT_WITHIN_CONSTRAINT, explanation, evidence)

    if _soft_stall(text) or state == "STALLED":
        decision.primary_action = NextBestSalesAction.WAIT_FOR_CUSTOMER.value
        decision.strategy_mode = StrategyMode.HOLD.value
        decision.question_policy = QuestionPolicy.NO_QUESTION.value
        decision.cta_policy = CtaPolicy.NONE.value
        decision.pressure_ceiling = PressureCeiling.NONE.value
        decision.response_steps = [ResponseStep.ACKNOWLEDGE.value, ResponseStep.STOP_SELLING.value]
        for prohibited in (ProhibitedAction.PUSH_FOR_PAYMENT.value, ProhibitedAction.CREATE_URGENCY.value, ProhibitedAction.CREATE_SCARCITY.value):
            if prohibited not in decision.prohibited_actions:
                decision.prohibited_actions.append(prohibited)
        evidence.append({"type": "explicit_soft_stall", "value": True})
        return _set_contract(decision, CommercialObjective.PRESERVE_RELATIONSHIP, SellingStrategy.DO_NOT_PUSH, CommercialNextMove.ACKNOWLEDGE_WITHOUT_PRESSURE, "العميل طلب مساحة للتفكير؛ الضغط أو الاستعجال سيخالف دليله الحالي.", evidence)

    if _comparison_request(text) or decision.primary_action == NextBestSalesAction.COMPARE_OPTIONS.value:
        known = _known_need(recommendation_decision, preference_memory, text)
        evidence.append({"type": "known_decision_criterion", "value": known})
        move = CommercialNextMove.EXPLAIN_NEED_LINKED_DIFFERENCE if known else CommercialNextMove.ASK_ONE_DECISION_CRITERION
        explanation = "اربط الفروق فقط بالاحتياج المصرح به." if known else "المقارنة مطلوبة لكن معيار الملاءمة غير معروف؛ قارن الحقائق ثم اطلب معيارًا واحدًا عالي القيمة."
        return _set_contract(decision, CommercialObjective.DIFFERENTIATE_OPTIONS, SellingStrategy.DIFFERENTIATE_OPTIONS, move, explanation, evidence)

    if _price_objection(text, objection_snapshot):
        known = _known_need(recommendation_decision, preference_memory, text)
        recommended = _recommended_names(recommendation_decision)
        evidence.extend((
            {"type": "price_objection", "value": True},
            {"type": "known_need", "value": known},
            {"type": "trusted_fit_candidates", "value": recommended},
        ))
        decision.primary_action = NextBestSalesAction.RESPOND_TO_SUPPORTED_CONCERN.value
        decision.strategy_mode = StrategyMode.CLARIFY_CONCERN.value if not known else StrategyMode.SUPPORT_DECISION.value
        decision.question_policy = QuestionPolicy.ONE_REQUIRED_CLARIFIER.value if not known else QuestionPolicy.ONE_OPTIONAL_QUESTION.value
        if known and recommended:
            return _set_contract(decision, CommercialObjective.RESOLVE_OBJECTION, SellingStrategy.REANCHOR_VALUE, CommercialNextMove.REANCHOR_TO_EXPLICIT_NEED, "يوجد احتياج معروف ومرشح ملائم؛ وضّح القيمة المرتبطة بالاحتياج فقط من دون افتراض أن السعر مقبول.", evidence)
        return _set_contract(decision, CommercialObjective.QUALIFY_CONSTRAINT, SellingStrategy.CLARIFY_CRITERION, CommercialNextMove.ASK_BUDGET_OR_VALUE_CLARIFIER, "الاعتراض صريح لكن سببه غير مثبت: قد يكون سقف ميزانية أو فجوة قيمة أو مقارنة. اسأل سؤالًا واحدًا يحسم المسار.", evidence)

    if _contains(text, ("أرخص", "ارخص", "cheaper", "lower price")):
        previous = _previous_product_context(db, company_id, lead_id)
        evidence.append({"type": "prior_product_context", "value": previous})
        return _set_contract(decision, CommercialObjective.ESTABLISH_FIT, SellingStrategy.OFFER_TRUSTED_ALTERNATIVE, CommercialNextMove.PRESENT_HIGHEST_FIT_WITHIN_CONSTRAINT, "العميل يعود إلى سياق سابق ويطلب بديلًا أرخص؛ استخدم المنتج السابق فقط إذا كان مثبتًا في المحادثة.", evidence)

    if state == "NEED_DISCOVERY" or decision.primary_action in (NextBestSalesAction.CLARIFY_CUSTOMER_NEED.value, NextBestSalesAction.ASK_ONE_DECISION_CRITERION.value):
        return _set_contract(decision, CommercialObjective.DISCOVER_NEED, SellingStrategy.DISCOVER_NEED, CommercialNextMove.ASK_ONE_USE_CASE_QUESTION, "الاحتياج غير مكتمل؛ سؤال واحد عالي القيمة أفضل من عرض منتجات عشوائي.", evidence)

    if state in ("LOST", "WON") or decision.strategy_mode in (StrategyMode.RESPECT_AND_CLOSE.value, StrategyMode.HOLD.value):
        return _set_contract(decision, CommercialObjective.DO_NOT_ADVANCE, SellingStrategy.DO_NOT_PUSH, CommercialNextMove.ACKNOWLEDGE_AND_HOLD, "لا توجد خطوة بيع إضافية مدعومة الآن.", evidence)

    return _set_contract(decision, CommercialObjective.ADVANCE_DECISION, SellingStrategy.RECOMMEND_FIT, CommercialNextMove.ANSWER_SUPPORTED_REQUEST, "أجب الطلب الحالي من الحقائق الموثوقة ثم اقترح أصغر خطوة مفيدة.", evidence)


def _previous_product_context(db: Session, company_id: str, lead_id: Optional[int]) -> List[str]:
    if not lead_id:
        return []
    from database import CommercialEvent

    rows = (
        db.query(CommercialEvent)
        .filter(CommercialEvent.company_id == company_id, CommercialEvent.lead_id == lead_id, CommercialEvent.product_ref.isnot(None))
        .order_by(desc(CommercialEvent.observed_at))
        .limit(6)
        .all()
    )
    result = []
    for row in rows:
        if row.product_ref and row.product_ref not in result:
            result.append(row.product_ref)
    return result


def _knowledge_gap_topic(text: str, db: Session, company_id: str, products: Sequence[Any]) -> Optional[str]:
    from database import CompanyKnowledge

    checks = (
        ("shipping_policy", ("شحن", "توصيل", "delivery", "shipping")),
        ("warranty", ("ضمان", "warranty")),
        ("installation", ("تركيب", "installation", "assembly")),
        ("availability", ("متوفر", "مخزون", "stock", "available")),
    )
    topic = next((name for name, terms in checks if _contains(text, terms)), None)
    if not topic:
        return None
    matches = list(products)
    if topic == "warranty" and any(getattr(product, "warranty", None) not in (None, "") for product in matches):
        return None
    if topic == "installation" and any(getattr(product, "installation", None) not in (None, "") for product in matches):
        return None
    if topic == "availability" and any(getattr(product, "stock", None) not in (None, "") for product in matches):
        return None
    knowledge = db.query(CompanyKnowledge).filter(CompanyKnowledge.company_id == company_id).first()
    trusted_text = f"{getattr(knowledge, 'knowledge_base', '') or ''} {getattr(knowledge, 'system_prompt', '') or ''}".casefold()
    topic_terms = dict(checks)[topic]
    negative_markers = ("no ", "not supplied", "missing", "unknown", "غير معروف", "غير متاح", "لا توجد", "لا يوجد")
    explicitly_unknown = any(marker in trusted_text for marker in negative_markers)
    return None if not explicitly_unknown and any(term.casefold() in trusted_text for term in topic_terms) else topic


def _event_hash(company_id: str, source_id: str, event_type: str, product_ref: Optional[str], detail: str = "") -> str:
    raw = "|".join((company_id, source_id, event_type, product_ref or "", detail))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _event_spec(event_type: CommercialEventType, product: Optional[str], stage: Optional[str], source: str, **extra: Any) -> Dict[str, Any]:
    return {"event_type": event_type.value, "product_ref": product, "stage": stage, "source_text": source[:1000], **extra}


def derive_commercial_event_specs(
    db: Session,
    company_id: str,
    lead_id: int,
    customer_text: str,
    assistant_text: str,
    decision: Any,
    sales_snapshot: Any,
    objection_snapshot: Any = None,
    recommendation_decision: Any = None,
) -> List[Dict[str, Any]]:
    """Derive source-linked events from a customer turn only.

    ``assistant_text`` remains in the signature for backwards-compatible
    callers but is deliberately not an input to event derivation. Bounded
    deterministic snapshots may classify the same customer text, but generated
    or advisory assistant text must never become observed commercial evidence.
    """
    from services.product_context_service import get_company_products, match_product_mentions

    products = get_company_products(db, company_id)
    explicit_products = match_product_mentions(customer_text, products)
    contextual_names = _previous_product_context(db, company_id, lead_id)
    current_names = [product.name for product in explicit_products]
    relevant_names = list(dict.fromkeys(current_names or contextual_names[:2]))
    raw_state = getattr(sales_snapshot, "primary_state", None)
    state = str(raw_state.value if isinstance(raw_state, Enum) else (raw_state or "UNKNOWN"))
    specs: List[Dict[str, Any]] = []

    for product in explicit_products:
        specs.append(_event_spec(CommercialEventType.PRODUCT_MENTIONED, product.name, "INQUIRY", customer_text, attribution="explicit_mention"))
        if "?" in customer_text or "؟" in customer_text or _contains(customer_text, ("بكام", "إيه", "ايه", "هل", "what", "how", "which")):
            specs.append(_event_spec(CommercialEventType.PRODUCT_ASKED_ABOUT, product.name, "INQUIRY", customer_text, attribution="explicit_question"))
        if _is_explicit_product_request(customer_text) and _catalog_stock_state(getattr(product, "stock", None)) == "out_of_stock":
            specs.append(
                _event_spec(
                    CommercialEventType.PRODUCT_REQUESTED_OUT_OF_STOCK,
                    product.name,
                    "DEMAND_GAP",
                    customer_text,
                    attribution="explicit_request_against_trusted_catalog_stock",
                    catalog_match_status="matched",
                    stock_state="out_of_stock",
                    stock_value=getattr(product, "stock", None),
                    truth_class="DETERMINISTICALLY_DERIVED",
                )
            )

    if not explicit_products:
        unlisted_request = _extract_unlisted_product_request(customer_text, products)
        if unlisted_request:
            specs.append(
                _event_spec(
                    CommercialEventType.PRODUCT_REQUESTED_UNLISTED,
                    unlisted_request,
                    "DEMAND_GAP",
                    customer_text,
                    attribution="bounded_explicit_request_pattern",
                    requested_term=unlisted_request,
                    catalog_match_status="unlisted",
                    stock_state="unknown",
                    truth_class="OBSERVED",
                )
            )

    if relevant_names and (state in ("EVALUATING", "COMPARING", "OBJECTING", "NEGOTIATING", "READY_TO_BUY", "COMMITTING") or _contains(customer_text, ("أنسب", "انسب", "عايز", "محتاج", "consider", "interested"))):
        for name in relevant_names:
            specs.append(_event_spec(CommercialEventType.PRODUCT_CONSIDERED, name, "NEED_FIT", customer_text, attribution="explicit_or_active_context"))

    if _comparison_request(customer_text):
        compared = current_names or relevant_names
        for name in compared:
            specs.append(_event_spec(CommercialEventType.PRODUCT_COMPARED, name, "COMPARISON", customer_text, attribution="comparison_request"))

    raw_explicitness = getattr(objection_snapshot, "explicitness", "") if objection_snapshot else ""
    objection_explicitness = str(raw_explicitness.value if isinstance(raw_explicitness, Enum) else raw_explicitness).upper()
    raw_objection = getattr(objection_snapshot, "primary_objection", "NONE") if objection_snapshot else "NONE"
    primary_objection = str(raw_objection.value if isinstance(raw_objection, Enum) else raw_objection)
    explicit_objection = bool(
        objection_snapshot
        and getattr(objection_snapshot, "objection_present", False)
        and objection_explicitness == "EXPLICIT"
        and primary_objection not in {"", "NONE"}
    )
    if explicit_objection:
        obstruction = primary_objection
        for name in relevant_names or [None]:
            specs.append(
                _event_spec(
                    CommercialEventType.OBJECTION_EXPRESSED,
                    name,
                    "OBJECTION",
                    customer_text,
                    objection_type=obstruction,
                    attribution="deterministic_explicit_objection_snapshot",
                    explicitness="EXPLICIT",
                    confidence=float(getattr(objection_snapshot, "confidence", 0.0) or 0.0),
                    root_cause_hypothesis=str(getattr(objection_snapshot, "root_cause_hypothesis", "UNKNOWN") or "UNKNOWN"),
                    root_cause_confidence=float(getattr(objection_snapshot, "root_cause_confidence", 0.0) or 0.0),
                    root_cause_truth_class="HYPOTHESIS",
                    secondary_objections=list(getattr(objection_snapshot, "secondary_objections", []) or []),
                    blocking_level=str(getattr(objection_snapshot, "blocking_level", "UNKNOWN") or "UNKNOWN"),
                    objection_status=str(getattr(objection_snapshot, "status", "UNKNOWN") or "UNKNOWN"),
                    objection_evidence_refs=list(getattr(objection_snapshot, "evidence_refs", []) or []),
                    reason_codes=list(getattr(objection_snapshot, "reason_codes", []) or []),
                )
            )
    elif _price_objection(customer_text):
        obstruction = "PRICE_RESISTANCE"
        for name in relevant_names or [None]:
            specs.append(_event_spec(CommercialEventType.OBJECTION_EXPRESSED, name, "OBJECTION", customer_text, objection_type=obstruction, attribution="explicit_customer_objection"))

    budget = _extract_hard_budget(customer_text)
    if budget is not None:
        for name in relevant_names or [None]:
            specs.append(_event_spec(CommercialEventType.HARD_CONSTRAINT_STATED, name, "CONSTRAINT", customer_text, constraint_type="BUDGET_CEILING", constraint_value=budget))

    if _contains(customer_text, ("أرخص", "ارخص", "cheaper", "alternative", "بديل")):
        for name in relevant_names or [None]:
            specs.append(_event_spec(CommercialEventType.ALTERNATIVE_REQUESTED, name, "COMPARISON", customer_text, attribution="explicit_alternative_request"))

    selected = _contains(customer_text, ("هاخد", "آخد", "اخد", "اختياري", "i'll take", "i will take", "choose"))
    if selected:
        for name in relevant_names or current_names or [None]:
            specs.append(_event_spec(CommercialEventType.PRODUCT_SELECTED, name, "SELECTION", customer_text, attribution="explicit_selection_language"))

    if _contains(customer_text, ("هشتري", "عايز أشتري", "عايز اشتري", "i want to buy", "i'll buy", "purchase")):
        for name in relevant_names or [None]:
            specs.append(_event_spec(CommercialEventType.PURCHASE_INTENT_EXPRESSED, name, "PURCHASE_INTENT", customer_text, attribution="explicit_purchase_intent"))

    if selected:
        for name in relevant_names or [None]:
            specs.append(_event_spec(CommercialEventType.PURCHASE_COMMITMENT, name, "COMMITMENT", customer_text, attribution="explicit_commitment_not_order"))

    if _purchase_execution_request(customer_text):
        for name in relevant_names or [None]:
            specs.append(_event_spec(CommercialEventType.PURCHASE_EXECUTION_REQUEST, name, "EXECUTION", customer_text, attribution="explicit_execution_request"))

    if _soft_stall(customer_text):
        for name in relevant_names or [None]:
            specs.append(_event_spec(CommercialEventType.CONVERSATION_STALLED, name, "STALLED", customer_text, attribution="explicit_stall"))

    topic = _knowledge_gap_topic(customer_text, db, company_id, explicit_products or products)
    if topic:
        specs.append(_event_spec(CommercialEventType.KNOWLEDGE_GAP_HIT, relevant_names[0] if relevant_names else None, state, customer_text, knowledge_topic=topic))

    # Stable de-duplication within a turn.
    unique: Dict[Tuple[str, Optional[str], str], Dict[str, Any]] = {}
    for spec in specs:
        detail = str(spec.get("objection_type") or spec.get("knowledge_topic") or spec.get("constraint_type") or "")
        unique[(spec["event_type"], spec.get("product_ref"), detail)] = spec
    return list(unique.values())


def _observe_previous_outcome(previous: Any, current_decision: Any, sales_snapshot: Any, customer_text: str) -> Tuple[str, List[Dict[str, Any]]]:
    previous_data = json.loads(previous.decision_json or "{}")
    if not isinstance(previous_data, dict):
        previous_data = {}
    previous_state = str(previous_data.get("state_snapshot_ref") or "UNKNOWN")
    current_state = str(getattr(sales_snapshot, "primary_state", getattr(current_decision, "state_snapshot_ref", "UNKNOWN")))
    outcome = ObservedOutcome.UNKNOWN
    if _extract_hard_budget(customer_text) is not None or _contains(customer_text, ("ساعات", "للشغل", "مقاس", "لون", "budget", "for work")):
        outcome = ObservedOutcome.CUSTOMER_PROVIDED_MISSING_INFORMATION
    elif _purchase_execution_request(customer_text):
        outcome = ObservedOutcome.PURCHASE_EXECUTION_STARTED
    elif _contains(customer_text, ("هاخد", "آخد", "اخد", "i'll take")):
        outcome = ObservedOutcome.PURCHASE_COMMITMENT_APPEARED
    elif _soft_stall(customer_text) or current_state == "STALLED":
        outcome = ObservedOutcome.CONVERSATION_STALLED
    elif _price_objection(customer_text) and previous.strategy in (SellingStrategy.REANCHOR_VALUE.value, SellingStrategy.HANDLE_PRICE_RESISTANCE.value, SellingStrategy.CLARIFY_CRITERION.value):
        outcome = ObservedOutcome.OBJECTION_PERSISTED
    elif _comparison_request(customer_text):
        outcome = ObservedOutcome.COMPARISON_CONTINUED
    elif _STATE_RANK.get(current_state, 0) > _STATE_RANK.get(previous_state, 0):
        outcome = ObservedOutcome.CUSTOMER_PROGRESSED
    elif _STATE_RANK.get(current_state, 0) < _STATE_RANK.get(previous_state, 0):
        outcome = ObservedOutcome.CUSTOMER_REGRESSED
    evidence = [
        {"type": "subsequent_customer_message", "value": customer_text[:500]},
        {"type": "previous_state", "value": previous_state},
        {"type": "subsequent_state", "value": current_state},
        {"type": "causality", "value": "not_claimed"},
    ]
    return outcome.value, evidence


def persist_commercial_turn_in_session(
    db: Session,
    company_id: str,
    lead_id: int,
    channel: str,
    inbound_internal_id: str,
    outbound_internal_id: Optional[str],
    customer_text: str,
    assistant_text: str,
    decision: Any,
    sales_snapshot: Any,
    objection_snapshot: Any = None,
    recommendation_decision: Any = None,
) -> Dict[str, Any]:
    """Stage one canonical commercial turn in the caller's transaction.

    This function deliberately does not commit.  It lets the public-chat path
    commit the assistant message, decision lineage, derived events, canonical
    invalidation, and processing-claim completion as one database unit.
    """
    from database import CommercialDecisionLineage, CommercialEvent, Message, SystemEvent

    source = db.query(Message).filter(
        Message.company_id == company_id,
        Message.internal_message_id == inbound_internal_id,
    ).first()
    # A generated reply, owner reply, or caller-supplied text cannot be
    # promoted into a canonical source row.
    if not source or source.direction != "incoming" or source.sender not in {"user", "customer"} or source.message != customer_text:
        return {"decision_id": None, "events_created": 0, "outbound_message_internal_id": outbound_internal_id, "skipped": "unverified_inbound_source"}
    source_id = source.internal_message_id
    previous = (
        db.query(CommercialDecisionLineage)
        .filter(
            CommercialDecisionLineage.company_id == company_id,
            CommercialDecisionLineage.lead_id == lead_id,
            CommercialDecisionLineage.observed_outcome.is_(None),
        )
        .order_by(desc(CommercialDecisionLineage.created_at), desc(CommercialDecisionLineage.id))
        .first()
    )
    if previous and previous.source_message_internal_id != source_id:
        outcome, outcome_evidence = _observe_previous_outcome(previous, decision, sales_snapshot, customer_text)
        previous.observed_outcome = outcome
        previous.outcome_evidence_json = json.dumps(outcome_evidence, ensure_ascii=False)
        previous.outcome_observed_at = datetime.now(timezone.utc)

    existing = db.query(CommercialDecisionLineage).filter(CommercialDecisionLineage.company_id == company_id, CommercialDecisionLineage.source_message_internal_id == source_id).first()
    created_lineage = existing is None
    if created_lineage:
        existing = CommercialDecisionLineage(
            company_id=company_id,
            lead_id=lead_id,
            source_message_id=source.id,
            source_message_internal_id=source_id,
            objective=getattr(decision, "commercial_objective", CommercialObjective.DO_NOT_ADVANCE.value),
            strategy=getattr(decision, "selling_strategy", SellingStrategy.DO_NOT_PUSH.value),
            next_move=getattr(decision, "next_move", CommercialNextMove.ACKNOWLEDGE_AND_HOLD.value),
            decision_json=json.dumps(_jsonable(decision), ensure_ascii=False),
            evidence_json=json.dumps(_jsonable(getattr(decision, "decision_evidence", [])), ensure_ascii=False),
            escalation_required=bool(getattr(decision, "escalation_required", False)),
            escalation_json=json.dumps(_jsonable(getattr(decision, "escalation", {})), ensure_ascii=False) if getattr(decision, "escalation_required", False) else None,
        )
        db.add(existing)
        db.flush()

    specs = derive_commercial_event_specs(db, company_id, lead_id, customer_text, assistant_text, decision, sales_snapshot, objection_snapshot, recommendation_decision)
    created = 0
    created_types: set[str] = set()
    for spec in specs:
        detail = str(spec.get("objection_type") or spec.get("knowledge_topic") or spec.get("constraint_type") or "")
        digest = _event_hash(company_id, source_id, spec["event_type"], spec.get("product_ref"), detail)
        if db.query(CommercialEvent.id).filter(CommercialEvent.company_id == company_id, CommercialEvent.event_hash == digest).first():
            continue
        evidence_payload = {key: value for key, value in spec.items() if key not in ("event_type", "product_ref", "stage", "source_text", "objection_type")}
        db.add(
            CommercialEvent(
                company_id=company_id,
                lead_id=lead_id,
                message_id=source.id,
                source_message_internal_id=source_id,
                channel=channel,
                event_type=spec["event_type"],
                product_ref=spec.get("product_ref"),
                stage=spec.get("stage"),
                objection_type=spec.get("objection_type"),
                source_text=spec["source_text"],
                evidence_json=json.dumps(_jsonable(evidence_payload), ensure_ascii=False),
                provenance=EVENT_POLICY_VERSION,
                event_hash=digest,
            )
        )
        created += 1
        created_types.add(spec["event_type"])
    progression_types = {
        CommercialEventType.PRODUCT_SELECTED.value,
        CommercialEventType.PURCHASE_INTENT_EXPRESSED.value,
        CommercialEventType.PURCHASE_COMMITMENT.value,
        CommercialEventType.PURCHASE_EXECUTION_REQUEST.value,
    }
    if created_types & progression_types:
        prior_actions = db.query(SystemEvent).filter(
            SystemEvent.company_id == company_id,
            SystemEvent.event_type == "pilot.owner_action_started",
            SystemEvent.created_at <= (source.created_at or datetime.now(timezone.utc)),
        ).order_by(SystemEvent.created_at.desc(), SystemEvent.id.desc()).limit(200).all()
        action = None
        for row in prior_actions:
            try:
                metadata = (json.loads(row.payload or "{}").get("metadata") or {})
            except (TypeError, json.JSONDecodeError):
                metadata = {}
            if str(metadata.get("lead_id")) == str(lead_id):
                action = row
                break
        if action is not None:
            from services.pilot_telemetry_service import record_pilot_event

            record_pilot_event(
                db,
                event_name="subsequent_progress_observed",
                company_id=company_id,
                actor_type="system",
                entity_id=lead_id,
                source="commercial_event_persistence",
                idempotency_key=f"progress:{lead_id}:{source_id}",
                metadata={
                    "lead_id": lead_id,
                    "source_message_internal_id": source_id,
                    "outcome": "temporal_progress_after_owner_action",
                },
                commit=False,
            )
    if created_lineage or created:
        # This is invalidation metadata only. Clients must refetch their
        # canonical CRM view rather than adopt truth from an SSE payload.
        db.add(
            SystemEvent(
                company_id=company_id,
                entity_id=str(lead_id),
                event_type="canonical_commercial.updated",
                payload=json.dumps(
                    {
                        "company_id": company_id,
                        "lead_id": lead_id,
                        "source_message_internal_id": source_id,
                    },
                    ensure_ascii=False,
                ),
            )
        )
    return {"decision_id": existing.id, "events_created": created, "outbound_message_internal_id": outbound_internal_id}


def persist_commercial_turn(
    company_id: str,
    lead_id: int,
    channel: str,
    inbound_internal_id: str,
    outbound_internal_id: Optional[str],
    customer_text: str,
    assistant_text: str,
    decision: Any,
    sales_snapshot: Any,
    objection_snapshot: Any = None,
    recommendation_decision: Any = None,
) -> Dict[str, Any]:
    """Backward-compatible standalone transaction wrapper."""
    import database

    with database.SessionLocal() as db:
        result = persist_commercial_turn_in_session(
            db,
            company_id,
            lead_id,
            channel,
            inbound_internal_id,
            outbound_internal_id,
            customer_text,
            assistant_text,
            decision,
            sales_snapshot,
            objection_snapshot,
            recommendation_decision,
        )
        db.commit()
        return result


_INTEREST_TYPES = {
    CommercialEventType.PRODUCT_MENTIONED.value,
    CommercialEventType.PRODUCT_ASKED_ABOUT.value,
    CommercialEventType.PRODUCT_CONSIDERED.value,
    CommercialEventType.PRODUCT_COMPARED.value,
    CommercialEventType.PRODUCT_REQUESTED_OUT_OF_STOCK.value,
    CommercialEventType.PRODUCT_REQUESTED_UNLISTED.value,
    CommercialEventType.PRICE_REVEALED.value,
    CommercialEventType.OBJECTION_EXPRESSED.value,
}
_PROGRESSION_TYPES = {
    CommercialEventType.PRODUCT_SELECTED.value,
    CommercialEventType.PURCHASE_INTENT_EXPRESSED.value,
    CommercialEventType.PURCHASE_COMMITMENT.value,
    CommercialEventType.PURCHASE_EXECUTION_REQUEST.value,
    CommercialEventType.CONFIRMED_ORDER.value,
    CommercialEventType.PAID.value,
}

# Only explicit request/selection/purchase language may contribute to the
# "currently unavailable demand" metric.  Mere mentions, price objections and
# generic product questions remain useful conversation signals, but are not
# evidence that the customer requested an unavailable item.
_EXPLICIT_PRODUCT_DEMAND_TYPES = {
    CommercialEventType.PRODUCT_REQUESTED_OUT_OF_STOCK.value,
    CommercialEventType.PRODUCT_REQUESTED_UNLISTED.value,
    CommercialEventType.PRODUCT_SELECTED.value,
    CommercialEventType.PURCHASE_INTENT_EXPRESSED.value,
    CommercialEventType.PURCHASE_COMMITMENT.value,
    CommercialEventType.PURCHASE_EXECUTION_REQUEST.value,
}

_RESOLUTION_EVENT_TYPES = {
    CommercialEventType.CONFIRMED_ORDER.value,
    CommercialEventType.PAID.value,
}

_FRICTION_TYPES = {
    CommercialEventType.OBJECTION_EXPRESSED.value,
    CommercialEventType.CONVERSATION_STALLED.value,
    CommercialEventType.KNOWLEDGE_GAP_HIT.value,
    CommercialEventType.WAITING_ON_US.value,
    CommercialEventType.PRODUCT_REQUESTED_OUT_OF_STOCK.value,
    CommercialEventType.PRODUCT_REQUESTED_UNLISTED.value,
}

_CHANNEL_VALUES = {"all", "whatsapp", "web"}

_OPPORTUNITY_RULES: Dict[str, Dict[str, Any]] = {
    CommercialEventType.WAITING_ON_US.value: {
        "priority": 100,
        "reason": "العميل ينتظر ردًا أو قرارًا من الشركة.",
        "recommended_action": "راجع رسالة المصدر وأرسل الآن ردًا مبنيًا على المعلومات الموثوقة.",
    },
    CommercialEventType.PURCHASE_EXECUTION_REQUEST.value: {
        "priority": 96,
        "reason": "العميل سأل صراحة عن كيفية إتمام خطوة الشراء التالية.",
        "recommended_action": "أكد المنتج المختار وقدّم فقط خطوة التنفيذ الموثقة، من دون افتراض وجود طلب.",
    },
    CommercialEventType.PURCHASE_COMMITMENT.value: {
        "priority": 92,
        "reason": "العميل استخدم لغة التزام صريحة؛ هذا لا يثبت إنشاء طلب أو دفعًا.",
        "recommended_action": "أكد المنتج والكمية ثم قدّم التفصيلة الموثقة التالية لإتمام الإجراء.",
    },
    CommercialEventType.PURCHASE_INTENT_EXPRESSED.value: {
        "priority": 88,
        "reason": "العميل عبّر صراحة عن نية شراء.",
        "recommended_action": "عالج العائق الموثق التالي واقترح خطوة عملية واحدة فقط.",
    },
    CommercialEventType.PRODUCT_REQUESTED_OUT_OF_STOCK.value: {
        "priority": 87,
        "reason": "يوجد طلب مرصود على منتج يؤكد الكتالوج الموثوق أن مخزونه الحالي نافد.",
        "recommended_action": "اعرض بديلًا موثوقًا متاحًا أو احسم قرار إعادة التوريد من دون وعد بموعد غير موثق.",
    },
    CommercialEventType.PRODUCT_REQUESTED_UNLISTED.value: {
        "priority": 86,
        "reason": "العميل طلب صراحة منتجًا لا يطابق أي عنصر في الكتالوج الحالي.",
        "recommended_action": "أكد المواصفة المطلوبة ثم اعرض بديلًا موثوقًا أو ارفع قرار إضافة المنتج للكتالوج.",
    },
    CommercialEventType.OWNER_INTERVENTION_REQUIRED.value: {
        "priority": 85,
        "reason": "هناك استثناء تجاري موثق يحتاج مراجعة صاحب الصلاحية.",
        "recommended_action": "راجع دليل المصدر واتخذ القرار التجاري داخل الحدود الموثقة.",
    },
    CommercialEventType.OBJECTION_EXPRESSED.value: {
        "priority": 80,
        "reason": "العميل عبّر عن اعتراض موثق.",
        "recommended_action": "عالج الاعتراض المذكور بحقائق موثوقة واسأل سؤال توضيح واحدًا عند الحاجة.",
    },
    CommercialEventType.KNOWLEDGE_GAP_HIT.value: {
        "priority": 78,
        "reason": "معلومة طلبها العميل غير موجودة في معرفة البيزنس الموثوقة.",
        "recommended_action": "أكد المعلومة الناقصة وأضف مصدرها المعتمد قبل الرد.",
    },
    CommercialEventType.CONVERSATION_STALLED.value: {
        "priority": 72,
        "reason": "العميل أجّل القرار أو أوقفه صراحة.",
        "recommended_action": "استخدم متابعة هادئة مرتبطة بآخر احتياج صرّح به العميل.",
    },
}


_CLASSIFICATION_AR = {
    "STRONG_PERFORMER": "أداء قوي",
    "LEAKAGE_CANDIDATE": "مرشح لتسرب الطلب",
    "HIDDEN_WINNER": "فائز خفي محتمل",
    "LOW_SIGNAL": "إشارة محدودة",
    "INSUFFICIENT_EVIDENCE": "دليل غير كافٍ",
}


def _classification(interest: int, progressed: int, high_interest_threshold: int) -> Tuple[str, str]:
    if interest < MIN_CLASSIFICATION_SAMPLE:
        return "INSUFFICIENT_EVIDENCE", "العينة أقل من الحد الأدنى؛ هذه إشارة مبكرة وليست استنتاجًا."
    high_interest = interest >= high_interest_threshold
    higher_progression = progressed >= 2 and progressed * 2 >= interest
    if high_interest and higher_progression:
        return "STRONG_PERFORMER", "اهتمام مرتفع مع أدلة تقدم لاحقة في محادثات متعددة."
    if high_interest and not higher_progression:
        return "LEAKAGE_CANDIDATE", "اهتمام مرتفع لكن أدلة التقدم اللاحقة محدودة."
    if not high_interest and higher_progression:
        return "HIDDEN_WINNER", "اهتمام أقل نسبيًا مع تقدم لاحق في معظم المحادثات المرصودة."
    return "LOW_SIGNAL", "الاهتمام والتقدم كلاهما محدودان؛ يحتاج المنتج إلى مزيد من الأدلة."


def _serialize_event(row: Any, lead_names: Dict[int, str]) -> Dict[str, Any]:
    try:
        detail = json.loads(row.evidence_json or "{}")
    except (TypeError, ValueError):
        detail = {}
    return {
        "event_id": row.id,
        "lead_id": row.lead_id,
        "customer_name": lead_names.get(row.lead_id, f"عميل {row.lead_id}"),
        "source_message_internal_id": row.source_message_internal_id,
        "event_type": row.event_type,
        "product": row.product_ref,
        "stage": row.stage,
        "objection_type": row.objection_type,
        "source_text": row.source_text,
        "channel": row.channel,
        "observed_at": row.observed_at.isoformat() if row.observed_at else None,
        "provenance": row.provenance,
        "detail": detail,
    }


def _recommendation_contract(kind: str, product: Optional[str], evidence: List[Dict[str, Any]], facts: Dict[str, Any]) -> Dict[str, Any]:
    label = product or "المحادثات"
    if kind == "LEAKAGE_CANDIDATE":
        return {
            "observed": f"{label} يظهر في {facts['interest']} محادثات مهتمة، بينما ظهر تقدم لاحق في {facts['progressed']} فقط.",
            "evidence": evidence,
            "hypothesis": "قد لا يكون فرق القيمة أو الملاءمة واضحًا عند نقطة القرار.",
            "unknown": "لا نعرف هل السبب سقف الميزانية أم عرض القيمة أم الملاءمة أم منافس خارجي.",
            "recommendation": "راجع شرح الملاءمة والفرق المرتبط بالاحتياج قبل دفع العميل للقرار.",
            "experiment": "اختبر شرحًا قصيرًا يربط فرق المنتج باحتياج صريح في المحادثات المؤهلة فقط.",
            "measure": "راقب عدد المحادثات المؤهلة التي يظهر فيها دليل تقدم بعد نقطة الضعف مقارنة بالفترة السابقة.",
            "do_not_conclude": "لا تستنتج خفض السعر أو إيقاف المنتج من هذه الملاحظة وحدها.",
        }
    if kind == "KNOWLEDGE_GAP":
        topic = facts.get("topic", "معلومة")
        return {
            "observed": f"تكرر سؤال غير مدعوم ببيانات موثوقة حول {topic} في {facts['count']} محادثات.",
            "evidence": evidence,
            "hypothesis": "إضافة حقيقة موثوقة قد تقلل انتظار الرد اليدوي.",
            "unknown": "لا نعرف بعد أثر المعلومة الناقصة على قرار الشراء.",
            "recommendation": "أضف إجابة معتمدة ومصدرها إلى قاعدة معرفة الشركة.",
            "experiment": "أضف الحقيقة لمدة أسبوع وراقب هل يقل تكرار KNOWLEDGE_GAP_HIT لنفس الموضوع.",
            "measure": "عدد المحادثات التي تحتاج تصعيدًا لنفس السؤال بعد الإضافة.",
            "do_not_conclude": "لا تعتبر كل محادثة تسأل عن المعلومة صفقة مفقودة.",
        }
    if kind == "OWNER_RESPONSE":
        return {
            "observed": f"توجد {facts['count']} محادثات عليها دليل انتظار لتدخل تجاري من الشركة.",
            "evidence": evidence,
            "hypothesis": "زمن استجابة المالك قد يؤثر في استمرار الزخم.",
            "unknown": "لا يوجد دليل كافٍ على خسارة بيع أو قيمة مالية.",
            "recommendation": "راجع طلبات الاستثناء والشراء المنتظرة وحدد مالكًا وموعد استجابة.",
            "experiment": "طبّق حدًا تشغيليًا لمراجعة WAITING_ON_US مرتين يوميًا.",
            "measure": "مدة الانتظار وعدد الحالات التي تتلقى تدخلًا موثقًا.",
            "do_not_conclude": "لا تحسب إيرادًا ضائعًا من حالات الانتظار.",
        }
    if kind == "OBJECTION":
        return {
            "observed": f"الاعتراض {facts['objection']} تركز حول {label} في {facts['count']} محادثات.",
            "evidence": evidence,
            "hypothesis": "قد توجد فجوة في الملاءمة أو القيمة أو القيد التجاري.",
            "unknown": "تكرار الاعتراض لا يثبت سببًا جذريًا ولا يثبت خسارة البيع.",
            "recommendation": "راجع المحادثات الداعمة وافصل سقف الميزانية عن فجوة القيمة قبل تعديل العرض.",
            "experiment": "اختبر سؤال توضيح واحدًا يميز نوع الاعتراض قبل الرد.",
            "measure": "نوع الدليل اللاحق: قيد ميزانية، استمرار مقارنة، تقدم، أو توقف.",
            "do_not_conclude": "لا تخفض السعر تلقائيًا.",
        }
    return {
        "observed": f"{label} مصنف كـ {_CLASSIFICATION_AR.get(kind, kind)} بناءً على أحداث محادثة صريحة.",
        "evidence": evidence,
        "hypothesis": "قد يستحق المنتج مراجعة موضعه في الحوار التجاري.",
        "unknown": "لا توجد بيانات دفع أو طلبات مؤكدة تكفي لقياس مبيعات المنتج.",
        "recommendation": "راجع الأدلة قبل تغيير التسعير أو الاستثمار التسويقي.",
        "experiment": "اختبر توضيح الملاءمة على عينة محدودة من المحادثات المؤهلة.",
        "measure": "أحداث التقدم الصريحة اللاحقة، لا الانطباعات أو الإيراد المفترض.",
        "do_not_conclude": "التقدم في المحادثة ليس طلبًا مؤكدًا ولا دفعًا.",
    }


def _normalize_channel_filter(channel: Optional[str]) -> str:
    normalized = str(channel or "all").strip().casefold()
    if normalized not in _CHANNEL_VALUES:
        raise ValueError("channel must be one of: all, whatsapp, web")
    return normalized


def _lead_matches_channel(lead: Any, channel: str) -> bool:
    if channel == "all":
        return True
    value = str(getattr(lead, "channel_type", "") or "").strip().upper()
    if channel == "whatsapp":
        return value.startswith("WHATSAPP")
    return value in {"VELOR_WEB_CHAT", "WEB_CHAT", "WEB"}


def _latest_message_direction_by_lead(
    db: Session,
    company_id: str,
    leads: Sequence[Any],
) -> Dict[int, str]:
    """Return latest persisted message direction for each lead in one bounded query."""
    from database import Message, get_phone_variants, normalize_whatsapp_number

    lead_by_user_id: Dict[str, int] = {}
    for lead in leads:
        identifiers: set[str] = set()
        for value in (
            getattr(lead, "phone", None),
            getattr(lead, "whatsapp_number", None),
            getattr(lead, "whatsapp_jid", None),
            getattr(lead, "customer_provided_phone", None),
        ):
            if not value:
                continue
            identifiers.add(str(value))
            normalized = normalize_whatsapp_number(str(value))
            if normalized:
                identifiers.add(normalized)
                identifiers.update(get_phone_variants(normalized))
        external_customer_id = getattr(lead, "external_customer_id", None)
        if external_customer_id:
            identifiers.add(str(external_customer_id))
        for identifier in identifiers:
            lead_by_user_id.setdefault(identifier, lead.id)

    if not lead_by_user_id:
        return {}

    ranked = (
        db.query(
            Message.id.label("message_id"),
            func.row_number()
            .over(
                partition_by=Message.user_id,
                order_by=(Message.created_at.desc(), Message.id.desc()),
            )
            .label("row_number"),
        )
        .filter(
            Message.company_id == company_id,
            Message.user_id.in_(list(lead_by_user_id)),
            Message.is_deleted == False,
        )
        .subquery()
    )
    latest_identifier_rows = (
        db.query(Message)
        .join(ranked, Message.id == ranked.c.message_id)
        .filter(ranked.c.row_number == 1)
        .all()
    )

    latest_by_lead: Dict[int, Any] = {}
    for message in latest_identifier_rows:
        lead_id = lead_by_user_id.get(message.user_id)
        if lead_id is None:
            continue
        current = latest_by_lead.get(lead_id)

        def sort_key(row: Any) -> Tuple[float, int]:
            created_at = getattr(row, "created_at", None)
            if created_at is None:
                timestamp = 0.0
            else:
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)
                timestamp = created_at.astimezone(timezone.utc).timestamp()
            return timestamp, int(getattr(row, "id", 0) or 0)

        if current is None or sort_key(message) > sort_key(current):
            latest_by_lead[lead_id] = message
    return {
        lead_id: str(getattr(message, "direction", "") or "").casefold()
        for lead_id, message in latest_by_lead.items()
    }


def _event_date(row: Any) -> Optional[str]:
    observed_at = getattr(row, "observed_at", None)
    if observed_at is None:
        return None
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)
    return observed_at.astimezone(timezone.utc).date().isoformat()


def _distinct_lead_ids(rows: Iterable[Any], event_types: Iterable[str]) -> set[int]:
    allowed = set(event_types)
    return {row.lead_id for row in rows if row.event_type in allowed}


def _event_timestamp(row: Any) -> float:
    observed_at = getattr(row, "observed_at", None)
    if observed_at is None:
        return 0.0
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)
    return observed_at.astimezone(timezone.utc).timestamp()


def _event_order_key(row: Any) -> Tuple[float, int]:
    """Return deterministic conversation-event order, including same-turn rows."""
    return _event_timestamp(row), int(getattr(row, "id", 0) or 0)


def _demand_progression_state(rows: Iterable[Any]) -> Tuple[set[int], set[int]]:
    """Return demand leads and leads progressing after their latest demand.

    A progression observed before a newer demand signal must not resolve that
    newer demand.  Event id is the stable tie-breaker for deterministic events
    derived from the same source turn and timestamp.
    """
    latest_demand_by_lead: Dict[int, Any] = {}
    progression_rows_by_lead: Dict[int, List[Any]] = defaultdict(list)
    for row in rows:
        if row.event_type in _INTEREST_TYPES:
            current = latest_demand_by_lead.get(row.lead_id)
            if current is None or _event_order_key(row) > _event_order_key(current):
                latest_demand_by_lead[row.lead_id] = row
        if row.event_type in _PROGRESSION_TYPES:
            progression_rows_by_lead[row.lead_id].append(row)

    progressed: set[int] = set()
    for lead_id, demand_row in latest_demand_by_lead.items():
        demand_key = _event_order_key(demand_row)
        if any(_event_order_key(row) > demand_key for row in progression_rows_by_lead.get(lead_id, [])):
            progressed.add(lead_id)
    return set(latest_demand_by_lead), progressed


def _projection_observed_at(item: Dict[str, Any]) -> Optional[datetime]:
    raw = (item.get("freshness") or {}).get("observed_at") or item.get("created_at")
    if not raw:
        return None
    try:
        value = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _build_daily_trend(events: Sequence[Any], start_date: Any, window_days: int) -> List[Dict[str, Any]]:
    by_day: Dict[str, List[Any]] = defaultdict(list)
    for row in events:
        day = _event_date(row)
        if day:
            by_day[day].append(row)

    trend: List[Dict[str, Any]] = []
    latest_demand_key_by_lead: Dict[int, Tuple[float, int]] = {}
    progressed_after_latest_demand: Dict[int, bool] = {}
    for offset in range(window_days):
        day = (start_date + timedelta(days=offset)).isoformat()
        rows = sorted(by_day.get(day, []), key=_event_order_key)
        demand = _distinct_lead_ids(rows, _INTEREST_TYPES)
        progressed_today: set[int] = set()
        for event in rows:
            event_key = _event_order_key(event)
            if event.event_type in _INTEREST_TYPES:
                latest_demand_key_by_lead[event.lead_id] = event_key
                progressed_after_latest_demand[event.lead_id] = False
            if (
                event.event_type in _PROGRESSION_TYPES
                and event.lead_id in latest_demand_key_by_lead
                and event_key > latest_demand_key_by_lead[event.lead_id]
            ):
                progressed_after_latest_demand[event.lead_id] = True
                progressed_today.add(event.lead_id)
        cumulative_demand = set(latest_demand_key_by_lead)
        cumulative_progressed = {
            lead_id
            for lead_id, did_progress in progressed_after_latest_demand.items()
            if did_progress
        }
        unresolved_backlog = cumulative_demand - cumulative_progressed
        trend.append(
            {
                "date": day,
                "source_conversations": len({row.lead_id for row in rows}),
                "commercial_events": len(rows),
                "demand_conversations": len(demand),
                "progressed_conversations": len(progressed_today),
                "demand_without_progress": len(unresolved_backlog),
                "demand_without_progress_backlog": len(unresolved_backlog),
                "cumulative_demand_conversations": len(cumulative_demand),
                "cumulative_progressed_conversations": len(cumulative_progressed),
                "purchase_intent": len(_distinct_lead_ids(rows, {CommercialEventType.PURCHASE_INTENT_EXPRESSED.value})),
                "purchase_commitment": len(_distinct_lead_ids(rows, {CommercialEventType.PURCHASE_COMMITMENT.value})),
                "purchase_execution": len(_distinct_lead_ids(rows, {CommercialEventType.PURCHASE_EXECUTION_REQUEST.value})),
                "objection": len(_distinct_lead_ids(rows, {CommercialEventType.OBJECTION_EXPRESSED.value})),
                "stalled": len(_distinct_lead_ids(rows, {CommercialEventType.CONVERSATION_STALLED.value})),
                "knowledge_gap": len(_distinct_lead_ids(rows, {CommercialEventType.KNOWLEDGE_GAP_HIT.value})),
                "waiting_on_us": len(_distinct_lead_ids(rows, {CommercialEventType.WAITING_ON_US.value})),
            }
        )
    return trend


def _build_opportunity_queue(
    events: Sequence[Any],
    lead_names: Dict[int, str],
    current_product_states: Optional[Dict[str, str]] = None,
    eligible_lead_ids: Optional[set[int]] = None,
    *,
    limit: int = 25,
) -> List[Dict[str, Any]]:
    product_states = current_product_states or {}

    def is_current_candidate(row: Any) -> bool:
        product_key = str(getattr(row, "product_ref", "") or "").casefold()
        if row.event_type == CommercialEventType.PRODUCT_REQUESTED_OUT_OF_STOCK.value:
            return bool(product_key) and product_states.get(product_key) == "out_of_stock"
        if row.event_type == CommercialEventType.PRODUCT_REQUESTED_UNLISTED.value:
            return bool(product_key) and product_states.get(product_key) == "unlisted"
        if row.event_type == CommercialEventType.WAITING_ON_US.value:
            # Waiting is a current operational state, not a durable historical
            # event. The owner-attention projection is its canonical source.
            return False
        return True

    by_lead: Dict[int, List[Any]] = defaultdict(list)
    for row in events:
        if eligible_lead_ids is not None and row.lead_id not in eligible_lead_ids:
            continue
        by_lead[row.lead_id].append(row)

    queue: List[Dict[str, Any]] = []
    for lead_id, rows in by_lead.items():
        rows = sorted(rows, key=_event_order_key)
        state_rows = [
            row
            for row in rows
            if row.event_type
            in (_INTEREST_TYPES | _PROGRESSION_TYPES | _FRICTION_TYPES | set(_OPPORTUNITY_RULES))
        ]
        reason_code = None
        rule: Optional[Dict[str, Any]] = None
        source = None

        latest_state = state_rows[-1] if state_rows else None
        if latest_state and latest_state.event_type in _RESOLUTION_EVENT_TYPES:
            # Confirmed order/payment is a trusted terminal outcome.  Never
            # resurrect an older objection or purchase request as a current task.
            continue
        if latest_state and latest_state.event_type == CommercialEventType.WAITING_ON_US.value:
            # Historical waiting rows are not current state.  The canonical
            # owner-attention projection either supplies this task or resolves it.
            continue

        if (
            latest_state
            and latest_state.event_type in _OPPORTUNITY_RULES
            and is_current_candidate(latest_state)
        ):
            source = latest_state
            reason_code = source.event_type
            rule = _OPPORTUNITY_RULES[reason_code]
        else:
            demand, progressed = _demand_progression_state(rows)
            if lead_id not in demand or lead_id in progressed:
                continue
            source = next((row for row in reversed(rows) if row.event_type in _INTEREST_TYPES), rows[-1])
            reason_code = "DEMAND_WITHOUT_PROGRESS"
            rule = {
                "priority": 60,
                "reason": "المحادثة تحتوي على طلب منتج من دون إشارة تقدم صريحة داخل الفترة.",
                "recommended_action": "راجع آخر احتياج واقترح خطوة واحدة موثوقة من دون افتراض نتيجة.",
            }

        serialized_source = _serialize_event(source, lead_names)
        supporting = [
            _serialize_event(row, lead_names)
            for row in reversed(rows)
            if row.event_type in (_INTEREST_TYPES | _PROGRESSION_TYPES | _FRICTION_TYPES)
        ][:5]
        queue.append(
            {
                "id": f"commercial-opportunity:{lead_id}:{reason_code}:{source.source_message_internal_id}",
                "lead_id": lead_id,
                "customer_name": lead_names.get(lead_id, f"عميل {lead_id}"),
                "priority": int(rule["priority"]),
                "priority_score": int(rule["priority"]),
                "reason_code": reason_code,
                "reason": rule["reason"],
                "action": rule["recommended_action"],
                "recommended_action": rule["recommended_action"],
                "product": source.product_ref,
                "channel": source.channel,
                "observed_at": serialized_source.get("observed_at"),
                "_observed_timestamp": _event_timestamp(source),
                "source_message_internal_id": source.source_message_internal_id,
                "source": serialized_source,
                "evidence": supporting,
                "outcome_scope": "conversation_progress_only",
            }
        )

    queue.sort(
        key=lambda item: (
            -(item.get("priority") or 0),
            -(item.get("_observed_timestamp") or 0),
            item.get("lead_id") or 0,
        )
    )
    result = queue[: max(1, min(int(limit or 25), 100))]
    for item in result:
        item.pop("_observed_timestamp", None)
    return result


def _build_current_attention_queue(
    projection_items: Sequence[Dict[str, Any]],
    leads_by_id: Dict[int, Any],
    eligible_lead_ids: set[int],
) -> List[Dict[str, Any]]:
    class_priority = {
        "WAITING_ON_US": 100,
        "READY_TO_CLOSE": 96,
        "STUCK_ON_OBJECTION": 80,
        "REGRESSING": 72,
    }
    class_label = {
        "WAITING_ON_US": "ينتظر ردنا",
        "READY_TO_CLOSE": "جاهز لخطوة شراء",
        "STUCK_ON_OBJECTION": "متوقف عند اعتراض",
        "REGRESSING": "زخمه يتراجع",
    }
    current_by_lead: Dict[int, Dict[str, Any]] = {}
    for item in projection_items:
        lead_id = item.get("lead_id")
        if lead_id not in eligible_lead_ids or lead_id in current_by_lead:
            continue
        current_by_lead[lead_id] = item

    queue: List[Dict[str, Any]] = []
    for lead_id, item in current_by_lead.items():
        lead = leads_by_id[lead_id]
        projection_class = str(item.get("projection_class") or item.get("type") or "CURRENT_ATTENTION")
        evidence = list(item.get("evidence") or [])
        source_evidence = evidence[0] if evidence else {}
        source_message_id = source_evidence.get("source_message_internal_id")
        observed_at = (item.get("freshness") or {}).get("observed_at") or source_evidence.get("created_at")
        priority = max(int(item.get("score") or 0), class_priority.get(projection_class, 70))
        product = next(
            (
                row.get("normalized_value")
                for row in evidence
                if row.get("type") == "product_mention" and row.get("normalized_value")
            ),
            None,
        )
        source = {
            "lead_id": lead_id,
            "customer_name": item.get("lead_name") or getattr(lead, "name", None),
            "source_message_internal_id": source_message_id,
            "source_text": source_evidence.get("source_text"),
            "channel": getattr(lead, "channel_type", None),
            "observed_at": observed_at,
            "provenance": "owner_attention_projection",
            "detail": {
                "projection_class": projection_class,
                "operational_reason_code": item.get("reason_code"),
            },
        }
        queue.append(
            {
                "id": item.get("id") or f"current-attention:{lead_id}:{projection_class}",
                "lead_id": lead_id,
                "customer_name": source["customer_name"],
                "title": item.get("title") or class_label.get(projection_class, "حالة تحتاج مراجعة"),
                "status": projection_class,
                "status_label": class_label.get(projection_class, "تحتاج مراجعة"),
                "priority": priority,
                "priority_score": priority,
                "reason_code": item.get("reason_code") or projection_class,
                "operational_reason_code": item.get("reason_code"),
                "reason": item.get("why") or "توجد حالة حالية تحتاج مراجعة صاحب البيزنس.",
                "action": item.get("what_next") or "راجع المحادثة وحدد الخطوة التالية من الدليل الحالي.",
                "recommended_action": item.get("what_next") or "راجع المحادثة وحدد الخطوة التالية من الدليل الحالي.",
                "product": product,
                "channel": getattr(lead, "channel_type", None),
                "observed_at": observed_at,
                "source_message_internal_id": source_message_id,
                "source": source,
                "evidence": evidence[:5],
                "outcome_scope": "current_owner_attention_projection",
            }
        )
    queue.sort(key=lambda item: (-(item.get("priority") or 0), str(item.get("observed_at") or "")), reverse=False)
    return queue


def build_business_commercial_intelligence(
    db: Session,
    company_id: str,
    days: int = 90,
    channel: str = "all",
) -> Dict[str, Any]:
    from database import CommercialEvent, Lead
    from services.product_context_service import get_company_products

    window_days = max(1, min(int(days or 90), 365))
    channel_filter = _normalize_channel_filter(channel)
    now = datetime.now(timezone.utc)
    start_date = now.date() - timedelta(days=window_days - 1)
    since = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)
    query = (
        db.query(CommercialEvent)
        .join(Lead, Lead.id == CommercialEvent.lead_id)
        .filter(
            CommercialEvent.company_id == company_id,
            CommercialEvent.observed_at >= since,
            Lead.company_id == company_id,
            Lead.is_deleted == False,
            Lead.is_test == False,
        )
    )
    if channel_filter == "whatsapp":
        query = query.filter(func.upper(CommercialEvent.channel).like("WHATSAPP%"))
    elif channel_filter == "web":
        query = query.filter(func.upper(CommercialEvent.channel).in_(("VELOR_WEB_CHAT", "WEB_CHAT", "WEB")))
    events = query.order_by(CommercialEvent.observed_at.asc(), CommercialEvent.id.asc()).all()
    from services.trusted_outcome_contract import is_trusted_outcome_provenance

    events = [
        row
        for row in events
        if row.event_type not in _RESOLUTION_EVENT_TYPES
        or is_trusted_outcome_provenance(row.provenance)
    ]
    lead_ids = sorted({row.lead_id for row in events})
    leads = (
        db.query(Lead)
        .filter(
            Lead.company_id == company_id,
            Lead.id.in_(lead_ids),
            Lead.is_deleted == False,
            Lead.is_test == False,
        )
        .all()
        if lead_ids
        else []
    )
    lead_names = {lead.id: lead.name or lead.external_customer_id or f"عميل {lead.id}" for lead in leads}

    from services.owner_attention_projection_service import get_owner_attention_projection

    # Projection freshness comes from persisted message/evidence timestamps, so
    # current owner-attention state can honor the same trusted reporting window.
    attention_projection = get_owner_attention_projection(db, company_id, limit=100)
    raw_projection_items = list(attention_projection.get("items") or [])
    projection_items = []
    projection_items_without_timestamp = 0
    for item in raw_projection_items:
        observed_at = _projection_observed_at(item)
        if observed_at is None:
            projection_items_without_timestamp += 1
            continue
        if observed_at >= since:
            projection_items.append(item)
    projection_lead_ids = {
        int(item["lead_id"])
        for item in projection_items
        if item.get("lead_id") is not None
    }
    projection_leads = (
        db.query(Lead)
        .filter(
            Lead.company_id == company_id,
            Lead.id.in_(projection_lead_ids),
            Lead.is_deleted == False,
            Lead.is_test == False,
        )
        .all()
        if projection_lead_ids
        else []
    )
    action_leads_by_id = {lead.id: lead for lead in [*leads, *projection_leads]}
    latest_direction_by_lead = _latest_message_direction_by_lead(
        db,
        company_id,
        list(action_leads_by_id.values()),
    )

    def is_open_lead(lead: Any) -> bool:
        stage = str(getattr(lead, "stage", "") or "").strip().casefold()
        status = str(getattr(lead, "status", "") or "").strip().casefold()
        return stage not in {"won", "lost"} and status not in {"won", "lost"}

    event_opportunity_lead_ids = {
        lead.id
        for lead in leads
        if is_open_lead(lead) and latest_direction_by_lead.get(lead.id) != "outgoing"
    }
    projection_opportunity_lead_ids = {
        lead.id
        for lead in projection_leads
        if is_open_lead(lead)
        and _lead_matches_channel(lead, channel_filter)
        and latest_direction_by_lead.get(lead.id) != "outgoing"
    }
    current_projection_items = [
        item
        for item in projection_items
        if item.get("lead_id") in projection_opportunity_lead_ids
    ]
    current_waiting_items = [
        item
        for item in current_projection_items
        if item.get("projection_class") == "WAITING_ON_US"
    ]
    catalog_products = {
        str(getattr(product, "name", "")).casefold(): product
        for product in get_company_products(db, company_id)
        if getattr(product, "name", None)
    }

    by_product: Dict[str, List[Any]] = defaultdict(list)
    for row in events:
        if row.product_ref:
            by_product[row.product_ref].append(row)

    raw_interest = []
    for rows in by_product.values():
        raw_interest.append(len({row.lead_id for row in rows if row.event_type in _INTEREST_TYPES}))
    high_interest_threshold = max(4, int(median(raw_interest))) if raw_interest else 4

    products: List[Dict[str, Any]] = []
    current_product_states: Dict[str, str] = {}
    current_unavailable_leads_by_product: Dict[str, set[int]] = defaultdict(set)
    for product, rows in by_product.items():
        counts = Counter(row.event_type for row in rows)
        interest_leads, progressed_demand_leads = _demand_progression_state(rows)
        demand_without_progress_leads = interest_leads - progressed_demand_leads
        classification, uncertainty = _classification(len(interest_leads), len(progressed_demand_leads), high_interest_threshold)
        stage_counts = Counter()
        for row in rows:
            if row.stage:
                stage_counts[row.stage] += 1
        catalog_product = catalog_products.get(product.casefold())
        catalog_match_status = (
            "matched"
            if catalog_product is not None
            else (
                "unlisted"
                if any(row.event_type == CommercialEventType.PRODUCT_REQUESTED_UNLISTED.value for row in rows)
                else "unknown"
            )
        )
        stock_value = getattr(catalog_product, "stock", None) if catalog_product is not None else None
        stock_state = _catalog_stock_state(stock_value)
        current_product_states[product.casefold()] = "unlisted" if catalog_match_status == "unlisted" else stock_state
        explicit_unavailable_leads = {
            row.lead_id
            for row in rows
            if row.event_type
            in {
                CommercialEventType.PRODUCT_REQUESTED_OUT_OF_STOCK.value,
                CommercialEventType.PRODUCT_REQUESTED_UNLISTED.value,
            }
        }
        explicit_product_demand_leads = {
            row.lead_id
            for row in rows
            if row.event_type in _EXPLICIT_PRODUCT_DEMAND_TYPES
        }
        if stock_state == "out_of_stock":
            current_unavailable_leads = set(explicit_product_demand_leads)
        elif catalog_match_status == "unlisted":
            current_unavailable_leads = {
                row.lead_id
                for row in rows
                if row.event_type == CommercialEventType.PRODUCT_REQUESTED_UNLISTED.value
            }
        else:
            # A historical stock-out signal is not current unavailability once
            # the trusted catalog says the product is available (or unknown).
            current_unavailable_leads = set()
        current_unavailable_leads_by_product[product.casefold()].update(current_unavailable_leads)
        friction_counts = {
            "objection": len({row.lead_id for row in rows if row.event_type == CommercialEventType.OBJECTION_EXPRESSED.value}),
            "stalled": len({row.lead_id for row in rows if row.event_type == CommercialEventType.CONVERSATION_STALLED.value}),
            "knowledge_gap": len({row.lead_id for row in rows if row.event_type == CommercialEventType.KNOWLEDGE_GAP_HIT.value}),
            "waiting_on_us": len({row.lead_id for row in rows if row.event_type == CommercialEventType.WAITING_ON_US.value}),
            "unavailable_request": len(explicit_unavailable_leads),
        }
        product_payload = {
            "product": product,
            "classification": classification,
            "classification_label": _CLASSIFICATION_AR[classification],
            "uncertainty": uncertainty,
            "interest_conversations": len(interest_leads),
            "demand_conversations": len(interest_leads),
            "progressed_conversations": len(progressed_demand_leads),
            "progression_rate": round(len(progressed_demand_leads) / len(interest_leads), 4) if interest_leads else None,
            "progression_rate_pct": round((len(progressed_demand_leads) / len(interest_leads)) * 100, 1) if interest_leads else None,
            "demand_gap": len(demand_without_progress_leads),
            "demand_without_progress": len(demand_without_progress_leads),
            "purchase_intent": len({row.lead_id for row in rows if row.event_type == CommercialEventType.PURCHASE_INTENT_EXPRESSED.value}),
            "purchase_commitment": len({row.lead_id for row in rows if row.event_type == CommercialEventType.PURCHASE_COMMITMENT.value}),
            "purchase_execution": len({row.lead_id for row in rows if row.event_type == CommercialEventType.PURCHASE_EXECUTION_REQUEST.value}),
            "explicit_demand_conversations": len(explicit_product_demand_leads),
            "friction_counts": friction_counts,
            "catalog_match_status": catalog_match_status,
            "current_catalog_stock_state": stock_state,
            "current_stock_state": stock_state,
            "current_catalog_stock": _jsonable(stock_value),
            "current_unavailable_demand": len(current_unavailable_leads),
            "current_unavailable_demand_definition": "explicit_request_or_purchase_intent_against_current_catalog_unavailability",
            "event_counts": dict(sorted(counts.items())),
            "stage_counts": dict(sorted(stage_counts.items())),
            "source_lead_ids": sorted({row.lead_id for row in rows}),
            "attribution_note": "كل رقم يمثل حدثًا أو محادثة صريحة حسب الاسم؛ لا يمثل معدل تحويل أو مبيعات.",
        }
        products.append(product_payload)
    products.sort(key=lambda item: (-item["interest_conversations"], item["product"].casefold()))

    insights: List[Dict[str, Any]] = []
    for product in products:
        if product["classification"] not in ("LEAKAGE_CANDIDATE", "STRONG_PERFORMER", "HIDDEN_WINNER"):
            continue
        rows = by_product[product["product"]]
        evidence = [_serialize_event(row, lead_names) for row in rows if row.event_type in (_INTEREST_TYPES | _PROGRESSION_TYPES | {CommercialEventType.OBJECTION_EXPRESSED.value})][:8]
        contract = _recommendation_contract(product["classification"], product["product"], evidence, {"interest": product["interest_conversations"], "progressed": product["progressed_conversations"]})
        insights.append({"id": f"product:{product['classification']}:{product['product']}", "type": product["classification"], "priority": 90 if product["classification"] == "LEAKAGE_CANDIDATE" else 55, "title": f"{product['classification_label']}: {product['product']}", "product": product["product"], **contract})

    objection_groups: Dict[Tuple[Optional[str], str], List[Any]] = defaultdict(list)
    for row in events:
        if row.event_type == CommercialEventType.OBJECTION_EXPRESSED.value:
            objection_groups[(row.product_ref, row.objection_type or "UNCLASSIFIED_OBJECTION")].append(row)
    for (product, objection), rows in sorted(objection_groups.items(), key=lambda item: len({row.lead_id for row in item[1]}), reverse=True):
        conversation_count = len({row.lead_id for row in rows})
        if conversation_count < 2:
            continue
        evidence = [_serialize_event(row, lead_names) for row in rows[:8]]
        contract = _recommendation_contract("OBJECTION", product, evidence, {"objection": objection, "count": conversation_count})
        insights.append({"id": f"objection:{product}:{objection}", "type": "OBJECTION_CONCENTRATION", "priority": 80, "title": f"اعتراض متكرر حول {product or 'عدة محادثات'}", "product": product, **contract})

    gap_groups: Dict[str, List[Any]] = defaultdict(list)
    for row in events:
        if row.event_type == CommercialEventType.KNOWLEDGE_GAP_HIT.value:
            try:
                topic = json.loads(row.evidence_json or "{}").get("knowledge_topic", "unknown_fact")
            except (TypeError, ValueError):
                topic = "unknown_fact"
            gap_groups[topic].append(row)
    for topic, rows in sorted(gap_groups.items(), key=lambda item: len({row.lead_id for row in item[1]}), reverse=True):
        conversation_count = len({row.lead_id for row in rows})
        if conversation_count < 2:
            continue
        evidence = [_serialize_event(row, lead_names) for row in rows[:8]]
        contract = _recommendation_contract("KNOWLEDGE_GAP", None, evidence, {"topic": topic, "count": conversation_count})
        insights.append({"id": f"knowledge:{topic}", "type": "KNOWLEDGE_GAP", "priority": 85, "title": "معلومة ناقصة تعطل محادثات", **contract})

    if current_waiting_items:
        evidence = []
        for item in current_waiting_items[:10]:
            source = next(iter(item.get("evidence") or []), {})
            evidence.append(
                {
                    "lead_id": item.get("lead_id"),
                    "customer_name": item.get("lead_name"),
                    "source_message_internal_id": source.get("source_message_internal_id"),
                    "source_text": source.get("source_text"),
                    "observed_at": (item.get("freshness") or {}).get("observed_at"),
                    "provenance": "owner_attention_projection",
                    "detail": {"operational_reason_code": item.get("reason_code")},
                }
            )
        contract = _recommendation_contract("OWNER_RESPONSE", None, evidence, {"count": len(current_waiting_items)})
        insights.append({"id": "owner-response:waiting", "type": "OWNER_RESPONSE_LEAKAGE", "priority": 100, "title": "عملاء ينتظرون قرارًا من الشركة", **contract})

    insights.sort(key=lambda item: (-item["priority"], item["title"]))
    demand_leads, progressed_leads = _demand_progression_state(events)
    purchase_intent_leads = _distinct_lead_ids(events, {CommercialEventType.PURCHASE_INTENT_EXPRESSED.value})
    purchase_commitment_leads = _distinct_lead_ids(events, {CommercialEventType.PURCHASE_COMMITMENT.value})
    purchase_execution_leads = _distinct_lead_ids(events, {CommercialEventType.PURCHASE_EXECUTION_REQUEST.value})
    objection_leads = _distinct_lead_ids(events, {CommercialEventType.OBJECTION_EXPRESSED.value})
    stalled_leads = _distinct_lead_ids(events, {CommercialEventType.CONVERSATION_STALLED.value})
    knowledge_gap_leads = _distinct_lead_ids(events, {CommercialEventType.KNOWLEDGE_GAP_HIT.value})
    waiting_on_us_leads = {
        int(item["lead_id"])
        for item in current_waiting_items
        if item.get("lead_id") is not None
    }
    current_unavailable_leads: set[int] = set()
    for product_leads in current_unavailable_leads_by_product.values():
        current_unavailable_leads.update(product_leads)

    daily_trend = _build_daily_trend(events, start_date, window_days)
    for row in daily_trend:
        row["waiting_on_us"] = 0
        row["waiting_on_us_scope"] = "windowed_current_owner_attention_projection"
    if daily_trend:
        daily_trend[-1]["waiting_on_us"] = len(waiting_on_us_leads)

    current_attention_queue = _build_current_attention_queue(
        current_projection_items,
        action_leads_by_id,
        projection_opportunity_lead_ids,
    )
    current_attention_lead_ids = {item["lead_id"] for item in current_attention_queue}
    event_opportunity_queue = _build_opportunity_queue(
        events,
        lead_names,
        current_product_states,
        event_opportunity_lead_ids - current_attention_lead_ids,
    )
    opportunity_queue = [*current_attention_queue, *event_opportunity_queue]
    opportunity_queue.sort(
        key=lambda item: (
            -(item.get("priority") or 0),
            0 if item.get("outcome_scope") == "current_owner_attention_projection" else 1,
            item.get("lead_id") or 0,
        )
    )
    opportunity_queue = opportunity_queue[:25]
    most_discussed = products[0] if products else None
    return {
        "window_days": window_days,
        "channel": channel_filter,
        "filters": {
            "days": window_days,
            "channel": channel_filter,
            "tenant_scope": company_id,
        },
        "filters_applied": {
            "days": window_days,
            "channel": channel_filter,
            "tenant_scope": company_id,
        },
        "scope_metadata": {
            "commercial_events": {
                "since": since.isoformat(),
                "days_filter_applied": True,
                "channel_filter_applied": True,
            },
            "current_owner_attention": {
                "since": since.isoformat(),
                "timestamp_source": "projection.freshness.observed_at",
                "days_filter_applied": True,
                "channel_filter_applied": True,
                "bounded_limit": 100,
                "potentially_truncated": len(raw_projection_items) >= 100,
                "excluded_missing_timestamp": projection_items_without_timestamp,
            },
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_source": "deterministic_commercial_events",
        "sample_safety": {"minimum_conversations": MIN_CLASSIFICATION_SAMPLE, "high_interest_threshold": high_interest_threshold},
        "product_attribution_policy": {
            "asked": "سؤال صريح يذكر المنتج",
            "considered": "ذكر صريح أو سياق منتج نشط مع حالة تقييم",
            "recommended": "قرار توصية قانوني في المحرك وظهر المنتج في الرد",
            "price_revealed": "سعر كتالوج موثوق ظهر في رد مرتبط بالمنتج",
            "compared": "طلب مقارنة صريح مرتبط بالمنتج",
            "selected": "لغة اختيار صريحة؛ ليست طلبًا مؤكدًا",
            "purchase_intent": "نية شراء صريحة؛ ليست التزامًا",
            "commitment": "لغة التزام صريحة؛ ليست طلبًا ولا دفعًا",
            "confirmed_order": "حدث موثوق من تكامل طلبات فقط؛ لا يستنتج من الدردشة",
            "paid": "حدث موثوق من تكامل دفع فقط؛ لا يستنتج من الدردشة",
            "current_unavailable_demand": "طلب أو اختيار أو نية شراء صريحة لمنتج غير متاح وفق حالة الكتالوج الحالية؛ الذكر أو الاعتراض وحده لا يكفي",
            "unknown": "غياب الحدث يعني غير معروف، لا صفرًا",
        },
        "summary": {
            "source_conversations": len({row.lead_id for row in events}),
            "commercial_events": len(events),
            "products_with_evidence": len(products),
            "demand_conversations": len(demand_leads),
            "progressed_conversations": len(progressed_leads),
            "demand_without_progress": len(demand_leads - progressed_leads),
            "purchase_intent": len(purchase_intent_leads),
            "purchase_commitment": len(purchase_commitment_leads),
            "purchase_execution": len(purchase_execution_leads),
            "objection": len(objection_leads),
            "stalled": len(stalled_leads),
            "knowledge_gap": len(knowledge_gap_leads),
            "waiting_on_us": len(waiting_on_us_leads),
            "waiting_on_us_scope": "windowed_current_owner_attention_projection",
            "current_unavailable_demand": len(current_unavailable_leads),
            "most_discussed_product": most_discussed["product"] if most_discussed else None,
            "most_discussed_conversations": most_discussed["interest_conversations"] if most_discussed else None,
            "confirmed_orders": None,
            "paid_outcomes": None,
            "paid_conversations": None,
            "outcome_coverage": {
                "orders": "not_connected",
                "payments": "not_connected",
            },
            "outcome_note": "تكامل الطلبات والدفع غير متصل حاليًا؛ لذلك هذه القيم غير معروفة وليست صفرًا.",
        },
        "products": products,
        "daily_trend": daily_trend,
        "opportunity_queue": opportunity_queue,
        "insights": insights[:12],
        "evidence_feed": [_serialize_event(row, lead_names) for row in reversed(events[-40:])],
        "ask_examples": [
            "إيه أكتر منتج الناس بتسأل عليه؟",
            "ليه المنتج ده بيتسأل عليه كتير ومش بيتقدم؟",
            "إيه أكتر اعتراض متكرر؟",
            "إيه المعلومات الناقصة اللي العملاء بيسألوا عنها؟",
            "مين من العملاء الجاهزين مستني ردنا؟",
        ],
    }


def answer_business_question(db: Session, company_id: str, question: str) -> Optional[Dict[str, Any]]:
    text = (question or "").casefold()
    triggers = ("أكتر منتج", "اكتر منتج", "بيتسأل", "مش بيتقدم", "بنخسر", "اعتراض متكرر", "معلومات ناقصة", "مستني ردنا", "hidden winner", "leakage", "most discussed")
    if not any(trigger.casefold() in text for trigger in triggers):
        return None
    data = build_business_commercial_intelligence(db, company_id)
    summary = data["summary"]
    products = data["products"]
    insights = data["insights"]
    selected_insights: List[Dict[str, Any]] = []
    if _contains(text, ("مش بيتقدم", "لا يتقدم", "بنخسر", "leakage", "not progressing")):
        selected_insights = [item for item in insights if item["type"] == "LEAKAGE_CANDIDATE"][:1]
        answer = selected_insights[0]["observed"] if selected_insights else "لا يوجد مرشح تسرب يتجاوز حد العينة حاليًا."
    elif _contains(text, ("أكتر منتج", "اكتر منتج", "most discussed", "بيتسأل عليه")):
        product = summary.get("most_discussed_product")
        count = summary.get("most_discussed_conversations")
        answer = f"أكثر منتج له محادثات اهتمام هو {product} في {count} محادثات." if product else "لا توجد أحداث منتجات كافية للإجابة بعد."
    elif _contains(text, ("اعتراض", "objection")):
        selected_insights = [item for item in insights if item["type"] == "OBJECTION_CONCENTRATION"][:1]
        answer = selected_insights[0]["observed"] if selected_insights else "لا يوجد اعتراض متكرر مدعوم بمحادثتين على الأقل في الفترة الحالية."
    elif _contains(text, ("معلومات ناقصة", "معلومة ناقصة", "knowledge")):
        selected_insights = [item for item in insights if item["type"] == "KNOWLEDGE_GAP"][:3]
        answer = "\n".join(item["observed"] for item in selected_insights) or "لا توجد فجوة معرفة متكررة مدعومة بمحادثتين على الأقل."
    elif _contains(text, ("مستني ردنا", "ينتظر", "waiting")):
        selected_insights = [item for item in insights if item["type"] == "OWNER_RESPONSE_LEAKAGE"][:1]
        answer = selected_insights[0]["observed"] if selected_insights else "لا توجد حالات WAITING_ON_US في الفترة الحالية."
    elif _contains(text, ("قليل", "hidden winner", "فائز خفي")):
        hidden = [item for item in products if item["classification"] == "HIDDEN_WINNER"]
        answer = f"الإشارة الأقوى لفائز خفي محتمل هي {hidden[0]['product']}: اهتمام في {hidden[0]['interest_conversations']} محادثات وتقدم في {hidden[0]['progressed_conversations']}." if hidden else "لا توجد عينة كافية لفائز خفي محتمل حاليًا."
    else:
        selected_insights = [item for item in insights if item["type"] == "LEAKAGE_CANDIDATE"][:1]
        answer = selected_insights[0]["observed"] if selected_insights else "لا يوجد مرشح تسرب يتجاوز حد العينة حاليًا."

    evidence = []
    for insight in selected_insights:
        evidence.extend(insight.get("evidence", []))
    return {
        "answer": answer + " هذه أحداث تقدم محادثة وليست نسبة تحويل أو مبيعات مؤكدة.",
        "evidence": evidence[:8],
        "confidence": None,
        "missing_data": ["confirmed_order_or_payment_events"]
        if summary.get("confirmed_orders") is None or summary.get("paid_outcomes") is None
        else [],
        "suggested_action": selected_insights[0]["recommendation"] if selected_insights else "اجمع محادثات أكثر قبل استنتاج السبب.",
        "suggested_reply": None,
        "source_entities": {"lead_ids": sorted({item["lead_id"] for item in evidence}), "product_names": sorted({item["product"] for item in evidence if item.get("product")})},
        "business_intelligence": {"summary": summary, "insights": selected_insights},
        "intent": "business_commercial_intelligence",
        "scope": "company",
        "llm_used": False,
        "grounding": "deterministic_commercial_events",
    }
