from types import SimpleNamespace

import pytest

from services.velor_chat_v2 import AllowedFact, ClaimVerifier


def _fact(fact_id, fact_type, value, product_key=None):
    return AllowedFact(
        fact_id=fact_id,
        fact_type=fact_type,
        value=value,
        source_type="catalog",
        source_id="products_data",
        product_key=product_key,
    )


def _comparison_context_and_plan():
    products = [
        {"name": "Alpha Chair", "price": 1000, "stock": 12, "warranty": "2 years", "description": "mesh back", "discount": "10%"},
        {"name": "Beta Chair", "price": 2000, "stock": 0, "warranty": "5 years", "description": "leather back", "discount": "20%"},
    ]
    facts = []
    for product in products:
        name = product["name"]
        key = name.lower().replace(" ", "-")
        facts.extend(
            [
                _fact(f"product-{key}", "product", name, name),
                _fact(f"price-{key}", "price", product["price"], name),
                _fact(f"stock-{key}", "availability", product["stock"], name),
                _fact(f"warranty-{key}", "warranty", product["warranty"], name),
                _fact(f"spec-{key}", "spec", product["description"], name),
                _fact(f"discount-{key}", "discount", product["discount"], name),
            ]
        )
    context = SimpleNamespace(
        explicit_budget=None,
        trusted_catalog_products=products,
        recent_messages=[],
    )
    plan = SimpleNamespace(
        allowed_facts=facts,
        contact_capture_allowed=False,
    )
    return context, plan


def test_multi_product_claims_pass_when_each_fact_belongs_to_its_product():
    context, plan = _comparison_context_and_plan()

    reply = (
        "Alpha Chair costs 1000 EGP and has a 2 year warranty. "
        "Alpha Chair is in stock and has a mesh back. "
        "Beta Chair costs 2000 EGP and has a 5 year warranty. "
        "Beta Chair is out of stock and has a leather back."
    )

    ok, violations = ClaimVerifier.verify(reply, plan, context)

    assert ok is True, violations


@pytest.mark.parametrize(
    ("reply", "expected_violation"),
    [
        (
            "Alpha Chair costs 2000 EGP. Beta Chair costs 1000 EGP.",
            "PRICE_PRODUCT_MISMATCH",
        ),
        (
            "Alpha Chair has a 5 year warranty. Beta Chair has a 2 year warranty.",
            "WARRANTY_PRODUCT_MISMATCH",
        ),
        (
            "Alpha Chair is out of stock. Beta Chair is in stock.",
            "AVAILABILITY_PRODUCT_MISMATCH",
        ),
        (
            "Alpha Chair has a leather back. Beta Chair has a mesh back.",
            "SPEC_PRODUCT_MISMATCH",
        ),
        (
            "Alpha Chair has a 20% discount. Beta Chair has a 10% discount.",
            "DISCOUNT_PRODUCT_MISMATCH",
        ),
    ],
)
def test_multi_product_claims_reject_facts_swapped_between_products(reply, expected_violation):
    context, plan = _comparison_context_and_plan()

    ok, violations = ClaimVerifier.verify(reply, plan, context)

    assert ok is False
    assert expected_violation in violations


def test_citing_product_b_does_not_authorize_product_a_price_for_it():
    context, plan = _comparison_context_and_plan()
    fact_ids_used = ["product-beta-chair", "price-alpha-chair"]

    ok, violations = ClaimVerifier.verify(
        "Beta Chair costs 1000 EGP.",
        plan,
        context,
        fact_ids_used=fact_ids_used,
    )

    assert ok is False
    assert "PRICE_PRODUCT_MISMATCH" in violations


def test_one_grouped_claim_must_be_true_for_every_named_product():
    context, plan = _comparison_context_and_plan()

    ok, violations = ClaimVerifier.verify(
        "Alpha Chair and Beta Chair are in stock.",
        plan,
        context,
    )

    assert ok is False
    assert "AVAILABILITY_PRODUCT_MISMATCH" in violations


def test_shipping_fee_cannot_be_reused_as_a_product_price():
    context, plan = _comparison_context_and_plan()
    plan.allowed_facts.append(_fact("shipping-fee", "delivery", "50 EGP"))

    price_ok, price_violations = ClaimVerifier.verify(
        "Alpha Chair costs 50 EGP.",
        plan,
        context,
    )
    shipping_ok, shipping_violations = ClaimVerifier.verify(
        "Shipping costs 50 EGP.",
        plan,
        context,
    )

    assert price_ok is False
    assert "PRICE_PRODUCT_MISMATCH" in price_violations
    assert shipping_ok is True, shipping_violations


def test_unrelated_policy_number_cannot_be_reused_as_product_warranty():
    context, plan = _comparison_context_and_plan()
    plan.allowed_facts.append(_fact("returns-policy", "policy", "Returns are allowed within 7 days"))

    ok, violations = ClaimVerifier.verify(
        "Alpha Chair has a 7 year warranty.",
        plan,
        context,
    )

    assert ok is False
    assert "WARRANTY_PRODUCT_MISMATCH" in violations
