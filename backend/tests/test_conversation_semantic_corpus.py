"""A compact 204-case semantic regression corpus for the capability boundary."""

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from services.conversation_capability_router import ConversationCapability, route_customer_capability


@dataclass(frozen=True)
class SemanticCase:
    case_id: str
    customer_turn: str
    expected_capability: ConversationCapability
    expected_action: str | None
    required_facts: tuple[str, ...]
    forbidden_facts: tuple[str, ...]
    max_products: int
    max_questions: int
    language: str
    pending_question: str | None = None


_ACTION_STATE = '{"conversation_scope":{"company_id":"corpus","visitor_id":"visitor","channel":"VELOR_WEB_CHAT"},"offered_action":{"type":"REQUEST_OWNER_VERIFICATION","status":"offered"}}'

_SEEDS = (
    ("social", "ألو", ConversationCapability.SOCIAL, None, (), (), 0, 1, "ar", None),
    ("thanks", "شكراً", ConversationCapability.ACKNOWLEDGEMENT, None, (), (), 0, 1, "ar", None),
    ("continue", "كمل", ConversationCapability.UNRESOLVED_DIALOGUE, None, (), (), 0, 1, "ar", None),
    ("noise", "؟", ConversationCapability.UNCLEAR_OR_NOISE, None, (), (), 0, 1, "ar", None),
    ("discovery", "عايز كرسي مكتب", ConversationCapability.PRODUCT_DISCOVERY, None, ("category",), (), 3, 1, "ar", None),
    ("price", "بكام Ergo One؟", ConversationCapability.PRICE_QUESTION, None, ("price",), (), 1, 1, "mixed", None),
    ("compare", "قارن Ergo One وErgo Pro", ConversationCapability.PRODUCT_COMPARISON, None, ("products",), (), 2, 1, "mixed", None),
    ("objection", "السعر غالي أوي", ConversationCapability.PRICE_OBJECTION, None, (), (), 0, 1, "ar", None),
    ("budget", "ميزانيتي 7000 جنيه", ConversationCapability.BUDGET, None, ("budget",), (), 3, 1, "ar", None),
    ("installments", "فيه تقسيط؟", ConversationCapability.POLICY_QUESTION, "REQUEST_OWNER_VERIFICATION", (), ("installment:invented",), 0, 1, "ar", None),
    ("purchase", "عايز أشتريه", ConversationCapability.PURCHASE_ADVANCEMENT, "PURCHASE_HANDOFF", (), (), 1, 1, "ar", None),
    ("handoff", "وصلني بخدمة العملاء", ConversationCapability.HUMAN_HANDOFF_REQUEST, "START_HUMAN_HANDOFF", (), (), 0, 1, "ar", None),
    ("verify", "اسأل الفريق", ConversationCapability.OWNER_VERIFICATION_REQUEST, "REQUEST_OWNER_VERIFICATION", (), (), 0, 1, "ar", None),
    ("accept", "اسأل الفريق", ConversationCapability.OWNER_VERIFICATION_ACCEPTANCE, "ACCEPT_OWNER_VERIFICATION", (), (), 0, 0, "ar", _ACTION_STATE),
    ("cancel", "كنسل الطلب", ConversationCapability.CANCELLATION, "CANCEL_OWNER_VERIFICATION", (), (), 0, 0, "ar", _ACTION_STATE),
    ("unknown", "الكرسي بيتحمل 200 كيلو؟", ConversationCapability.UNKNOWN_COMMERCIAL_FACT, "REQUEST_OWNER_VERIFICATION", (), ("weight:200",), 0, 1, "ar", None),
    ("angry", "الخدمة دي زفت", ConversationCapability.DEESCALATION, None, (), (), 0, 1, "ar", None),
    ("ood", "مين كسب الماتش؟", ConversationCapability.OUT_OF_DOMAIN, None, (), (), 0, 1, "ar", None),
)


def _build_cases():
    cases = []
    variants = ("", "!", "؟", "  ", " لو سمحت", " دلوقتي", " please", "!!!", " 🙂", " بس", " بجد", " حالاً")
    for seed_id, turn, capability, action, required, forbidden, max_products, max_questions, language, pending in _SEEDS:
        for index, suffix in enumerate(variants):
            cases.append(SemanticCase(
                case_id=f"{seed_id}-{index + 1}",
                customer_turn=f"{turn}{suffix}",
                expected_capability=capability,
                expected_action=action,
                required_facts=required,
                forbidden_facts=forbidden,
                max_products=max_products,
                max_questions=max_questions,
                language=language,
                pending_question=pending,
            ))
    return cases


CASES = _build_cases()
assert len(CASES) == 216


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.case_id)
def test_semantic_corpus_routes_each_latest_turn(case):
    ctx = SimpleNamespace(
        latest_customer_message=case.customer_turn,
        company_id="corpus",
        visitor_id="visitor",
        product_resolution={},
        pending_question_payload=case.pending_question,
    )
    decision = route_customer_capability(ctx)
    assert decision.capability == case.expected_capability
    assert (decision.execute_action or decision.offered_action) == case.expected_action
