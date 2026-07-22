from types import SimpleNamespace

import pytest

from services.conversation_capability_router import (
    ConversationCapability,
    CustomerActionType,
    route_customer_capability,
)


def _ctx(message, *, products=None, status=None, pending=None):
    return SimpleNamespace(
        latest_customer_message=message,
        company_id="tenant-a",
        visitor_id="visitor-a",
        product_resolution={"resolved_products": products or [], "status": status},
        pending_question_payload=pending,
    )


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("ألو", ConversationCapability.SOCIAL),
        ("شكراً", ConversationCapability.ACKNOWLEDGEMENT),
        ("كمل", ConversationCapability.UNRESOLVED_DIALOGUE),
        ("؟", ConversationCapability.UNCLEAR_OR_NOISE),
        ("عايز كرسي مكتب", ConversationCapability.PRODUCT_DISCOVERY),
        ("بكام Ergo One؟", ConversationCapability.PRICE_QUESTION),
        ("قارن بينهم", ConversationCapability.PRODUCT_COMPARISON),
        ("غالي أوي", ConversationCapability.PRICE_OBJECTION),
        ("ميزانيتي 7000 جنيه", ConversationCapability.BUDGET),
        ("فيه تقسيط؟", ConversationCapability.POLICY_QUESTION),
        ("عايز أشتريه", ConversationCapability.PURCHASE_ADVANCEMENT),
        ("وصلني بخدمة العملاء", ConversationCapability.HUMAN_HANDOFF_REQUEST),
        ("الخدمة دي زفت", ConversationCapability.DEESCALATION),
        ("مين كسب الماتش؟", ConversationCapability.OUT_OF_DOMAIN),
        ("الكرسي بيتحمل 200 كيلو؟", ConversationCapability.UNKNOWN_COMMERCIAL_FACT),
    ],
)
def test_router_keeps_distinct_customer_capabilities(message, expected):
    assert route_customer_capability(_ctx(message)).capability == expected


def test_usage_duration_keeps_the_active_product_context():
    decision = route_customer_capability(SimpleNamespace(
        latest_customer_message="استخدامي 8 ساعات في اليوم",
        company_id="tenant-a",
        visitor_id="visitor-a",
        product_resolution={"resolved_products": [], "status": None},
        current_product_references=["Arvena Ergo One"],
        pending_question_payload=None,
    ))

    assert decision.capability == ConversationCapability.PRODUCT_RECOMMENDATION
    assert decision.reason == "usage_duration_follow_up"


@pytest.mark.parametrize("message", ("انت غبي", "كسمين امك", "الخدمة دي زفت"))
def test_insults_deescalate_without_becoming_out_of_domain(message):
    assert route_customer_capability(_ctx(message)).capability == ConversationCapability.DEESCALATION


def test_policy_question_is_an_actionable_offer_not_an_unknown_default():
    decision = route_customer_capability(_ctx("ينفع تقسيط؟"))
    assert decision.capability == ConversationCapability.POLICY_QUESTION
    assert decision.offered_action == CustomerActionType.REQUEST_OWNER_VERIFICATION.value


def test_offered_verification_acceptance_executes_once_in_its_own_scope():
    pending = '{"conversation_scope":{"company_id":"tenant-a","visitor_id":"visitor-a","channel":"VELOR_WEB_CHAT"},"offered_action":{"type":"REQUEST_OWNER_VERIFICATION","status":"offered"}}'
    decision = route_customer_capability(_ctx("اسأل الفريق", pending=pending))
    assert decision.capability == ConversationCapability.OWNER_VERIFICATION_ACCEPTANCE
    assert decision.execute_action == CustomerActionType.ACCEPT_OWNER_VERIFICATION.value


def test_foreign_scope_cannot_accept_another_visitors_action():
    pending = '{"conversation_scope":{"company_id":"tenant-b","visitor_id":"visitor-b","channel":"VELOR_WEB_CHAT"},"offered_action":{"type":"REQUEST_OWNER_VERIFICATION","status":"offered"}}'
    decision = route_customer_capability(_ctx("تمام", pending=pending))
    assert decision.capability == ConversationCapability.ACKNOWLEDGEMENT
    assert decision.execute_action is None


def test_cancellation_resolves_the_active_verification_action():
    pending = '{"conversation_scope":{"company_id":"tenant-a","visitor_id":"visitor-a","channel":"VELOR_WEB_CHAT"},"offered_action":{"type":"REQUEST_OWNER_VERIFICATION","status":"offered"}}'
    decision = route_customer_capability(_ctx("كنسل الطلب", pending=pending))
    assert decision.capability == ConversationCapability.CANCELLATION
    assert decision.execute_action == CustomerActionType.CANCEL_OWNER_VERIFICATION.value
