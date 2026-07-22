import json

import pytest

from database import Company, CompanyKnowledge, Lead, LeadEvidence, Message, hash_api_key, save_message
from services.evidence_engine import extract_evidence_from_text
from services.product_context_service import (
    ProductContext,
    estimate_deal_value,
    get_company_products,
    get_price_for_product,
    match_product_mentions,
    normalize_products_data,
    resolve_conversational_product_context,
    resolve_runtime_product_context,
)


class _FailingCompletions:
    async def create(self, *args, **kwargs):
        raise RuntimeError("simulated provider outage")


class _FailingChat:
    completions = _FailingCompletions()


class _FailingGroq:
    chat = _FailingChat()


def _seed_company(db, company_id="product_context_co", products_data="[]"):
    company = Company(
        company_id=company_id,
        company_name="Product Context Company",
        email=f"{company_id}@example.com",
        password="hashed",
        api_key_hash=hash_api_key(f"{company_id}-api-key"),
        plan="PRO",
    )
    db.add(company)
    db.add(
        CompanyKnowledge(
            company_id=company_id,
            system_prompt="You are a sales assistant.",
            products_data=products_data,
            knowledge_base="Demo Product costs 9999 EGP in this free text only.",
        )
    )
    db.commit()
    return company


def _metadata(row):
    return json.loads(row.metadata_json or "{}")


def test_normalizes_structured_products_data_with_numeric_price():
    products = normalize_products_data(
        json.dumps(
            [
                {"name": "Demo Product", "price": "1,200 EGP", "aliases": ["DP"]},
                {"service": "Setup Call", "price": 300, "currency": "EGP"},
            ]
        )
    )

    assert [product.name for product in products] == ["Demo Product", "Setup Call"]
    assert products[0].aliases == ["DP"]
    assert products[0].price == 1200.0
    assert products[0].currency == "EGP"
    assert products[0].source == "products_data"
    assert products[0].confidence == 1.0
    assert products[0].missing_data == []


def test_invalid_price_remains_unknown():
    products = normalize_products_data(json.dumps([{"name": "Demo Product", "price": "call us"}]))

    assert products[0].price is None
    assert get_price_for_product(products[0]) == {
        "price": None,
        "currency": None,
        "missing_data": ["price"],
        "source": "products_data",
    }


def test_product_matching_works_only_for_known_product_names():
    products = normalize_products_data(json.dumps([{"name": "Demo Product"}, {"name": "Pro"}]))

    assert [product.name for product in match_product_mentions("Is Demo Product available?", products)] == ["Demo Product"]
    assert match_product_mentions("Is Mystery Product available?", products) == []
    assert match_product_mentions("I have a problem to solve.", products) == []


def test_unknown_product_text_does_not_become_verified_product_evidence():
    products = normalize_products_data(json.dumps([{"name": "Demo Product"}]))

    evidence = extract_evidence_from_text("Is Mystery Product available?", product_names=products)

    assert "buying_signal" in {item.evidence_type for item in evidence}
    assert "product_mention" not in {item.evidence_type for item in evidence}


def test_deal_value_is_unknown_when_quantity_is_missing():
    product = ProductContext(name="Demo Product", price=500.0, currency="EGP")

    estimate = estimate_deal_value(product, quantity=None)

    assert estimate["value"] is None
    assert estimate["currency"] == "EGP"
    assert estimate["missing_data"] == ["quantity"]


def test_deal_value_is_calculated_only_with_known_price_and_quantity():
    known = ProductContext(name="Demo Product", price=500.0, currency="EGP")
    unknown_price = ProductContext(name="Setup Call")

    assert estimate_deal_value(known, quantity=3) == {
        "value": 1500.0,
        "currency": "EGP",
        "missing_data": [],
        "source": "products_data",
    }

    missing_price = estimate_deal_value(unknown_price, quantity=3)
    assert missing_price["value"] is None
    assert missing_price["missing_data"] == ["price"]


def test_currency_handling_is_explicit_or_marked_missing():
    explicit = normalize_products_data(json.dumps([{"name": "Demo Product", "price": 500, "currency": "egp"}]))[0]
    missing = normalize_products_data(json.dumps([{"name": "Setup Call", "price": 300}]))[0]

    assert explicit.currency == "EGP"
    assert explicit.missing_data == []
    assert missing.currency is None
    assert get_price_for_product(missing)["missing_data"] == ["currency"]


def test_get_company_products_ignores_free_text_knowledge_base(db):
    company = _seed_company(db, company_id="product_context_free_text", products_data="[]")

    products = get_company_products(db, company.company_id)

    assert products == []


def test_evidence_product_mention_includes_known_product_context(db):
    company = _seed_company(
        db,
        company_id="product_context_evidence",
        products_data=json.dumps([{"name": "Demo Product", "aliases": ["DP"], "price": 500, "currency": "EGP"}]),
    )
    save_message(
        db,
        company.company_id,
        "201001112223@s.whatsapp.net",
        "user",
        "Is DP available?",
        "msg-product-context-evidence",
        "incoming",
    )

    evidence = db.query(LeadEvidence).filter(LeadEvidence.message_internal_id == "msg-product-context-evidence").all()
    product_evidence = [row for row in evidence if row.evidence_type == "product_mention"]

    assert len(product_evidence) == 1
    assert product_evidence[0].source_text == "DP"
    assert product_evidence[0].normalized_value == "Demo Product"
    assert _metadata(product_evidence[0])["known_price"] == 500.0
    assert _metadata(product_evidence[0])["currency"] == "EGP"


def test_chat_behavior_still_persists_evidence_with_product_context(client, db, monkeypatch):
    import brain
    import engine.analyzer as analyzer
    import engine.memory as memory

    company = _seed_company(
        db,
        company_id="product_context_chat",
        products_data=json.dumps([{"name": "Demo Product", "price": 500, "currency": "EGP"}]),
    )
    monkeypatch.setattr(brain, "groq_client", _FailingGroq())
    monkeypatch.setattr(analyzer, "should_trigger_analysis", lambda *args, **kwargs: False)
    monkeypatch.setattr(memory, "rebuild_lead_memory_task", lambda *args, **kwargs: None)

    response = client.post(
        "/chat",
        json={"message": "What is the price for Demo Product?", "user_id": "201001112223@s.whatsapp.net", "external_message_id": "wamid.product-context-chat-1"},
        headers={"X-Internal-Secret": "secret", "X-Company-ID": company.company_id},
    )

    assert response.status_code == 200
    assert response.json()["reply"]

    incoming = db.query(Message).filter(Message.company_id == company.company_id, Message.direction == "incoming").one()
    evidence_types = {row.evidence_type for row in db.query(LeadEvidence).filter(LeadEvidence.message_internal_id == incoming.internal_message_id).all()}
    lead = db.query(Lead).filter(Lead.company_id == company.company_id).one()

    assert evidence_types == {"price_question", "product_mention"}
    assert lead.opportunity_value is None


def test_product_context_does_not_use_default_opportunity_value():
    product_without_price = ProductContext(name="Demo Product")

    estimate = estimate_deal_value(product_without_price, quantity=None)

    assert estimate["value"] is None
    assert estimate["missing_data"] == ["price", "quantity"]


def _arvena_catalog():
    return normalize_products_data(
        json.dumps(
            [
                {"name": "Arvena Ergo One", "aliases": ["Ergo One"], "category": "Office Chairs", "price": 6900, "currency": "EGP"},
                {"name": "Arvena Ergo Pro", "aliases": ["Ergo Pro"], "category": "Office Chairs", "price": 10900, "currency": "EGP"},
                {"name": "FocusDesk 120", "category": "Office Desks", "price": 8500, "currency": "EGP"},
                {"name": "CleanCable Kit", "category": "Accessories", "price": 700, "currency": "EGP"},
            ]
        )
    )


def test_category_resolution_is_precise_for_arabic_variants():
    products = _arvena_catalog()

    chairs = resolve_runtime_product_context("\u0639\u0646\u062f\u0643\u0645 \u0643\u0631\u0627\u0633\u064a \u0645\u0643\u062a\u0628\u064a\u0629\u061f", products)
    desks = resolve_runtime_product_context("\u0639\u0646\u062f\u0643\u0645 \u0645\u0643\u0627\u062a\u0628\u061f", products)
    accessories = resolve_runtime_product_context("\u0639\u0646\u062f\u0643\u0645 \u0627\u0643\u0633\u0633\u0648\u0627\u0631\u0627\u062a\u061f", products)

    assert [item["name"] for item in chairs["resolved_products"]] == ["Arvena Ergo One", "Arvena Ergo Pro"]
    assert [item["name"] for item in desks["resolved_products"]] == ["FocusDesk 120"]
    assert [item["name"] for item in accessories["resolved_products"]] == ["CleanCable Kit"]


def test_conversational_resolver_uses_unique_price_and_prior_order_without_guessing():
    products = _arvena_catalog()
    history = [{"role": "assistant", "content": "Arvena Ergo One: 6900 EGP\nArvena Ergo Pro: 10900 EGP"}]

    price_reference = resolve_conversational_product_context("\u0639\u0627\u064a\u0632 \u0627\u0644\u0644\u064a \u0628\u06406900 \u062f\u0647", products, history)
    first_reference = resolve_conversational_product_context("\u0627\u0644\u062e\u064a\u0627\u0631 \u0627\u0644\u0627\u0648\u0644", products, history)
    pro_reference = resolve_conversational_product_context("\u0637\u0628 \u0627\u0644\u0640 Pro \u0628\u0643\u0627\u0645\u061f", products, history)

    assert price_reference["resolution_reason"] == "unique_price_reference"
    assert [item["name"] for item in price_reference["resolved_products"]] == ["Arvena Ergo One"]
    assert [item["name"] for item in first_reference["resolved_products"]] == ["Arvena Ergo One"]
    assert [item["name"] for item in pro_reference["resolved_products"]] == ["Arvena Ergo Pro"]

    ambiguous_products = _arvena_catalog()
    ambiguous_products[1] = ProductContext(name="Arvena Ergo Pro", aliases=["Ergo Pro"], category="Office Chairs", price=6900, currency="EGP")
    ambiguous = resolve_conversational_product_context("\u0639\u0627\u064a\u0632 \u0627\u0644\u0644\u064a \u0628\u06406900", ambiguous_products, history)
    assert ambiguous["status"] == "ambiguous"


def test_price_objection_does_not_fall_into_catalog_price_fast_path():
    import brain

    products = _arvena_catalog()
    context = resolve_runtime_product_context("10900 \u063a\u0627\u0644\u064a \u062c\u062f\u064b\u0627", products)

    assert brain._direct_catalog_payload(
        "10900 \u063a\u0627\u0644\u064a \u062c\u062f\u064b\u0627",
        context,
        products,
        {"history": []},
        {"company_name": "ARVENA"},
        resolve_runtime_product_context,
    ) is None

    fallback = brain._heuristic_ai_payload("10900 \u063a\u0627\u0644\u064a \u062c\u062f\u064b\u0627", {}, {"company_name": "ARVENA"})
    assert "\u0627\u0644\u0633\u0639\u0631 \u0645\u0631\u062a\u0641\u0639" in fallback["reply"]
    assert "\u0645\u0634 \u0647\u0641\u062a\u0631\u0636" in fallback["reply"]


@pytest.mark.parametrize(
    "message",
    [
        "\u0623\u0646\u0627 \u0622\u062e\u0631\u064a 7000",
        "\u0645\u064a\u0632\u0627\u0646\u064a\u062a\u064a 7000",
        "\u0645\u0639\u0627\u064a\u0627 7000",
        "\u0645\u0634 \u0647\u0642\u062f\u0631 \u0623\u0639\u062f\u064a 7000",
        "\u0639\u0627\u064a\u0632 \u062d\u0627\u062c\u0629 \u0623\u0642\u0644 \u0645\u0646 7000",
    ],
)
def test_max_budget_language_does_not_enter_direct_catalog_shortcut(message):
    import brain

    products = _arvena_catalog()
    context = resolve_runtime_product_context(message, products)

    assert brain._direct_catalog_payload(
        message,
        context,
        products,
        {"history": []},
        {"company_name": "ARVENA"},
        resolve_runtime_product_context,
    ) is None


def test_open_work_need_fallback_asks_one_useful_question_not_for_a_phone():
    import brain

    fallback = brain._heuristic_ai_payload("\u0639\u0627\u064a\u0632 \u0643\u0631\u0633\u064a \u0643\u0648\u064a\u0633 \u0644\u0644\u0634\u063a\u0644", {}, {"company_name": "ARVENA"})

    assert "\u0631\u0627\u062d\u0629 \u0627\u0644\u0638\u0647\u0631" in fallback["reply"]
    assert "\u0631\u0642\u0645 \u0645\u0648\u0628\u0627\u064a\u0644" not in fallback["reply"]
