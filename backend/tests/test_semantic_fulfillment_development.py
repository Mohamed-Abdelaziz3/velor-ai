"""Development corpus: 300 semantic answer-fulfillment cases."""

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from services.answer_obligation import ObligationType, derive_answer_obligation
from services.fulfillment_verifier import verify_fulfillment
from services.velor_chat_v2 import ResponsePlan, execute_contextual_fallback


_VARIANTS = (
    "", "؟", "!", " دلوقتي", " لو سمحت", " يا فندم", " بجد", " حالياً", " please", "!!!",
    "؟", " بسرعة", " من فضلك", " كده", " طيب", " معلش", " شوية", " لو تقدر", " now", "؟!",
    " تمام", " يا ريت", " حالاً", " فورا", " من غير تفاصيل زيادة", " عادي", " ليه", " بالظبط", " مرة تانية", " لو أمكن",
)


@dataclass(frozen=True)
class Family:
    name: str
    base_turn: str
    capability: str
    plan_type: str
    expected_obligation: str
    policy_kind: str | None = None
    execute_action: str | None = None
    offered_action: str | None = None
    history: tuple[dict, ...] = ()


_FAMILIES = (
    Family("color", "الوان الكرسي ايه", "PRODUCT_DETAILS", "PRODUCT_SPECS", ObligationType.ATTRIBUTE_QUESTION),
    Family("support", "معايا مشكلة في الكرسي", "CLARIFICATION", "CLARIFY", ObligationType.PRODUCT_SUPPORT_ISSUE),
    Family("recency", "اخر موديل ايه", "PRODUCT_DISCOVERY", "CATEGORY_DISCOVERY", ObligationType.RECENCY_QUESTION),
    Family("price_correction", "مش غالي", "CLARIFICATION", "CLARIFY", ObligationType.CONTEXTUAL_POLARITY_UPDATE, history=({"role": "assistant", "content": "سعر Arvena Ergo One هو 6900 EGP"},)),
    Family("no_contact", "مش عايز اكلم حد", "CLARIFICATION", "CLARIFY", ObligationType.NEGATIVE_CONTACT),
    Family("order_status", "وصلني الطلب", "DELIVERY_STATUS", "POLICY_ANSWER", ObligationType.ORDER_STATUS, policy_kind="delivery_status"),
    Family("payment_order", "ادفع ازاي واطلب", "PAYMENT_PROCESS", "POLICY_ANSWER", ObligationType.POLICY_QUESTION, policy_kind="payment_and_order"),
    Family("installments", "فيه تقسيط", "POLICY_QUESTION", "POLICY_ANSWER", ObligationType.POLICY_QUESTION, policy_kind="installments", offered_action="REQUEST_OWNER_VERIFICATION"),
    Family("verify", "اسأل الفريق", "OWNER_VERIFICATION_ACCEPTANCE", "OWNER_VERIFICATION_ACCEPTANCE", ObligationType.ACTION_REQUEST, execute_action="ACCEPT_OWNER_VERIFICATION"),
    Family("handoff", "وصلني بخدمة العملاء", "HUMAN_HANDOFF_REQUEST", "HUMAN_HANDOFF", ObligationType.ACTION_REQUEST, execute_action="START_HUMAN_HANDOFF"),
)

CASES = tuple((family, index, suffix) for family in _FAMILIES for index, suffix in enumerate(_VARIANTS, start=1))
assert len(CASES) == 300


def _context(turn: str, history: tuple[dict, ...]):
    product = {
        "name": "Arvena Ergo One",
        "category": "كراسي مكتبية",
        "price": 6900,
        "currency": "EGP",
        "description": "كرسي بظهر شبكي ودعم قطني",
    }
    return SimpleNamespace(
        latest_customer_message=turn,
        source_message_id=1,
        product_resolution={"resolved_products": [product]},
        current_product_references=[product["name"]],
        trusted_catalog_products=[product],
        recent_messages=list(history),
        merchant_tone="Professional",
        applicable_policies={},
        explicit_budget=None,
        company_id="development",
        visitor_id="visitor",
    )


@pytest.mark.parametrize("family,index,suffix", CASES, ids=[f"{family.name}-{index}" for family, index, _ in CASES])
def test_development_semantic_fulfillment_corpus(family, index, suffix):
    ctx = _context(f"{family.base_turn}{suffix}", family.history)
    route = SimpleNamespace(
        capability=family.capability,
        policy_kind=family.policy_kind,
        execute_action=family.execute_action,
        offered_action=family.offered_action,
        confidence=0.98,
    )
    obligation = derive_answer_obligation(ctx, route)
    assert obligation.obligation_type == family.expected_obligation

    plan = ResponsePlan(
        plan_type=family.plan_type,
        contact_capture_allowed=False,
        allowed_facts=[],
        capability=family.capability,
        policy_kind=family.policy_kind,
        execute_action=family.execute_action,
        offered_action=family.offered_action,
        answer_obligation=obligation,
    )
    reply = execute_contextual_fallback(ctx, plan)
    result = verify_fulfillment(reply, obligation)
    assert result.passed, (family.name, index, reply, result.violations)
    assert "تختار موديل مناسب" not in reply
