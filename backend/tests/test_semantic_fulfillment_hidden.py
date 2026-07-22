"""Separate hidden-style acceptance corpus for semantic fulfillment.

The data lives in a fixture and is never imported by production code.  It uses
novel wording and multi-turn context distinct from the development corpus.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from services.answer_obligation import derive_answer_obligation
from services.fulfillment_verifier import verify_fulfillment
from services.velor_chat_v2 import ResponsePlan, execute_contextual_fallback


FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "semantic_fulfillment_hidden.json").read_text(encoding="utf-8"))
CASES = tuple((case, suffix) for case in FIXTURE["cases"] for suffix in FIXTURE["variants"])
assert len(CASES) == 150


def _context(turn, history_text=None):
    product = {
        "name": "Arvena Ergo One",
        "category": "كراسي مكتبية",
        "price": 6900,
        "currency": "EGP",
        "description": "كرسي بظهر شبكي ودعم قطني",
    }
    history = [{"role": "assistant", "content": history_text}] if history_text else []
    return SimpleNamespace(
        latest_customer_message=turn,
        source_message_id=2,
        product_resolution={"resolved_products": [product]},
        current_product_references=[product["name"]],
        trusted_catalog_products=[product],
        recent_messages=history,
        merchant_tone="Professional",
        applicable_policies={},
        explicit_budget=None,
        company_id="hidden",
        visitor_id="visitor",
    )


@pytest.mark.parametrize("case,suffix", CASES, ids=[f"{case['id']}-{index}" for case in FIXTURE["cases"] for index, _ in enumerate(FIXTURE["variants"], start=1)])
def test_hidden_semantic_fulfillment_acceptance(case, suffix):
    ctx = _context(f"{case['turn']}{suffix}", case.get("history"))
    route = SimpleNamespace(
        capability=case["capability"],
        policy_kind=case.get("policy_kind"),
        execute_action=None,
        offered_action=None,
        confidence=0.97,
    )
    obligation = derive_answer_obligation(ctx, route)
    assert obligation.obligation_type == case["obligation"]
    if case.get("attribute"):
        assert obligation.requested_attribute == case["attribute"]

    plan = ResponsePlan(
        plan_type=case["plan_type"],
        contact_capture_allowed=False,
        allowed_facts=[],
        capability=case["capability"],
        policy_kind=case.get("policy_kind"),
        answer_obligation=obligation,
    )
    reply = execute_contextual_fallback(ctx, plan)
    result = verify_fulfillment(reply, obligation)
    assert result.passed, (case["id"], reply, result.violations)
    assert result.outcome == case["outcome"]
