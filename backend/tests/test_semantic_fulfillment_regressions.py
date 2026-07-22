"""Targeted regressions found by the real HTTP semantic campaign."""

from types import SimpleNamespace

from services.answer_obligation import ObligationType, derive_answer_obligation
from services.fulfillment_verifier import verify_fulfillment
from services.velor_chat_v2 import ResponsePlan, execute_contextual_fallback


def _context(turn: str):
    product = {"name": "Arvena Ergo One", "price": 6900, "currency": "EGP"}
    return SimpleNamespace(
        latest_customer_message=turn,
        source_message_id=1,
        product_resolution={"resolved_products": [product]},
        current_product_references=[product["name"]],
        trusted_catalog_products=[product],
        recent_messages=[],
        merchant_tone="Professional",
        applicable_policies={},
        explicit_budget=None,
        company_id="regression",
        visitor_id="visitor",
    )


def _reply(ctx, capability: str, plan_type: str):
    route = SimpleNamespace(capability=capability, policy_kind=None, execute_action=None, offered_action=None, confidence=0.98)
    obligation = derive_answer_obligation(ctx, route)
    plan = ResponsePlan(
        plan_type=plan_type,
        contact_capture_allowed=False,
        allowed_facts=[],
        capability=capability,
        answer_obligation=obligation,
    )
    return obligation, execute_contextual_fallback(ctx, plan)


def test_price_response_names_the_definite_price_slot():
    obligation, reply = _reply(_context("Arvena Ergo One \u0628\u0643\u0627\u0645\u061f"), "PRICE_QUESTION", "PRODUCT_PRICE")
    assert obligation.obligation_type == ObligationType.ATTRIBUTE_QUESTION
    assert obligation.requested_attribute == "PRICE"
    assert reply == "\u0627\u0644\u0633\u0639\u0631 Arvena Ergo One \u0627\u0644\u0645\u0633\u062c\u0644 \u0647\u0648: 6900 EGP."
    assert verify_fulfillment(reply, obligation).passed


def test_direct_arabic_no_call_form_has_a_no_contact_obligation():
    obligation, reply = _reply(_context("\u0645\u0627 \u062a\u062a\u0635\u0644\u0634 \u0628\u064a\u0627"), "CALLBACK_DECLINED", "CALLBACK_DECLINED")
    assert obligation.obligation_type == ObligationType.NEGATIVE_CONTACT
    assert verify_fulfillment(reply, obligation).passed


def test_product_name_after_attribute_clarification_completes_the_original_slot():
    ctx = _context("Arvena Ergo One")
    ctx.recent_messages = [{
        "role": "assistant",
        "content": "\u0639\u0627\u064a\u0632 \u062a\u0639\u0631\u0641 \u0623\u0644\u0648\u0627\u0646 \u0623\u0646\u0647\u064a \u0645\u0646\u062a\u062c \u0628\u0627\u0644\u0636\u0628\u0637\u061f",
    }]
    obligation, reply = _reply(ctx, "PRODUCT_SELECTION", "PRODUCT_SELECTION")
    assert obligation.obligation_type == ObligationType.ATTRIBUTE_QUESTION
    assert obligation.requested_attribute == "COLOR"
    assert reply.startswith("\u0623\u0644\u0648\u0627\u0646")
    assert verify_fulfillment(reply, obligation).passed
