"""Bounded semantic obligations for customer-visible answer fulfillment.

The router decides *what kind of turn this is*.  This module records the
specific thing the customer still needs answered, clarified, or actioned so a
generic catalog response cannot silently satisfy an unrelated request.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
import unicodedata
from typing import Any, Iterable, Optional


class ObligationType:
    ATTRIBUTE_QUESTION = "ATTRIBUTE_QUESTION"
    RECENCY_QUESTION = "RECENCY_QUESTION"
    PRODUCT_SUPPORT_ISSUE = "PRODUCT_SUPPORT_ISSUE"
    ORDER_SUPPORT_ISSUE = "ORDER_SUPPORT_ISSUE"
    ORDER_STATUS = "ORDER_STATUS"
    CONTEXTUAL_POLARITY_UPDATE = "CONTEXTUAL_POLARITY_UPDATE"
    NEGATIVE_CONTACT = "NEGATIVE_CONTACT"
    PURCHASE_DEFERRAL = "PURCHASE_DEFERRAL"
    REFERENCE_CORRECTION = "REFERENCE_CORRECTION"
    POLICY_QUESTION = "POLICY_QUESTION"
    ACTION_REQUEST = "ACTION_REQUEST"
    GENERIC = "GENERIC"


class AcceptableOutcome:
    DIRECT_ANSWER = "DIRECT_ANSWER"
    EXPLICIT_UNKNOWN = "EXPLICIT_UNKNOWN"
    CLARIFICATION = "CLARIFICATION"
    ACTION_EXECUTION = "ACTION_EXECUTION"
    DOMAIN_REDIRECT = "DOMAIN_REDIRECT"


_ARABIC_TRANSLATION = str.maketrans({
    "أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي", "ة": "ه", "ؤ": "و", "ئ": "ي",
})


def normalize_obligation_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold().translate(_ARABIC_TRANSLATION)
    return "".join(char for char in text if not unicodedata.combining(char))


def obligation_tokens(value: str) -> tuple[str, ...]:
    # Keep Arabic letters/digits but exclude Arabic punctuation such as ``؟``
    # (which lives in the broad U+0600–U+06FF block).
    return tuple(re.findall(r"[a-z0-9\u0621-\u063a\u0641-\u064a]+", normalize_obligation_text(value), flags=re.UNICODE))


def _contains_phrase(tokens: Iterable[str], phrase: Iterable[str]) -> bool:
    haystack = tuple(tokens)
    needle = tuple(phrase)
    return bool(needle) and any(haystack[index:index + len(needle)] == needle for index in range(len(haystack) - len(needle) + 1))


def _has_any(tokens: Iterable[str], options: Iterable[str]) -> bool:
    available = set(tokens)
    return bool(available.intersection(options))


_ATTRIBUTE_ALIASES: dict[str, set[str]] = {
    "COLOR": {"لون", "الوان", "الوانه", "color", "colors", "colour", "colours"},
    "DIMENSIONS": {"مقاس", "المقاس", "مقاسات", "المقاسات", "ابعاد", "الابعاد", "طول", "عرض", "ارتفاع", "dimension", "dimensions", "size", "sizes"},
    "MATERIAL": {"خامه", "خامة", "الخامه", "الخامة", "ماده", "مادة", "material", "mesh", "leather"},
    "WEIGHT_CAPACITY": {"يتحمل", "تحمل", "وزن", "الوزن", "كيلو", "capacity", "weight"},
    "ARMRESTS": {"مسند", "مسندات", "ذراع", "ذراعين", "armrest", "armrests"},
    "LUMBAR_SUPPORT": {"قطني", "الظهر", "lumbar"},
    "HEADREST": {"راس", "رأس", "headrest"},
    "ADJUSTABILITY": {"يتحرك", "بتتحرك", "قابل", "تعديل", "adjustable", "adjustability"},
    "PRICE": {"سعر", "بكام", "price", "cost"},
    "AVAILABILITY": {"متوفر", "متاح", "مخزون", "availability", "available", "stock"},
    "WARRANTY": {"ضمان", "warranty"},
    "MODEL_VERSION": {"موديل", "اصدار", "إصدار", "version", "model"},
    "USAGE_SUITABILITY": {"يناسب", "مناسب", "استخدام", "شغل", "مذاكره", "مذاكرة", "comfortable", "suitable"},
}

_ATTRIBUTE_PRODUCT_KEYS: dict[str, tuple[str, ...]] = {
    "COLOR": ("colors", "color", "colours", "colour"),
    "DIMENSIONS": ("dimensions", "dimension", "size", "sizes", "width", "height", "length"),
    "MATERIAL": ("material", "materials", "fabric", "upholstery"),
    "WEIGHT_CAPACITY": ("weight_capacity", "capacity", "max_weight", "max_load"),
    "ARMRESTS": ("armrests", "armrest"),
    "LUMBAR_SUPPORT": ("lumbar_support", "lumbar"),
    "HEADREST": ("headrest",),
    "ADJUSTABILITY": ("adjustability", "adjustable", "adjustments"),
    "PRICE": ("price",),
    "AVAILABILITY": ("stock", "availability"),
    "WARRANTY": ("warranty",),
    "MODEL_VERSION": ("model", "version"),
    "RELEASE_RECENCY": ("release_date", "release_order", "released_at", "launch_date"),
    "USAGE_SUITABILITY": ("usage_suitability", "suitable_for"),
}

_ATTRIBUTE_LABELS = {
    "COLOR": "ألوان",
    "DIMENSIONS": "مقاسات",
    "MATERIAL": "الخامة",
    "WEIGHT_CAPACITY": "قدرة التحمل",
    "ARMRESTS": "مساند الذراع",
    "LUMBAR_SUPPORT": "الدعم القطني",
    "HEADREST": "مسند الرأس",
    "ADJUSTABILITY": "إمكانية التعديل",
    "PRICE": "السعر",
    "AVAILABILITY": "التوفر",
    "WARRANTY": "الضمان",
    "MODEL_VERSION": "الموديل",
    "RELEASE_RECENCY": "ترتيب أحدث موديل",
    "USAGE_SUITABILITY": "ملاءمة الاستخدام",
}


@dataclass(frozen=True)
class AnswerObligation:
    obligation_type: str
    requested_subject: Optional[str] = None
    requested_attribute: Optional[str] = None
    requested_policy: Optional[str] = None
    requested_action: Optional[str] = None
    target_product: Optional[str] = None
    target_category: Optional[str] = None
    reference_source_message_ids: tuple[str, ...] = ()
    required_facts: tuple[str, ...] = ()
    forbidden_substitutions: tuple[str, ...] = ()
    acceptable_outcomes: tuple[str, ...] = (AcceptableOutcome.DIRECT_ANSWER,)
    completion_criteria: tuple[str, ...] = ()
    confidence: float = 0.0
    ambiguity_reason: Optional[str] = None
    issue_type: Optional[str] = None

    @property
    def requires_specific_fulfillment(self) -> bool:
        return self.obligation_type != ObligationType.GENERIC

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def attribute_label(attribute: Optional[str]) -> str:
    return _ATTRIBUTE_LABELS.get(str(attribute or ""), "المعلومة المطلوبة")


def product_attribute_keys(attribute: Optional[str]) -> tuple[str, ...]:
    return _ATTRIBUTE_PRODUCT_KEYS.get(str(attribute or ""), ())


def _resolved_products(ctx: Any) -> list[dict[str, Any]]:
    resolution = getattr(ctx, "product_resolution", {}) or {}
    products = [item for item in resolution.get("resolved_products", []) if isinstance(item, dict)]
    if products:
        return products[:3]
    references = {normalize_obligation_text(name) for name in getattr(ctx, "current_product_references", []) or []}
    return [
        item for item in (getattr(ctx, "trusted_catalog_products", []) or [])
        if normalize_obligation_text(item.get("name", "")) in references
    ][:3]


def _target(ctx: Any) -> tuple[Optional[str], Optional[str], Optional[str]]:
    products = _resolved_products(ctx)
    if len(products) == 1:
        product = products[0]
        return str(product.get("name") or "") or None, str(product.get("category") or "") or None, None
    # The catalog resolver deliberately avoids speculative fuzzy matching, but
    # a unique bounded product-name token (for example "LiftDesk") is an
    # explicit reference and is safe to carry into an answer obligation.
    customer_tokens = set(obligation_tokens(getattr(ctx, "latest_customer_message", "")))
    customer_normalized = normalize_obligation_text(getattr(ctx, "latest_customer_message", ""))
    token_matches = []
    for product in getattr(ctx, "trusted_catalog_products", []) or []:
        name_tokens = {
            token for token in obligation_tokens(product.get("name", ""))
            if len(token) >= 4 and token not in {"model", "موديل"}
        }
        ascii_name_tokens = set(re.findall(r"[a-z0-9]{4,}", normalize_obligation_text(product.get("name", ""))))
        ascii_match = any(
            re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", customer_normalized)
            for token in ascii_name_tokens
        )
        if (name_tokens and customer_tokens.intersection(name_tokens)) or ascii_match:
            token_matches.append(product)
    if len(token_matches) == 1:
        product = token_matches[0]
        return str(product.get("name") or "") or None, str(product.get("category") or "") or None, None
    if len(products) > 1:
        categories = {str(product.get("category") or "") for product in products if product.get("category")}
        return None, next(iter(categories), None) if len(categories) == 1 else None, "multiple_products_in_scope"
    return None, None, "no_unique_product_reference"


def _attribute_from_tokens(tokens: tuple[str, ...]) -> Optional[str]:
    for attribute, aliases in _ATTRIBUTE_ALIASES.items():
        if _has_any(tokens, aliases):
            return attribute
    return None


def _history_text(ctx: Any) -> tuple[str, ...]:
    return tuple(
        normalize_obligation_text(item.get("content", ""))
        for item in (getattr(ctx, "recent_messages", []) or [])[-4:]
        if isinstance(item, dict)
    )


def derive_answer_obligation(ctx: Any, route: Any) -> AnswerObligation:
    """Derive a bounded answer contract from the current turn and route."""
    tokens = obligation_tokens(getattr(ctx, "latest_customer_message", ""))
    capability = str(getattr(route, "capability", ""))
    policy_kind = getattr(route, "policy_kind", None)
    target_product, target_category, target_ambiguity = _target(ctx)
    source_id = str(getattr(ctx, "source_message_id", ""))
    refs = (source_id,) if source_id else ()

    attribute = _attribute_from_tokens(tokens)
    # A product name can be the direct answer to our immediately preceding
    # "which product?" clarification.  Carry only the requested attribute
    # across that bounded adjacent turn; do not infer a slot from ordinary
    # product descriptions or stale conversation history.
    if attribute is None and target_product:
        for message in reversed((getattr(ctx, "recent_messages", []) or [])[-3:]):
            if not isinstance(message, dict) or message.get("role") != "assistant":
                continue
            prior_tokens = obligation_tokens(str(message.get("content") or ""))
            asks_for_product = "product" in prior_tokens or "\u0645\u0646\u062a\u062c" in prior_tokens
            if not asks_for_product:
                continue
            for candidate_attribute, aliases in _ATTRIBUTE_ALIASES.items():
                if _has_any(prior_tokens, aliases):
                    attribute = candidate_attribute
                    break
            if attribute is not None:
                break
    recency = (
        _contains_phrase(tokens, ("اخر", "موديل"))
        or _contains_phrase(tokens, ("احدث", "موديل"))
        or _contains_phrase(tokens, ("latest", "model"))
        or ("موديل" in tokens and _has_any(tokens, {"جديد", "نازل", "newest", "new"}))
    )
    if recency:
        return AnswerObligation(
            obligation_type=ObligationType.RECENCY_QUESTION,
            requested_subject="model",
            requested_attribute="RELEASE_RECENCY",
            target_product=target_product,
            target_category=target_category,
            reference_source_message_ids=refs,
            required_facts=("RELEASE_RECENCY",),
            forbidden_substitutions=("PRODUCT_DESCRIPTION", "PRICE", "UNRELATED_SPECIFICATION"),
            acceptable_outcomes=(AcceptableOutcome.DIRECT_ANSWER, AcceptableOutcome.EXPLICIT_UNKNOWN, AcceptableOutcome.CLARIFICATION),
            completion_criteria=("name_latest_model_or_name_missing_recency_data",),
            confidence=0.98,
            ambiguity_reason=target_ambiguity,
        )

    support_tokens = {"مشكل", "مشكله", "مشكلة", "عيب", "صوت", "مكسور", "ناقص", "تالف", "مش", "بيتحرك", "بتتحرك"}
    delivery_issue = (
        _contains_phrase(tokens, ("الطلب", "وصل", "ناقص"))
        or _contains_phrase(tokens, ("order", "arrived", "missing"))
        or (_has_any(tokens, {"الطلب", "شحنه", "شحنة", "الشحنه", "الشحنة", "اوردر", "order", "shipment"}) and _has_any(tokens, {"ناقص", "مفقود", "جزء", "missing", "damaged", "تالف"}))
    )
    if delivery_issue:
        return AnswerObligation(
            obligation_type=ObligationType.ORDER_SUPPORT_ISSUE,
            requested_subject="order",
            requested_attribute="MISSING_OR_DAMAGED_DELIVERY",
            reference_source_message_ids=refs,
            required_facts=("ORDER_NUMBER", "ISSUE_DETAIL"),
            forbidden_substitutions=("PRODUCT_RECOMMENDATION", "NEW_PURCHASE"),
            acceptable_outcomes=(AcceptableOutcome.CLARIFICATION, AcceptableOutcome.ACTION_EXECUTION),
            completion_criteria=("ask_for_order_identifier_and_missing_or_damaged_item",),
            confidence=0.98,
            issue_type="delivery_issue",
        )
    if _has_any(tokens, support_tokens) and any(token in tokens for token in ("مشكل", "مشكله", "مشكلة", "عيب", "صوت", "مكسور", "بيتحرك", "بتتحرك")):
        issue_type = "sound" if "صوت" in tokens else ("adjustment" if any(item in tokens for item in ("بيتحرك", "بتتحرك")) else None)
        return AnswerObligation(
            obligation_type=ObligationType.PRODUCT_SUPPORT_ISSUE,
            requested_subject="product_support",
            target_product=target_product,
            target_category=target_category,
            reference_source_message_ids=refs,
            required_facts=("ISSUE_DETAIL",),
            forbidden_substitutions=("PRODUCT_RECOMMENDATION", "BUDGET_DISCOVERY", "UNRELATED_SPECIFICATION"),
            acceptable_outcomes=(AcceptableOutcome.CLARIFICATION, AcceptableOutcome.ACTION_EXECUTION, AcceptableOutcome.DIRECT_ANSWER),
            completion_criteria=("ask_for_problem_detail_or_use_documented_troubleshooting",),
            confidence=0.96,
            ambiguity_reason=None if issue_type else "issue_detail_missing",
            issue_type=issue_type,
        )

    history = _history_text(ctx)
    price_context = any("سعر" in entry or "بكام" in entry or "price" in entry for entry in history)
    if ("غالي" in tokens and any(item in tokens for item in ("مش", "لا"))) or _contains_phrase(tokens, ("السعر", "مناسب")) or _contains_phrase(tokens, ("لا", "السعر", "مناسب")):
        return AnswerObligation(
            obligation_type=ObligationType.CONTEXTUAL_POLARITY_UPDATE,
            requested_subject="price",
            target_product=target_product,
            reference_source_message_ids=refs,
            required_facts=("ACTIVE_PRICE_CONTEXT",),
            forbidden_substitutions=("PRICE_OBJECTION", "GENERIC_DISCOVERY"),
            acceptable_outcomes=(AcceptableOutcome.DIRECT_ANSWER, AcceptableOutcome.CLARIFICATION, AcceptableOutcome.ACTION_EXECUTION),
            completion_criteria=("acknowledge_price_is_acceptable_and_continue_active_context",),
            confidence=0.95 if price_context or target_product else 0.88,
            ambiguity_reason=None if price_context or target_product else "no_active_price_context",
        )

    if attribute:
        ambiguity = target_ambiguity if not target_product else None
        outcomes = (AcceptableOutcome.DIRECT_ANSWER, AcceptableOutcome.EXPLICIT_UNKNOWN)
        if not target_product:
            outcomes += (AcceptableOutcome.CLARIFICATION,)
        return AnswerObligation(
            obligation_type=ObligationType.ATTRIBUTE_QUESTION,
            requested_subject="product",
            requested_attribute=attribute,
            target_product=target_product,
            target_category=target_category,
            reference_source_message_ids=refs,
            required_facts=(attribute,),
            forbidden_substitutions=tuple(item for item in _ATTRIBUTE_ALIASES if item != attribute),
            acceptable_outcomes=outcomes,
            completion_criteria=("answer_requested_attribute_or_name_it_as_unknown",),
            confidence=0.97,
            ambiguity_reason=ambiguity,
        )

    if capability.endswith("DELIVERY_STATUS"):
        return AnswerObligation(
            obligation_type=ObligationType.ORDER_STATUS,
            requested_subject="order",
            requested_attribute="ORDER_STATUS",
            reference_source_message_ids=refs,
            required_facts=("ORDER_NUMBER",),
            forbidden_substitutions=("HUMAN_HANDOFF", "PRODUCT_DISCOVERY"),
            acceptable_outcomes=(AcceptableOutcome.DIRECT_ANSWER, AcceptableOutcome.CLARIFICATION, AcceptableOutcome.EXPLICIT_UNKNOWN),
            completion_criteria=("answer_status_or_request_order_identifier",),
            confidence=0.98,
        )

    if any(token.endswith("\u062a\u062a\u0635\u0644\u0634") or token == "dontcall" for token in tokens):
        return AnswerObligation(
            obligation_type=ObligationType.NEGATIVE_CONTACT,
            requested_action="NO_HANDOFF_OR_CALLBACK",
            reference_source_message_ids=refs,
            forbidden_substitutions=("HUMAN_HANDOFF", "CALLBACK"),
            acceptable_outcomes=(AcceptableOutcome.DIRECT_ANSWER,),
            completion_criteria=("acknowledge_no_contact_and_continue_in_chat",),
            confidence=0.97,
        )
    if (
        _contains_phrase(tokens, ("مش", "عايز", "اتكلم", "حد"))
        or _contains_phrase(tokens, ("مش", "عايز", "اكلم", "حد"))
        or (_has_any(tokens, {"مش", "لا"}) and _has_any(tokens, {"مكالمه", "مكالمة", "اتصال", "call"}) and _has_any(tokens, {"حابب", "عايز", "want"}))
    ):
        return AnswerObligation(
            obligation_type=ObligationType.NEGATIVE_CONTACT,
            requested_action="NO_HANDOFF_OR_CALLBACK",
            reference_source_message_ids=refs,
            forbidden_substitutions=("HUMAN_HANDOFF", "CALLBACK"),
            acceptable_outcomes=(AcceptableOutcome.DIRECT_ANSWER,),
            completion_criteria=("acknowledge_no_contact_and_continue_in_chat",),
            confidence=0.97,
        )
    if _contains_phrase(tokens, ("مش", "عايز", "اشتري", "دلوقتي")):
        return AnswerObligation(
            obligation_type=ObligationType.PURCHASE_DEFERRAL,
            requested_action="DEFER_PURCHASE",
            reference_source_message_ids=refs,
            forbidden_substitutions=("PURCHASE_HANDOFF", "CONTACT_REQUEST"),
            acceptable_outcomes=(AcceptableOutcome.DIRECT_ANSWER,),
            completion_criteria=("acknowledge_no_purchase_pressure",),
            confidence=0.97,
        )
    if _contains_phrase(tokens, ("قصدي", "التاني")) or _contains_phrase(tokens, ("لا", "مش", "ده")):
        return AnswerObligation(
            obligation_type=ObligationType.REFERENCE_CORRECTION,
            requested_subject="product_reference",
            reference_source_message_ids=refs,
            acceptable_outcomes=(AcceptableOutcome.CLARIFICATION,),
            completion_criteria=("clarify_correct_reference_without_stale_topic",),
            confidence=0.91,
        )

    if policy_kind:
        return AnswerObligation(
            obligation_type=ObligationType.POLICY_QUESTION,
            requested_policy=str(policy_kind),
            reference_source_message_ids=refs,
            required_facts=(str(policy_kind),),
            acceptable_outcomes=(AcceptableOutcome.DIRECT_ANSWER, AcceptableOutcome.EXPLICIT_UNKNOWN),
            completion_criteria=("name_requested_policy_or_specific_missing_policy",),
            confidence=0.95,
        )
    if getattr(route, "execute_action", None) or getattr(route, "offered_action", None):
        return AnswerObligation(
            obligation_type=ObligationType.ACTION_REQUEST,
            requested_action=getattr(route, "execute_action", None) or getattr(route, "offered_action", None),
            reference_source_message_ids=refs,
            acceptable_outcomes=(AcceptableOutcome.ACTION_EXECUTION, AcceptableOutcome.CLARIFICATION),
            completion_criteria=("offer_or_execute_the_requested_action",),
            confidence=float(getattr(route, "confidence", 0.9) or 0.9),
        )
    return AnswerObligation(obligation_type=ObligationType.GENERIC, confidence=float(getattr(route, "confidence", 0.0) or 0.0))
