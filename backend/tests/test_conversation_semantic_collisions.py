"""300 deterministic collision cases for the public-turn capability boundary."""

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from services.conversation_capability_router import (
    ConversationCapability,
    CustomerActionType,
    route_customer_capability,
)


_PENDING_VERIFICATION = (
    '{"conversation_scope":{"company_id":"collision","visitor_id":"visitor","channel":"VELOR_WEB_CHAT"},'
    '"offered_action":{"type":"REQUEST_OWNER_VERIFICATION","status":"offered"}}'
)


@dataclass(frozen=True)
class CollisionSeed:
    name: str
    text: str
    capability: ConversationCapability
    action: str | None = None
    pending: str | None = None


_SEEDS = (
    CollisionSeed("colour_not_greeting", "الوان الكرسي ايه", ConversationCapability.PRODUCT_DETAILS),
    CollisionSeed("delivery_not_handoff", "وصلني الطلب", ConversationCapability.DELIVERY_STATUS),
    CollisionSeed("problem_not_budget", "معايا مشكلة في الكرسي", ConversationCapability.CLARIFICATION),
    CollisionSeed("latest_not_budget", "اخر موديل ايه", ConversationCapability.PRODUCT_DISCOVERY),
    CollisionSeed("negated_handoff", "مش عايز اكلم حد", ConversationCapability.CLARIFICATION),
    CollisionSeed("no_callback", "ما تتصلش بيا", ConversationCapability.CALLBACK_DECLINED),
    CollisionSeed("negated_objection", "مش غالي", ConversationCapability.CLARIFICATION),
    CollisionSeed("payment_and_order", "ادفع ازاي واطلب", ConversationCapability.PAYMENT_PROCESS),
    CollisionSeed("positive_handoff", "وصلني بخدمة العملاء", ConversationCapability.HUMAN_HANDOFF_REQUEST, CustomerActionType.START_HUMAN_HANDOFF.value),
    CollisionSeed("verify_accept", "اسأل الفريق", ConversationCapability.OWNER_VERIFICATION_ACCEPTANCE, CustomerActionType.ACCEPT_OWNER_VERIFICATION.value, _PENDING_VERIFICATION),
    CollisionSeed("verify_offer", "اسأل الفريق", ConversationCapability.OWNER_VERIFICATION_REQUEST, CustomerActionType.REQUEST_OWNER_VERIFICATION.value),
    CollisionSeed("verify_cancel", "كنسل الطلب", ConversationCapability.CANCELLATION, CustomerActionType.CANCEL_OWNER_VERIFICATION.value, _PENDING_VERIFICATION),
    CollisionSeed("double_negation", "مش مش عايز اكلم حد", ConversationCapability.HUMAN_HANDOFF_REQUEST, CustomerActionType.START_HUMAN_HANDOFF.value),
    CollisionSeed("double_negation_with_la", "لا مش عايز اكلم حد", ConversationCapability.HUMAN_HANDOFF_REQUEST, CustomerActionType.START_HUMAN_HANDOFF.value),
    CollisionSeed("product_discovery", "عايز كرسي للشغل", ConversationCapability.PRODUCT_RECOMMENDATION),
    CollisionSeed("explicit_budget", "ميزانيتي 7000 جنيه", ConversationCapability.BUDGET),
    CollisionSeed("purchase", "عايز اشتري Ergo One", ConversationCapability.PURCHASE_ADVANCEMENT, CustomerActionType.PURCHASE_HANDOFF.value),
    CollisionSeed("reserve", "عايز احجز", ConversationCapability.PURCHASE_ADVANCEMENT, CustomerActionType.PURCHASE_HANDOFF.value),
    CollisionSeed("payment", "طريقة الدفع ايه", ConversationCapability.PAYMENT_PROCESS),
    CollisionSeed("ordering", "ازاي اطلب", ConversationCapability.ORDERING_PROCESS),
    CollisionSeed("installments", "فيه تقسيط", ConversationCapability.POLICY_QUESTION, CustomerActionType.REQUEST_OWNER_VERIFICATION.value),
    CollisionSeed("delivery_partial", "الطلب وصل ناقص", ConversationCapability.DELIVERY_STATUS),
    CollisionSeed("human_agent", "ممكن اكلم انسان", ConversationCapability.HUMAN_HANDOFF_REQUEST, CustomerActionType.START_HUMAN_HANDOFF.value),
    CollisionSeed("callback_declined", "من غير مكالمة", ConversationCapability.CALLBACK_DECLINED),
    CollisionSeed("callback_requested", "ممكن تتصل بيا", ConversationCapability.CALLBACK_REQUEST, CustomerActionType.REQUEST_CONTACT.value),
    CollisionSeed("acknowledgement", "شكرا", ConversationCapability.ACKNOWLEDGEMENT),
    CollisionSeed("greeting", "ألو", ConversationCapability.SOCIAL),
    CollisionSeed("price", "Ergo One بكام", ConversationCapability.PRICE_QUESTION),
    CollisionSeed("comparison", "قارن Ergo One و Ergo Pro", ConversationCapability.PRODUCT_COMPARISON),
    CollisionSeed("unknown_fact", "الكرسي بيتحمل 200 كيلو", ConversationCapability.UNKNOWN_COMMERCIAL_FACT, CustomerActionType.REQUEST_OWNER_VERIFICATION.value),
)

_SUFFIXES = ("", "!", "؟", " لو سمحت", " دلوقتي", " please", "!!!", " بس", " بجد", " حاليا")

CASES = tuple(
    (f"{seed.name}-{index + 1}", f"{seed.text}{suffix}", seed.capability, seed.action, seed.pending)
    for seed in _SEEDS
    for index, suffix in enumerate(_SUFFIXES)
)

assert len(CASES) == 300


@pytest.mark.parametrize("case_id,text,capability,action,pending", CASES, ids=[case[0] for case in CASES])
def test_collision_corpus(case_id, text, capability, action, pending):
    decision = route_customer_capability(SimpleNamespace(
        latest_customer_message=text,
        company_id="collision",
        visitor_id="visitor",
        product_resolution={},
        pending_question_payload=pending,
    ))
    assert decision.capability == capability, case_id
    assert (decision.execute_action or decision.offered_action) == action, case_id
    if decision.execute_action:
        assert decision.action_eligible is True, case_id
        assert decision.confidence >= 0.90, case_id


def test_collision_corpus_action_metrics_are_perfect_for_supported_actions():
    expected_actions = 0
    correct_actions = 0
    false_persistent_actions = 0
    for _case_id, text, expected_capability, expected_action, pending in CASES:
        decision = route_customer_capability(SimpleNamespace(
            latest_customer_message=text,
            company_id="collision",
            visitor_id="visitor",
            product_resolution={},
            pending_question_payload=pending,
        ))
        if expected_action:
            expected_actions += 1
            correct_actions += int((decision.execute_action or decision.offered_action) == expected_action)
        if expected_action is None and decision.execute_action:
            false_persistent_actions += 1
        assert decision.capability == expected_capability

    assert correct_actions / expected_actions == 1.0
    assert false_persistent_actions == 0
