"""Deterministic semantic fulfillment checks for the latest customer turn."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

from services.answer_obligation import (
    AcceptableOutcome,
    AnswerObligation,
    ObligationType,
    attribute_label,
    normalize_obligation_text,
    obligation_tokens,
)


_UNKNOWN_MARKERS = (
    "مش مسجله", "مش مسجل", "غير مسجله", "غير مسجل", "مش متاح", "غير متاح",
    "ما عنديش", "معنديش", "مش ظاهر", "not recorded", "not documented", "unavailable", "unknown",
)
_GENERIC_DISCOVERY_MARKERS = (
    "تختار موديل", "اختار الانسب", "اختيار مناسب", "استخدامك وميزانيتك",
    "help you choose", "suitable model", "what would you like to check",
)


@dataclass(frozen=True)
class FulfillmentResult:
    passed: bool
    outcome: str | None
    violations: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _contains_any(text: str, markers: Iterable[str]) -> bool:
    normalized = normalize_obligation_text(text)
    return any(normalize_obligation_text(marker) in normalized for marker in markers)


def _is_question(text: str) -> bool:
    normalized = normalize_obligation_text(text)
    return "؟" in text or "?" in text or any(marker in normalized for marker in ("ايه", "ماذا", "وضح", "اكتب", "ابعت", "which", "what", "please provide"))


def _slot_mentions(text: str, attribute: str | None) -> bool:
    tokens = set(obligation_tokens(text))
    if str(attribute or "") == "PRICE" and "\u0627\u0644\u0633\u0639\u0631" in tokens:
        return True
    aliases = {
        "COLOR": {"لون", "الوان", "color", "colors", "colour", "colours"},
        "DIMENSIONS": {"مقاس", "المقاس", "مقاسات", "المقاسات", "ابعاد", "الابعاد", "طول", "عرض", "ارتفاع", "dimension", "dimensions", "size"},
        "MATERIAL": {"خامه", "الخامه", "ماده", "material", "mesh", "leather"},
        "WEIGHT_CAPACITY": {"تحمل", "التحمل", "قدره", "قدرة", "يتحمل", "وزن", "الوزن", "capacity", "weight"},
        "ARMRESTS": {"مسند", "مسندات", "ذراع", "armrest"},
        "LUMBAR_SUPPORT": {"قطني", "lumbar"},
        "HEADREST": {"راس", "headrest"},
        "ADJUSTABILITY": {"تعديل", "يتحرك", "adjustable"},
        "PRICE": {"سعر", "بكام", "price"},
        "AVAILABILITY": {"متوفر", "متاح", "availability", "available", "stock"},
        "WARRANTY": {"ضمان", "warranty"},
        "MODEL_VERSION": {"موديل", "اصدار", "version", "model"},
        "RELEASE_RECENCY": {"احدث", "اخر", "موديل", "ترتيب", "latest", "newest", "release"},
    }
    return bool(tokens.intersection(aliases.get(str(attribute or ""), {normalize_obligation_text(attribute or "")})))


def verify_fulfillment(reply: str, obligation: AnswerObligation | None, *, cards: Iterable[dict[str, Any]] = ()) -> FulfillmentResult:
    """Verify semantic completion separately from factual claim validation."""
    if obligation is None or not obligation.requires_specific_fulfillment:
        return FulfillmentResult(True, AcceptableOutcome.DIRECT_ANSWER)

    normalized = normalize_obligation_text(reply)
    violations: list[str] = []
    unknown = _contains_any(reply, _UNKNOWN_MARKERS)
    generic_discovery = _contains_any(reply, _GENERIC_DISCOVERY_MARKERS)
    obligation_type = obligation.obligation_type

    if obligation_type == ObligationType.ATTRIBUTE_QUESTION:
        slot = obligation.requested_attribute
        slot_named = _slot_mentions(reply, slot)
        if not slot_named:
            violations.append("REQUESTED_SLOT_NOT_NAMED")
        if unknown and slot_named:
            return FulfillmentResult(not violations, AcceptableOutcome.EXPLICIT_UNKNOWN, tuple(violations))
        if generic_discovery:
            violations.append("GENERIC_DISCOVERY_SUBSTITUTED_FOR_ATTRIBUTE")
        if not obligation.target_product and _is_question(reply) and ("منتج" in normalized or "product" in normalized):
            return FulfillmentResult(not violations, AcceptableOutcome.CLARIFICATION, tuple(violations))
        if slot_named and not violations:
            return FulfillmentResult(True, AcceptableOutcome.DIRECT_ANSWER)

    elif obligation_type == ObligationType.RECENCY_QUESTION:
        recency_named = _slot_mentions(reply, "RELEASE_RECENCY")
        if not recency_named:
            violations.append("RECENCY_NOT_ADDRESSED")
        if generic_discovery:
            violations.append("GENERIC_DISCOVERY_SUBSTITUTED_FOR_RECENCY")
        if unknown and recency_named:
            return FulfillmentResult(not violations, AcceptableOutcome.EXPLICIT_UNKNOWN, tuple(violations))
        if recency_named and not violations:
            return FulfillmentResult(True, AcceptableOutcome.DIRECT_ANSWER)

    elif obligation_type == ObligationType.PRODUCT_SUPPORT_ISSUE:
        support_prompt = _contains_any(reply, ("ايه المشكله", "ايه المشكلة", "المشكله", "المشكلة", "ممكن تقول", "وضح", "تفاصيل المشكله", "تفاصيل المشكلة", "حصل امتى", "صوت", "مساند", "problem", "issue"))
        if generic_discovery:
            violations.append("GENERIC_DISCOVERY_SUBSTITUTED_FOR_SUPPORT")
        if not support_prompt:
            violations.append("SUPPORT_ISSUE_NOT_CLARIFIED")
        if support_prompt and not violations:
            return FulfillmentResult(True, AcceptableOutcome.CLARIFICATION)

    elif obligation_type == ObligationType.ORDER_SUPPORT_ISSUE:
        if "رقم الطلب" not in normalized and "order number" not in normalized:
            violations.append("ORDER_SUPPORT_IDENTIFIER_NOT_REQUESTED")
        if not _contains_any(reply, ("الناقص", "مفقوده", "missing", "damaged", "تالف")):
            violations.append("ORDER_SUPPORT_ISSUE_NOT_NAMED")
        if not violations:
            return FulfillmentResult(True, AcceptableOutcome.CLARIFICATION)

    elif obligation_type == ObligationType.ORDER_STATUS:
        if "رقم الطلب" not in normalized and "order number" not in normalized and not unknown:
            violations.append("ORDER_STATUS_NOT_FULFILLED")
        if not violations:
            return FulfillmentResult(True, AcceptableOutcome.CLARIFICATION if "رقم الطلب" in normalized or "order number" in normalized else AcceptableOutcome.EXPLICIT_UNKNOWN)

    elif obligation_type == ObligationType.CONTEXTUAL_POLARITY_UPDATE:
        if not _contains_any(reply, ("السعر مناسب", "مش غالي", "تمام", "price works", "price is fine")):
            violations.append("POLARITY_UPDATE_NOT_ACKNOWLEDGED")
        if generic_discovery:
            violations.append("GENERIC_DISCOVERY_SUBSTITUTED_FOR_POLARITY")
        if not violations:
            return FulfillmentResult(True, AcceptableOutcome.DIRECT_ANSWER)

    elif obligation_type == ObligationType.NEGATIVE_CONTACT:
        if not _contains_any(reply, ("من غير تحويل", "من غير اتصال", "مش هنتصل", "no call", "no handoff")):
            violations.append("NEGATIVE_CONTACT_NOT_ACKNOWLEDGED")
        if not violations:
            return FulfillmentResult(True, AcceptableOutcome.DIRECT_ANSWER)

    elif obligation_type == ObligationType.PURCHASE_DEFERRAL:
        if not _contains_any(reply, ("مش هضغط", "خد وقتك", "مش لازم تشتري", "no pressure", "take your time")):
            violations.append("PURCHASE_DEFERRAL_NOT_ACKNOWLEDGED")
        if not violations:
            return FulfillmentResult(True, AcceptableOutcome.DIRECT_ANSWER)

    elif obligation_type == ObligationType.REFERENCE_CORRECTION:
        if not _is_question(reply) or not _contains_any(reply, ("المنتج", "الموديل", "product", "model")):
            violations.append("REFERENCE_CORRECTION_NOT_CLARIFIED")
        if not violations:
            return FulfillmentResult(True, AcceptableOutcome.CLARIFICATION)

    elif obligation_type == ObligationType.POLICY_QUESTION:
        policy = str(obligation.requested_policy or "")
        if policy and normalize_obligation_text(policy).replace("_", " ") not in normalized and not unknown:
            # Policy fallbacks use customer-facing Arabic names, so a specific
            # unknown marker is sufficient when the typed label is not prose.
            violations.append("REQUESTED_POLICY_NOT_NAMED")
        if not violations:
            return FulfillmentResult(True, AcceptableOutcome.EXPLICIT_UNKNOWN if unknown else AcceptableOutcome.DIRECT_ANSWER)

    elif obligation_type == ObligationType.ACTION_REQUEST:
        return FulfillmentResult(True, AcceptableOutcome.ACTION_EXECUTION)

    if any(card.get("description") and normalize_obligation_text(str(card.get("description"))) in normalized for card in cards):
        violations.append("DUPLICATE_CARD_TEXT")
    return FulfillmentResult(False, None, tuple(dict.fromkeys(violations)))
