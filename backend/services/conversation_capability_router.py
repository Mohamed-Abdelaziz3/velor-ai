"""Deterministic semantic routing for one customer conversation turn.

The router deliberately has no database or provider dependency.  It operates
on normalized tokens and bounded phrases, records the evidence used for a
decision, and never lets a substring alone trigger a durable action.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Iterable, Optional, Sequence


class ConversationCapability(str, Enum):
    SOCIAL = "SOCIAL"
    ACKNOWLEDGEMENT = "ACKNOWLEDGEMENT"
    CLARIFICATION = "CLARIFICATION"
    UNRESOLVED_DIALOGUE = "UNRESOLVED_DIALOGUE"
    PRODUCT_DISCOVERY = "PRODUCT_DISCOVERY"
    PRODUCT_REFERENCE = "PRODUCT_REFERENCE"
    PRODUCT_SELECTION = "PRODUCT_SELECTION"
    PRODUCT_DETAILS = "PRODUCT_DETAILS"
    PRODUCT_RECOMMENDATION = "PRODUCT_RECOMMENDATION"
    PRODUCT_COMPARISON = "PRODUCT_COMPARISON"
    PRICE_QUESTION = "PRICE_QUESTION"
    PRICE_OBJECTION = "PRICE_OBJECTION"
    BUDGET = "BUDGET"
    POLICY_QUESTION = "POLICY_QUESTION"
    INSTALLMENT_POLICY_QUESTION = "INSTALLMENT_POLICY_QUESTION"
    PAYMENT_PROCESS = "PAYMENT_PROCESS"
    ORDERING_PROCESS = "ORDERING_PROCESS"
    DELIVERY_STATUS = "DELIVERY_STATUS"
    CALLBACK_REQUEST = "CALLBACK_REQUEST"
    CALLBACK_DECLINED = "CALLBACK_DECLINED"
    UNKNOWN_COMMERCIAL_FACT = "UNKNOWN_COMMERCIAL_FACT"
    PURCHASE_ADVANCEMENT = "PURCHASE_ADVANCEMENT"
    OWNER_VERIFICATION_REQUEST = "OWNER_VERIFICATION_REQUEST"
    OWNER_VERIFICATION_ACCEPTANCE = "OWNER_VERIFICATION_ACCEPTANCE"
    HUMAN_HANDOFF_REQUEST = "HUMAN_HANDOFF_REQUEST"
    CANCELLATION = "CANCELLATION"
    OUT_OF_DOMAIN = "OUT_OF_DOMAIN"
    UNCLEAR_OR_NOISE = "UNCLEAR_OR_NOISE"
    DEESCALATION = "DEESCALATION"


class CustomerActionType(str, Enum):
    REQUEST_OWNER_VERIFICATION = "REQUEST_OWNER_VERIFICATION"
    ACCEPT_OWNER_VERIFICATION = "ACCEPT_OWNER_VERIFICATION"
    CANCEL_OWNER_VERIFICATION = "CANCEL_OWNER_VERIFICATION"
    REQUEST_HUMAN_HANDOFF = "REQUEST_HUMAN_HANDOFF"
    START_HUMAN_HANDOFF = "START_HUMAN_HANDOFF"
    PURCHASE_HANDOFF = "PURCHASE_HANDOFF"
    REQUEST_CONTACT = "REQUEST_CONTACT"
    CANCEL_REQUEST = "CANCEL_REQUEST"


@dataclass(frozen=True)
class CapabilityDecision:
    """Private routing contract consumed by response and persistence layers."""

    capability: ConversationCapability
    legacy_plan_type: str
    policy_kind: Optional[str] = None
    offered_action: Optional[str] = None
    execute_action: Optional[str] = None
    secondary_capability: Optional[ConversationCapability] = None
    confidence: float = 0.0
    positive_evidence: tuple[str, ...] = ()
    negative_evidence: tuple[str, ...] = ()
    negation_detected: bool = False
    context_dependencies: tuple[str, ...] = ()
    action_eligible: bool = False
    clarification_required: bool = False
    reason_code: str = ""
    # Compatibility for V2 trace code.  It is intentionally never rendered to
    # the public client with the evidence fields above.
    reason: str = ""


@dataclass(frozen=True)
class _Candidate:
    decision: CapabilityDecision
    priority: int


_ARABIC_DIACRITICS = re.compile(r"[\u064b-\u065f\u0670]")
_TOKEN_RE = re.compile(r"[a-z0-9]+|[\u0621-\u063a\u0641-\u064a]+", re.IGNORECASE)
_NEGATORS = {"مش", "موش", "ما", "لا", "بدون", "بلاش", "مشعايز", "مشعاوزه", "not", "no", "never", "dont", "don't"}
_FILLERS = {"لو", "سمحت", "دلوقتي", "بس", "بجد", "حالا", "please", "now"}


def normalize_customer_text(value: str) -> str:
    """Normalize Arabic variants without losing token boundaries or polarity."""
    text = unicodedata.normalize("NFKC", value or "").casefold().strip()
    text = _ARABIC_DIACRITICS.sub("", text)
    text = text.translate(str.maketrans({
        "أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي", "ة": "ه", "ؤ": "و", "ئ": "ي",
        "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4",
        "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
    }))
    return re.sub(r"\s+", " ", text)


def _tokens(value: str) -> list[str]:
    return _TOKEN_RE.findall(normalize_customer_text(value))


def _has_token(tokens: Sequence[str], terms: Iterable[str]) -> bool:
    wanted = {normalize_customer_text(term) for term in terms}
    return any(any(_token_matches(token, term) for term in wanted) for token in tokens)


def _token_matches(actual: str, wanted: str) -> bool:
    """Match an exact token, allowing only the Arabic conjunction clitic.

    ``واطلب`` is one orthographic token but means ``و اطلب``.  Supporting
    this bounded prefix is not substring routing: the remainder must still
    equal the complete intent token.
    """
    return actual == wanted or (len(wanted) >= 3 and actual == f"و{wanted}")


def _phrase_positions(tokens: Sequence[str], phrase: str) -> list[int]:
    wanted = _tokens(phrase)
    if not wanted or len(wanted) > len(tokens):
        return []
    return [
        index for index in range(len(tokens) - len(wanted) + 1)
        if all(_token_matches(actual, expected) for actual, expected in zip(tokens[index:index + len(wanted)], wanted))
    ]


def _has_phrase(tokens: Sequence[str], phrases: Iterable[str]) -> bool:
    return any(_phrase_positions(tokens, phrase) for phrase in phrases)


def _is_negated(tokens: Sequence[str], start: int, length: int = 1) -> bool:
    """Bound negation to the three tokens directly before an intent phrase.

    Arabic ``ما تتصلش`` is one grammatical negation even though it includes
    both a particle and a suffix.  Other double negatives cancel by parity.
    """
    before = list(tokens[max(0, start - 3):start])
    target = list(tokens[start:start + length])
    marker_count = sum(token in _NEGATORS for token in before)
    suffix_negation = any(token.endswith("ش") and len(token) > 3 for token in target)
    if before and before[-1] == "ما" and suffix_negation:
        return True
    if suffix_negation:
        marker_count += 1
    return bool(marker_count % 2)


def _matched_phrase(tokens: Sequence[str], phrases: Iterable[str], *, require_positive: bool = False) -> tuple[Optional[str], bool]:
    """Return a bounded phrase and whether it is in a negated scope."""
    for phrase in phrases:
        phrase_tokens = _tokens(phrase)
        for position in _phrase_positions(tokens, phrase):
            negated = _is_negated(tokens, position, len(phrase_tokens))
            if not require_positive or not negated:
                return phrase, negated
    return None, False


def _pending_action(pending_question: Optional[str], *, company_id: str = "", visitor_id: str = "") -> Dict[str, Any]:
    if not pending_question:
        return {}
    try:
        payload = json.loads(pending_question)
    except (TypeError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    scope = payload.get("conversation_scope") or {}
    if scope and (
        scope.get("company_id") != company_id
        or scope.get("visitor_id") != visitor_id
        or scope.get("channel") != "VELOR_WEB_CHAT"
    ):
        return {}
    action = payload.get("offered_action") or payload.get("conversation_state", {}).get("offered_action")
    return action if isinstance(action, dict) and action.get("status", "offered") == "offered" else {}


def _decision(
    capability: ConversationCapability,
    plan: str,
    *,
    confidence: float,
    evidence: Iterable[str] = (),
    negative: Iterable[str] = (),
    negated: bool = False,
    policy_kind: Optional[str] = None,
    offered_action: Optional[str] = None,
    execute_action: Optional[str] = None,
    secondary: Optional[ConversationCapability] = None,
    dependencies: Iterable[str] = (),
    clarification: bool = False,
    reason: str,
) -> CapabilityDecision:
    return CapabilityDecision(
        capability=capability,
        legacy_plan_type=plan,
        policy_kind=policy_kind,
        offered_action=offered_action,
        execute_action=execute_action,
        secondary_capability=secondary,
        confidence=confidence,
        positive_evidence=tuple(evidence),
        negative_evidence=tuple(negative),
        negation_detected=negated,
        context_dependencies=tuple(dependencies),
        # Every durable action requires deterministic, high confidence,
        # positive evidence.  Offers intentionally are not executions.
        action_eligible=bool(execute_action and confidence >= 0.90 and not negated),
        clarification_required=clarification,
        reason_code=reason,
        reason=reason,
    )


def _choose(candidates: list[_Candidate]) -> Optional[CapabilityDecision]:
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item.decision.confidence, item.priority), reverse=True)
    return candidates[0].decision


def _short_confirmation(tokens: Sequence[str]) -> bool:
    return len(tokens) <= 3 and _has_token(tokens, {"اه", "ايوه", "نعم", "تمام", "ماشي", "اوكي", "اكيد", "طبعا", "ok", "okay", "yes"})


def _short_acknowledgement(tokens: Sequence[str]) -> bool:
    return len(tokens) <= 3 and _has_token(tokens, {"تمام", "ماشي", "شكرا", "تسلم", "متشكر", "حلو", "جميل", "اوكي", "وصل", "مفهوم", "ok"})


def _looks_like_catalog_discovery(raw: str) -> bool:
    """Recognize a shopper asking for available types/models, not one SKU."""
    text = str(raw or "").casefold()
    patterns = (
        "\u0627\u0644\u0623\u0646\u0648\u0627\u0639",  # الأنواع
        "\u0627\u0644\u0627\u062e\u062a\u064a\u0627\u0631\u0627\u062a",  # الاختيارات
        "\u0627\u0644\u0645\u0648\u062f\u064a\u0644\u0627\u062a",  # الموديلات
        "\u0627\u0644\u0645\u062a\u0627\u062d",  # المتاح
        "what do you have", "available models", "which models",
    )
    return any(pattern in text for pattern in patterns)


def route_customer_capability(ctx: Any) -> CapabilityDecision:
    """Classify one turn with deterministic semantic evidence and precedence."""
    raw = str(getattr(ctx, "latest_customer_message", "") or "")
    normalized = normalize_customer_text(raw)
    tokens = _tokens(raw)
    pending = _pending_action(
        getattr(ctx, "pending_question_payload", None),
        company_id=str(getattr(ctx, "company_id", "")),
        visitor_id=str(getattr(ctx, "visitor_id", "")),
    )
    active_action = str(pending.get("type") or "")
    product_resolution = getattr(ctx, "product_resolution", {}) or {}
    resolved = list(getattr(ctx, "resolved_products", []) or product_resolution.get("resolved_products", []) or [])
    # The product resolver deliberately avoids speculative matching on an
    # elliptical answer.  Keep only the already-resolved conversation context
    # so "استخدامي 8 ساعات" can answer the immediately preceding follow-up.
    contextual_products = list(getattr(ctx, "current_product_references", []) or [])
    resolution_status = str(getattr(ctx, "resolution_status", "") or product_resolution.get("status", "") or "")

    if not tokens or (len(raw.strip()) <= 1 and not tokens):
        return _decision(ConversationCapability.UNCLEAR_OR_NOISE, "CLARIFY", confidence=1.0, clarification=True, reason="empty_or_punctuation")
    if len(tokens) <= 3 and set(tokens).issubset(_FILLERS):
        return _decision(ConversationCapability.UNCLEAR_OR_NOISE, "CLARIFY", confidence=0.98, clarification=True, reason="filler_only")

    candidates: list[_Candidate] = []

    usage_duration = bool(re.search(r"\b\d{1,2}\s*(?:ساعة|ساعات|hour|hours)\b", normalized, re.IGNORECASE))
    if usage_duration and (resolved or contextual_products):
        candidates.append(_Candidate(_decision(
            ConversationCapability.PRODUCT_RECOMMENDATION, "PRODUCT_RECOMMENDATION", confidence=0.94,
            evidence=("usage_duration",), dependencies=("active_product_context",),
            reason="usage_duration_follow_up",
        ), 84))

    # Pending actions are tenant/visitor/channel scoped.  They only execute
    # after a high-confidence positive confirmation or cancellation.
    cancel_phrase, cancel_negated = _matched_phrase(tokens, ("الغى", "الغي", "كنسل", "تراجع", "بلاش", "cancel"), require_positive=True)
    if active_action and cancel_phrase:
        action = CustomerActionType.CANCEL_OWNER_VERIFICATION.value if active_action == CustomerActionType.REQUEST_OWNER_VERIFICATION.value else CustomerActionType.CANCEL_REQUEST.value
        candidates.append(_Candidate(_decision(
            ConversationCapability.CANCELLATION, "CANCELLATION", confidence=0.99,
            evidence=(cancel_phrase,), execute_action=action,
            dependencies=("scoped_pending_action",), reason="active_action_cancelled",
        ), 100))

    callback_decline, callback_declined = _matched_phrase(tokens, (
        "ما تتصلش بيا", "متتصلش بيا", "مش عايز مكالمة", "مش عايزه مكالمة", "مش عايز اتصال", "مش عايزه اتصال", "من غير مكالمة", "بدون مكالمة", "مش عايز تكلموني", "لا تتصل بي", "dont call me", "do not call me",
    ))
    if callback_decline:
        candidates.append(_Candidate(_decision(
            ConversationCapability.CALLBACK_DECLINED, "CALLBACK_DECLINED", confidence=0.99,
            evidence=(callback_decline,), negative=("callback_prohibited",), negated=True,
            reason="explicit_negative_contact_intent",
        ), 98))

    handoff_phrase, handoff_negated = _matched_phrase(tokens, (
        "وصلني بخدمة العملاء", "خدمة العملاء", "اكلم حد", "اكلم انسان", "موظف", "بشري", "حد من الفريق", "speak to a person", "human agent",
    ))
    if handoff_phrase:
        if handoff_negated:
            candidates.append(_Candidate(_decision(
                ConversationCapability.CLARIFICATION, "CLARIFY", confidence=0.82,
                negative=(f"negated:{handoff_phrase}",), negated=True, clarification=True,
                reason="negated_human_handoff",
            ), 96))
        else:
            candidates.append(_Candidate(_decision(
                ConversationCapability.HUMAN_HANDOFF_REQUEST, "HUMAN_HANDOFF", confidence=0.98,
                evidence=(handoff_phrase,), execute_action=CustomerActionType.START_HUMAN_HANDOFF.value,
                reason="explicit_human_handoff",
            ), 95))

    verify_phrase, verify_negated = _matched_phrase(tokens, (
        "اسال الفريق", "اسأل الفريق", "اتأكد من الفريق", "اتاكد من الفريق", "خليهم يراجعوا", "صاحب المكان",
    ))
    if verify_phrase:
        if verify_negated:
            candidates.append(_Candidate(_decision(
                ConversationCapability.CLARIFICATION, "CLARIFY", confidence=0.80, negated=True,
                negative=(f"negated:{verify_phrase}",), clarification=True, reason="negated_verification_request",
            ), 94))
        elif active_action == CustomerActionType.REQUEST_OWNER_VERIFICATION.value:
            candidates.append(_Candidate(_decision(
                ConversationCapability.OWNER_VERIFICATION_ACCEPTANCE, "OWNER_VERIFICATION_ACCEPTANCE", confidence=0.99,
                evidence=(verify_phrase,), execute_action=CustomerActionType.ACCEPT_OWNER_VERIFICATION.value,
                dependencies=("scoped_pending_action",), reason="accepted_offered_verification",
            ), 94))
        else:
            candidates.append(_Candidate(_decision(
                ConversationCapability.OWNER_VERIFICATION_REQUEST, "OWNER_VERIFICATION_OFFER", confidence=0.97,
                evidence=(verify_phrase,), offered_action=CustomerActionType.REQUEST_OWNER_VERIFICATION.value,
                reason="explicit_owner_verification",
            ), 93))
    elif active_action == CustomerActionType.REQUEST_OWNER_VERIFICATION.value and _short_confirmation(tokens):
        candidates.append(_Candidate(_decision(
            ConversationCapability.OWNER_VERIFICATION_ACCEPTANCE, "OWNER_VERIFICATION_ACCEPTANCE", confidence=0.95,
            evidence=("scoped_short_confirmation",), execute_action=CustomerActionType.ACCEPT_OWNER_VERIFICATION.value,
            dependencies=("scoped_pending_action",), reason="accepted_offered_verification",
        ), 92))

    delivery_phrase, delivery_negated = _matched_phrase(tokens, (
        "وصلني الطلب", "الطلب وصل", "فين طلبي", "فين الطلب", "حالة الطلب", "order status", "track my order",
    ))
    if delivery_phrase and not delivery_negated:
        candidates.append(_Candidate(_decision(
            ConversationCapability.DELIVERY_STATUS, "POLICY_ANSWER", confidence=0.97,
            evidence=(delivery_phrase,), policy_kind="delivery_status", reason="delivery_status_request",
        ), 91))

    payment_phrase, payment_negated = _matched_phrase(tokens, ("ادفع ازاي", "طريقة الدفع", "طرق الدفع", "payment process", "how to pay", "pay"))
    ordering_phrase, ordering_negated = _matched_phrase(tokens, ("اطلب ازاي", "طريقة الطلب", "ازاي اطلب", "how to order", "ordering process"))
    has_payment_token = _has_token(tokens, {"ادفع", "الدفع", "دفع", "payment", "pay"})
    has_order_token = _has_token(tokens, {"اطلب", "الطلب", "طلب", "order", "ordering"})
    if (payment_phrase or has_payment_token) and (ordering_phrase or has_order_token) and not (payment_negated or ordering_negated):
        candidates.append(_Candidate(_decision(
            ConversationCapability.PAYMENT_PROCESS, "POLICY_ANSWER", confidence=0.98,
            evidence=(payment_phrase or "payment_token", ordering_phrase or "ordering_token"),
            policy_kind="payment_and_order", secondary=ConversationCapability.ORDERING_PROCESS,
            reason="combined_payment_and_order_process",
        ), 90))
    elif payment_phrase and not payment_negated:
        candidates.append(_Candidate(_decision(
            ConversationCapability.PAYMENT_PROCESS, "POLICY_ANSWER", confidence=0.96,
            evidence=(payment_phrase,), policy_kind="payment", reason="payment_process_request",
        ), 89))
    elif ordering_phrase and not ordering_negated:
        candidates.append(_Candidate(_decision(
            ConversationCapability.ORDERING_PROCESS, "POLICY_ANSWER", confidence=0.96,
            evidence=(ordering_phrase,), policy_kind="ordering", reason="ordering_process_request",
        ), 89))

    installment_phrase, installment_negated = _matched_phrase(tokens, ("تقسيط", "اقساط", "قسط", "installment", "installments"))
    if installment_phrase and not installment_negated:
        candidates.append(_Candidate(_decision(
            # Preserve the stable primary capability while expressing the
            # precise policy subtype through the secondary capability.
            ConversationCapability.POLICY_QUESTION, "POLICY_ANSWER", confidence=0.96,
            evidence=(installment_phrase,), policy_kind="installments", secondary=ConversationCapability.INSTALLMENT_POLICY_QUESTION,
            offered_action=CustomerActionType.REQUEST_OWNER_VERIFICATION.value, reason="installment_policy_question",
        ), 87))

    generic_policy_phrase, generic_policy_negated = _matched_phrase(tokens, (
        "خصم", "discount", "استرجاع", "استبدال", "ضمان", "توصيل", "شحن", "متوفر", "availability", "فرع",
    ))
    if generic_policy_phrase and not generic_policy_negated:
        policy_kind = {
            "خصم": "discount", "discount": "discount", "استرجاع": "returns", "استبدال": "returns",
            "ضمان": "warranty", "توصيل": "delivery", "شحن": "delivery", "متوفر": "availability",
            "availability": "availability", "فرع": "branch",
        }.get(normalize_customer_text(generic_policy_phrase), "policy")
        candidates.append(_Candidate(_decision(
            ConversationCapability.POLICY_QUESTION, "POLICY_ANSWER", confidence=0.90,
            evidence=(generic_policy_phrase,), policy_kind=policy_kind,
            offered_action=CustomerActionType.REQUEST_OWNER_VERIFICATION.value, reason="policy_question",
        ), 86))

    callback_phrase, callback_negated = _matched_phrase(tokens, ("اتصل بيا", "تتصل بيا", "كلمني", "مكالمة", "عايز اتصال", "عايز مكالمة", "call me", "callback"))
    if callback_phrase and not callback_negated:
        candidates.append(_Candidate(_decision(
            ConversationCapability.CALLBACK_REQUEST, "CALLBACK_REQUEST", confidence=0.95,
            evidence=(callback_phrase,), offered_action=CustomerActionType.REQUEST_CONTACT.value, reason="callback_requested",
        ), 86))

    purchase_phrase, purchase_negated = _matched_phrase(tokens, (
        "عايز اشتري", "عايز اشتريه", "عايز احجز", "احجزلي", "هاخده", "هاخد", "هشتري", "اشتري", "اشتريه", "buy", "purchase",
    ))
    if purchase_phrase and not purchase_negated and not (ordering_phrase or payment_phrase):
        candidates.append(_Candidate(_decision(
            ConversationCapability.PURCHASE_ADVANCEMENT, "PURCHASE_HANDOFF", confidence=0.96,
            evidence=(purchase_phrase,), execute_action=CustomerActionType.PURCHASE_HANDOFF.value,
            reason="explicit_purchase_advancement",
        ), 85))

    frustration_phrase, frustration_negated = _matched_phrase(tokens, (
        "غبي", "زفت", "مستفز", "مش فاهم حاجه", "مش فاهم حاجة", "سيئ", "وحش",
        "كسم", "كسمين", "كس ام", "ابن كلب", "يلعن",
    ))
    if frustration_phrase and not frustration_negated:
        candidates.append(_Candidate(_decision(
            ConversationCapability.DEESCALATION, "DEESCALATION", confidence=0.93,
            evidence=(frustration_phrase,), reason="frustration_or_anger",
        ), 80))

    greeting_phrase, greeting_negated = _matched_phrase(tokens, ("السلام عليكم", "صباح الخير", "مساء الخير", "اهلا", "مرحبا", "هاي", "الو", "hello", "hi"))
    if greeting_phrase and not greeting_negated and len(tokens) <= 4:
        candidates.append(_Candidate(_decision(
            ConversationCapability.SOCIAL, "GREETING", confidence=0.97, evidence=(greeting_phrase,), reason="bounded_greeting",
        ), 70))
    if len(tokens) <= 3 and _has_phrase(tokens, ("مع السلامه", "باي", "bye", "goodbye")):
        candidates.append(_Candidate(_decision(
            ConversationCapability.SOCIAL, "SOCIAL", confidence=0.97, evidence=("goodbye",), reason="bounded_goodbye",
        ), 70))
    if len(tokens) <= 3 and _has_phrase(tokens, ("كمل", "كمللي", "تابع", "وبعدين", "continue")):
        candidates.append(_Candidate(_decision(
            ConversationCapability.UNRESOLVED_DIALOGUE, "CLARIFY", confidence=0.91, clarification=True, reason="continuation_without_facts",
        ), 65))
    if _short_acknowledgement(tokens):
        candidates.append(_Candidate(_decision(
            ConversationCapability.ACKNOWLEDGEMENT, "ACKNOWLEDGEMENT", confidence=0.90, reason="short_acknowledgement",
        ), 64))

    comparison_phrase, comparison_negated = _matched_phrase(tokens, ("قارن", "مقارنه", "مقارنة", "الفرق", "compare", "vs"))
    if comparison_phrase and not comparison_negated:
        candidates.append(_Candidate(_decision(
            ConversationCapability.PRODUCT_COMPARISON, "PRODUCT_COMPARISON", confidence=0.93,
            evidence=(comparison_phrase,), reason="comparison_request",
        ), 60))

    price_phrase, price_negated = _matched_phrase(tokens, ("بكام", "السعر", "سعر", "price", "cost"))
    if price_phrase and not price_negated:
        candidates.append(_Candidate(_decision(
            ConversationCapability.PRICE_QUESTION, "PRODUCT_PRICE", confidence=0.93,
            evidence=(price_phrase,), reason="price_question",
        ), 59))

    objection_phrase, objection_negated = _matched_phrase(tokens, ("غالي", "سعر عالي", "كتير اوي", "كتير قوي", "expensive", "too much", "مرتفع"))
    if objection_phrase:
        if objection_negated:
            candidates.append(_Candidate(_decision(
                ConversationCapability.CLARIFICATION, "CLARIFY", confidence=0.81, negated=True,
                negative=(f"negated:{objection_phrase}",), clarification=True, reason="negated_price_objection",
            ), 58))
        else:
            candidates.append(_Candidate(_decision(
            ConversationCapability.PRICE_OBJECTION, "PRICE_OBJECTION", confidence=0.95,
                evidence=(objection_phrase,), reason="price_objection",
            ), 58))

    currency_budget = bool(re.search(r"\b\d{3,8}\s*(?:جنيه|جنية|egp|le)\b", normalized, re.IGNORECASE))
    budget_phrase, budget_negated = _matched_phrase(tokens, ("ميزانيتي", "الميزانيه", "سقف ميزانيتي", "حدي", "حد اقصى", "budget", "under"))
    if currency_budget or (budget_phrase and re.search(r"\d{2,8}", normalized)):
        candidates.append(_Candidate(_decision(
            ConversationCapability.BUDGET, "BUDGET_CONSTRAINT", confidence=0.95,
            evidence=(("currency_amount",) if currency_budget else (budget_phrase,)), reason="explicit_monetary_constraint",
        ), 57))

    details_phrase, details_negated = _matched_phrase(tokens, ("مواصفات", "مواصفاته", "تفاصيل", "features", "details", "شكل", "مقاس", "الوان", "الوان الكرسي", "colors", "color"))
    if details_phrase and not details_negated:
        candidates.append(_Candidate(_decision(
            ConversationCapability.PRODUCT_DETAILS, "PRODUCT_SPECS", confidence=0.88,
            evidence=(details_phrase,), reason="product_details_request",
        ), 55))

    issue_phrase, issue_negated = _matched_phrase(tokens, ("مشكله في", "مشكلة في", "عندي مشكله", "عندي مشكلة", "معايا مشكله", "معايا مشكلة"))
    if issue_phrase and not issue_negated:
        candidates.append(_Candidate(_decision(
            ConversationCapability.CLARIFICATION, "CLARIFY", confidence=0.89,
            evidence=(issue_phrase,), clarification=True, reason="product_problem_needs_clarification",
        ), 56))

    unknown_phrase, unknown_negated = _matched_phrase(tokens, ("يتحمل", "بيتحمل", "وزن", "يحمي", "يعالج", "مضمون", "guarantee", "guaranteed", "health", "medical"))
    if unknown_phrase and not unknown_negated:
        candidates.append(_Candidate(_decision(
            ConversationCapability.UNKNOWN_COMMERCIAL_FACT, "UNKNOWN_INFORMATION", confidence=0.96 if unknown_phrase in {"مضمون", "guarantee", "guaranteed"} else 0.88,
            evidence=(unknown_phrase,), offered_action=CustomerActionType.REQUEST_OWNER_VERIFICATION.value,
            reason="explicit_unverified_commercial_claim",
        ), 54))

    catalog_discovery = _looks_like_catalog_discovery(raw)
    if resolution_status == "category_match":
        candidates.append(_Candidate(_decision(
            ConversationCapability.PRODUCT_DISCOVERY, "CATEGORY_DISCOVERY", confidence=0.94 if catalog_discovery else 0.88,
            dependencies=("product_resolution",), reason="category_resolution",
        ), 50))
    if catalog_discovery:
        candidates.append(_Candidate(_decision(
            ConversationCapability.PRODUCT_DISCOVERY, "CATEGORY_DISCOVERY", confidence=0.95,
            evidence=("catalog_type_discovery",), reason="catalog_type_discovery",
        ), 52))
    recommendation_phrase, recommendation_negated = _matched_phrase(tokens, ("للشغل", "مريح", "راحه", "راحة", "comfort", "long hours", "work"))
    if recommendation_phrase and not recommendation_negated:
        candidates.append(_Candidate(_decision(
            ConversationCapability.PRODUCT_RECOMMENDATION, "PRODUCT_RECOMMENDATION", confidence=0.84,
            evidence=(recommendation_phrase,), reason="usage_based_recommendation",
        ), 49))
    if resolved and not catalog_discovery:
        candidates.append(_Candidate(_decision(
            ConversationCapability.PRODUCT_REFERENCE, "PRODUCT_SELECTION", confidence=0.82,
            dependencies=("resolved_product",), reason="resolved_product_reference",
        ), 48))
    discovery_phrase, discovery_negated = _matched_phrase(tokens, ("كرسي", "مكتب", "chair", "desk", "منتج", "product", "موديل", "model"))
    if discovery_phrase and not discovery_negated:
        candidates.append(_Candidate(_decision(
            ConversationCapability.PRODUCT_DISCOVERY, "CATEGORY_DISCOVERY", confidence=0.83,
            evidence=(discovery_phrase,), reason="product_discovery_language",
        ), 47))

    chosen = _choose(candidates)
    if chosen:
        return chosen

    # Clearly unrelated questions receive a boundary; uncertain commerce-like
    # input receives a natural clarifier instead of an invented action.
    if _has_token(tokens, {"ماتش", "الماتش", "كوره", "كرة", "طقس", "weather", "politics", "سياسه", "سياسة"}):
        return _decision(ConversationCapability.OUT_OF_DOMAIN, "OUT_OF_DOMAIN", confidence=0.94, reason="known_out_of_domain_topic")
    commercial_hint = _has_token(tokens, {"منتج", "كرسي", "مكتب", "سعر", "طلب", "store", "product", "price", "order", "chair", "desk"})
    if commercial_hint or "?" in raw or "؟" in raw:
        return _decision(
            ConversationCapability.CLARIFICATION, "CLARIFY", confidence=0.45, clarification=True,
            reason="ambiguous_below_confidence_threshold",
        )
    return _decision(ConversationCapability.OUT_OF_DOMAIN, "OUT_OF_DOMAIN", confidence=0.70, reason="non_commercial_unresolved")
