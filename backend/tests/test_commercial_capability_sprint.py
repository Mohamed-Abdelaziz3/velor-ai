import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from jose import jwt

from database import (
    CommercialDecisionLineage,
    CommercialEvent,
    Company,
    CompanyKnowledge,
    Lead,
    Message,
    SystemEvent,
    hash_api_key,
)
from services.commercial_intelligence_service import (
    CommercialEventType,
    CommercialNextMove,
    CommercialObjective,
    ObservedOutcome,
    SellingStrategy,
    answer_business_question,
    build_business_commercial_intelligence,
    derive_commercial_event_specs,
    persist_commercial_turn,
)
from services.next_best_action_service import evaluate_next_best_action
from services.sales_state_service import BuyerIntent, PrimarySalesState, SalesStateSnapshot
from services.commercial_authority_service import get_canonical_commercial_view


@pytest.fixture
def commercial_company(db):
    suffix = uuid.uuid4().hex[:8]
    company_id = f"commercial_{suffix}"
    company = Company(
        company_id=company_id,
        company_name="VELOR Commercial Proof",
        email=f"{company_id}@example.com",
        password="hashed",
        api_key_hash=hash_api_key(f"{company_id}-key"),
    )
    db.add(company)
    db.add(
        CompanyKnowledge(
            company_id=company_id,
            system_prompt="Use catalog truth only.",
            products_data=json.dumps(
                [
                    {"name": "Arvena Ergo One", "aliases": ["Ergo One", "One"], "price": 6900, "currency": "EGP", "category": "chairs"},
                    {"name": "Arvena Ergo Pro", "aliases": ["Ergo Pro", "Pro"], "price": 10900, "currency": "EGP", "category": "chairs"},
                    {"name": "Arvena Ergo Lite", "aliases": ["Ergo Lite", "Lite"], "price": 5400, "currency": "EGP", "category": "chairs"},
                ],
                ensure_ascii=False,
            ),
            knowledge_base="No shipping policy is currently supplied.",
        )
    )
    db.commit()
    return company_id


def _snapshot(company_id, state, intents=None):
    return SalesStateSnapshot(
        company_id=company_id,
        lead_id=1,
        conversation_id="proof",
        primary_state=state,
        buyer_intents=intents or [],
        intent_strength="MEDIUM",
        confidence=0.9,
        momentum="STABLE",
    )


def test_need_discovery_has_explicit_objective_strategy_and_move(db, commercial_company):
    decision = evaluate_next_best_action(
        db,
        commercial_company,
        None,
        _snapshot(commercial_company, PrimarySalesState.NEED_DISCOVERY.value),
        "عايز كرسي كويس للشغل",
        recommendation_decision=SimpleNamespace(outcome="ASK_CLARIFYING_QUESTION", recommended_products=[]),
    )
    assert decision.commercial_objective == CommercialObjective.DISCOVER_NEED.value
    assert decision.selling_strategy == SellingStrategy.DISCOVER_NEED.value
    assert decision.next_move == CommercialNextMove.ASK_ONE_USE_CASE_QUESTION.value


def test_price_objection_chooses_uncertainty_resolving_move(db, commercial_company):
    objection = SimpleNamespace(objection_present=True, primary_objection="PRICE_TOO_HIGH")
    decision = evaluate_next_best_action(
        db,
        commercial_company,
        None,
        _snapshot(commercial_company, PrimarySalesState.OBJECTING.value, [BuyerIntent.PRICE_OBJECTION.value]),
        "10900 غالي جدًا",
        objection_snapshot=objection,
        recommendation_decision=SimpleNamespace(outcome="INSUFFICIENT_INFORMATION", recommended_products=[]),
    )
    assert decision.commercial_objective == CommercialObjective.QUALIFY_CONSTRAINT.value
    assert decision.selling_strategy == SellingStrategy.CLARIFY_CRITERION.value
    assert decision.next_move == CommercialNextMove.ASK_BUDGET_OR_VALUE_CLARIFIER.value
    assert "سببه غير مثبت" in decision.owner_explanation


def test_known_need_price_objection_reanchors_only_to_explicit_fit(db, commercial_company):
    recommendation = SimpleNamespace(
        outcome="RECOMMEND_ONE",
        recommended_products=[SimpleNamespace(product_name="Arvena Ergo Pro")],
    )
    decision = evaluate_next_best_action(
        db,
        commercial_company,
        None,
        _snapshot(commercial_company, PrimarySalesState.OBJECTING.value, [BuyerIntent.PRICE_OBJECTION.value]),
        "للشغل ساعات طويلة بس السعر غالي",
        objection_snapshot=SimpleNamespace(objection_present=True, primary_objection="PRICE_TOO_HIGH"),
        recommendation_decision=recommendation,
    )
    assert decision.selling_strategy == SellingStrategy.REANCHOR_VALUE.value
    assert decision.next_move == CommercialNextMove.REANCHOR_TO_EXPLICIT_NEED.value


def test_hard_budget_filters_expensive_product_before_ranking(db, commercial_company):
    decision = evaluate_next_best_action(
        db,
        commercial_company,
        None,
        _snapshot(commercial_company, PrimarySalesState.OBJECTING.value, [BuyerIntent.PRICE_OBJECTION.value]),
        "أنا آخري 7000",
    )
    assert decision.selling_strategy == SellingStrategy.OFFER_TRUSTED_ALTERNATIVE.value
    eligible = next(item["value"] for item in decision.decision_evidence if item["type"] == "eligible_trusted_products")
    assert {item["name"] for item in eligible} == {"Arvena Ergo One", "Arvena Ergo Lite"}
    assert all(item["price"] <= 7000 for item in eligible)
    assert "Arvena Ergo Pro" not in {item["name"] for item in eligible}


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
def test_hard_budget_language_variants_override_numeric_catalog_lookup(db, commercial_company, message):
    decision = evaluate_next_best_action(
        db,
        commercial_company,
        None,
        _snapshot(commercial_company, PrimarySalesState.OBJECTING.value, [BuyerIntent.PRICE_OBJECTION.value]),
        message,
    )

    assert decision.selling_strategy == SellingStrategy.OFFER_TRUSTED_ALTERNATIVE.value
    eligible = next(item["value"] for item in decision.decision_evidence if item["type"] == "eligible_trusted_products")
    assert eligible
    assert all(item["price"] <= 7000 for item in eligible)
    assert "Arvena Ergo Pro" not in {item["name"] for item in eligible}


def test_unknown_quantity_discount_escalates_without_promise(db, commercial_company):
    decision = evaluate_next_best_action(
        db,
        commercial_company,
        None,
        _snapshot(commercial_company, PrimarySalesState.NEGOTIATING.value, [BuyerIntent.NEGOTIATION.value]),
        "غالي شوية، فيه خصم لو اشتريت 2؟",
    )
    assert decision.escalation_required is True
    assert decision.selling_strategy == SellingStrategy.COMMERCIAL_EXCEPTION_ESCALATION.value
    assert decision.escalation["unknown"]
    assert "OFFER_UNTRUSTED_DISCOUNT" in decision.prohibited_actions


def test_soft_stall_uses_do_not_push(db, commercial_company):
    decision = evaluate_next_best_action(
        db,
        commercial_company,
        None,
        _snapshot(commercial_company, PrimarySalesState.STALLED.value),
        "تمام هفكر",
    )
    assert decision.selling_strategy == SellingStrategy.DO_NOT_PUSH.value
    assert decision.next_move == CommercialNextMove.ACKNOWLEDGE_WITHOUT_PRESSURE.value
    assert decision.question_policy == "NO_QUESTION"
    assert decision.cta_policy == "NONE"


def test_purchase_advancement_stops_selling_and_facilitates(db, commercial_company):
    decision = evaluate_next_best_action(
        db,
        commercial_company,
        None,
        _snapshot(commercial_company, PrimarySalesState.COMMITTING.value, [BuyerIntent.PURCHASE_COMMITMENT.value]),
        "تمام آخده، أعمل إيه؟",
    )
    assert decision.commercial_objective == CommercialObjective.COMPLETE_PURCHASE_STEP.value
    assert decision.selling_strategy == SellingStrategy.FACILITATE_PURCHASE.value
    assert "RESET_PURCHASE_TO_DISCOVERY" in decision.prohibited_actions


def test_returning_cheaper_request_uses_persisted_product_context(db, commercial_company):
    lead = Lead(company_id=commercial_company, name="Returning", phone=f"01{uuid.uuid4().int % 10**9:09d}")
    db.add(lead)
    db.flush()
    db.add(
        CommercialEvent(
            company_id=commercial_company,
            lead_id=lead.id,
            source_message_internal_id=f"prior-{uuid.uuid4().hex}",
            channel="VELOR_WEB_CHAT",
            event_type="PRODUCT_ASKED_ABOUT",
            product_ref="Arvena Ergo Pro",
            stage="INQUIRY",
            source_text="سألت عن Ergo Pro",
            evidence_json="{}",
            provenance="test",
            event_hash=hashlib.sha256(uuid.uuid4().bytes).hexdigest(),
        )
    )
    db.commit()
    decision = evaluate_next_best_action(
        db,
        commercial_company,
        lead.id,
        _snapshot(commercial_company, PrimarySalesState.EVALUATING.value),
        "عايز حاجة زي اللي سألتك عليها بس أرخص",
    )
    assert decision.selling_strategy == SellingStrategy.OFFER_TRUSTED_ALTERNATIVE.value
    previous = next(item["value"] for item in decision.decision_evidence if item["type"] == "prior_product_context")
    assert previous == ["Arvena Ergo Pro"]


def test_event_derivation_never_treats_commitment_as_order_or_paid(db, commercial_company):
    lead = Lead(company_id=commercial_company, name="Attribution", phone=f"01{uuid.uuid4().int % 10**9:09d}")
    db.add(lead)
    db.commit()
    snapshot = _snapshot(commercial_company, PrimarySalesState.COMMITTING.value, [BuyerIntent.PURCHASE_COMMITMENT.value])
    decision = evaluate_next_best_action(db, commercial_company, lead.id, snapshot, "هاخد Ergo One، أعمل إيه؟")
    specs = derive_commercial_event_specs(db, commercial_company, lead.id, "هاخد Ergo One، أعمل إيه؟", "نكمل الطلب", decision, snapshot)
    types = {item["event_type"] for item in specs}
    assert CommercialEventType.PRODUCT_SELECTED.value in types
    assert CommercialEventType.PURCHASE_COMMITMENT.value in types
    assert CommercialEventType.PURCHASE_EXECUTION_REQUEST.value in types
    assert CommercialEventType.CONFIRMED_ORDER.value not in types
    assert CommercialEventType.PAID.value not in types


def test_event_derivation_ignores_fabricated_assistant_output(db, commercial_company):
    lead = Lead(company_id=commercial_company, name="Fabrication", phone=f"01{uuid.uuid4().int % 10**9:09d}")
    db.add(lead)
    db.commit()
    snapshot = _snapshot(commercial_company, PrimarySalesState.COMMITTING.value, [BuyerIntent.PURCHASE_COMMITMENT.value])
    decision = evaluate_next_best_action(db, commercial_company, lead.id, snapshot, "hello")

    specs = derive_commercial_event_specs(
        db,
        commercial_company,
        lead.id,
        "hello",
        "The customer selected Ergo Pro and their budget is 15000 EGP.",
        decision,
        snapshot,
    )

    assert specs == []


def test_canonical_product_reference_uses_trusted_catalog_price(db, commercial_company):
    from database import LeadEvidence

    lead = Lead(
        company_id=commercial_company,
        name="Price authority",
        channel_type="VELOR_WEB_CHAT",
        external_customer_id="price-authority-visitor",
    )
    message = Message(
        company_id=commercial_company,
        user_id="price-authority-visitor",
        internal_message_id=f"in-{uuid.uuid4().hex}",
        sender="user",
        direction="incoming",
        message="I am considering Ergo One",
    )
    db.add_all([lead, message])
    db.flush()
    db.add(
        LeadEvidence(
            company_id=commercial_company,
            lead_id=lead.id,
            message_internal_id=message.internal_message_id,
            evidence_type="product_interest",
            source_text=message.message,
            normalized_value="Arvena Ergo One",
            evidence_hash=uuid.uuid4().hex,
        )
    )
    db.commit()

    reference = get_canonical_commercial_view(db, commercial_company, lead.id)["canonical_commercial"]["product_references"][0]
    assert reference["trusted_price"] == {
        "amount": 6900,
        "currency": "EGP",
        "truth_class": "OBSERVED",
        "source_type": "COMPANY_KNOWLEDGE",
    }


def test_strategy_move_and_later_outcome_are_persisted_without_causal_claim(db, commercial_company):
    lead = Lead(company_id=commercial_company, name="Lineage", phone=f"01{uuid.uuid4().int % 10**9:09d}", channel_type="VELOR_WEB_CHAT")
    db.add(lead)
    db.flush()
    first_message = Message(internal_message_id=f"in-{uuid.uuid4().hex}", company_id=commercial_company, user_id="lineage", sender="user", direction="incoming", message="10900 غالي", delivery_status="received")
    second_message = Message(internal_message_id=f"in-{uuid.uuid4().hex}", company_id=commercial_company, user_id="lineage", sender="user", direction="incoming", message="أنا آخري 7000", delivery_status="received")
    db.add_all([first_message, second_message])
    db.commit()

    first_snapshot = _snapshot(commercial_company, PrimarySalesState.OBJECTING.value, [BuyerIntent.PRICE_OBJECTION.value])
    first_decision = evaluate_next_best_action(db, commercial_company, lead.id, first_snapshot, first_message.message)
    persist_commercial_turn(commercial_company, lead.id, "VELOR_WEB_CHAT", first_message.internal_message_id, None, first_message.message, "ما هو سقف الميزانية؟", first_decision, first_snapshot)

    second_snapshot = _snapshot(commercial_company, PrimarySalesState.OBJECTING.value, [BuyerIntent.PRICE_OBJECTION.value])
    second_decision = evaluate_next_best_action(db, commercial_company, lead.id, second_snapshot, second_message.message)
    persist_commercial_turn(commercial_company, lead.id, "VELOR_WEB_CHAT", second_message.internal_message_id, None, second_message.message, "أرشح بديلًا داخل الميزانية", second_decision, second_snapshot)

    db.expire_all()
    first_lineage = db.query(CommercialDecisionLineage).filter(CommercialDecisionLineage.source_message_internal_id == first_message.internal_message_id).one()
    assert first_lineage.observed_outcome == ObservedOutcome.CUSTOMER_PROVIDED_MISSING_INFORMATION.value
    assert json.loads(first_lineage.outcome_evidence_json)[-1] == {"type": "causality", "value": "not_claimed"}
    invalidation = db.query(SystemEvent).filter(
        SystemEvent.company_id == commercial_company,
        SystemEvent.event_type == "canonical_commercial.updated",
        SystemEvent.entity_id == str(lead.id),
    ).all()
    assert len(invalidation) == 2
    payloads = [json.loads(item.payload) for item in invalidation]
    assert {item["source_message_internal_id"] for item in payloads} == {
        first_message.internal_message_id,
        second_message.internal_message_id,
    }
    assert all(set(item) == {"company_id", "lead_id", "source_message_internal_id"} for item in payloads)


def _stage(event_type):
    return {
        "PRODUCT_ASKED_ABOUT": "INQUIRY",
        "PRODUCT_CONSIDERED": "NEED_FIT",
        "PRICE_REVEALED": "PRICE",
        "PRODUCT_COMPARED": "COMPARISON",
        "OBJECTION_EXPRESSED": "OBJECTION",
        "PRODUCT_SELECTED": "SELECTION",
        "PURCHASE_INTENT_EXPRESSED": "PURCHASE_INTENT",
        "PURCHASE_COMMITMENT": "COMMITMENT",
        "PURCHASE_EXECUTION_REQUEST": "EXECUTION",
        "KNOWLEDGE_GAP_HIT": "EVALUATING",
        "OWNER_INTERVENTION_REQUIRED": "READY_TO_BUY",
        "WAITING_ON_US": "READY_TO_BUY",
    }.get(event_type, "UNKNOWN")


def _seed_business_fixture(db, company_id):
    fixture = json.loads((Path(__file__).parent / "fixtures" / "commercial_intelligence_scenarios.json").read_text(encoding="utf-8"))
    assert fixture["provenance"] == "trusted_commercial_intelligence_test_fixture"
    for conversation in fixture["conversations"]:
        lead = Lead(
            company_id=company_id,
            name=conversation["key"],
            phone=f"01{uuid.uuid4().int % 10**9:09d}",
            # Unit-test fixtures model eligible merchant conversations. A
            # separate regression below proves application-level test leads
            # are excluded from intelligence.
            is_test=False,
            channel_type="VELOR_WEB_CHAT",
            external_customer_id=f"fixture_{conversation['key']}",
        )
        db.add(lead)
        db.flush()
        for index, event_type in enumerate(conversation["events"]):
            source_id = f"fixture:{conversation['key']}:{event_type}:{index}"
            detail = {}
            if conversation.get("knowledge_topic"):
                detail["knowledge_topic"] = conversation["knowledge_topic"]
            db.add(
                CommercialEvent(
                    company_id=company_id,
                    lead_id=lead.id,
                    source_message_internal_id=source_id,
                    channel="VELOR_WEB_CHAT",
                    event_type=event_type,
                    product_ref=conversation.get("product"),
                    stage=_stage(event_type),
                    objection_type=conversation.get("objection") if event_type == "OBJECTION_EXPRESSED" else None,
                    source_text=f"Synthetic proof: {conversation['key']} -> {event_type}",
                    evidence_json=json.dumps(detail),
                    provenance=fixture["provenance"],
                    event_hash=hashlib.sha256(f"{company_id}|{source_id}".encode()).hexdigest(),
                    observed_at=datetime.now(timezone.utc),
                )
            )
    db.commit()


def test_business_aggregation_proves_demand_progression_leakage_and_safety(db, commercial_company):
    _seed_business_fixture(db, commercial_company)
    data = build_business_commercial_intelligence(db, commercial_company)
    by_name = {item["product"]: item for item in data["products"]}

    assert data["summary"]["most_discussed_product"] == "Arvena Ergo Pro"
    assert by_name["Arvena Ergo Pro"]["classification"] == "LEAKAGE_CANDIDATE"
    assert by_name["Arvena Ergo One"]["classification"] == "STRONG_PERFORMER"
    assert by_name["Arvena Ergo Lite"]["classification"] == "HIDDEN_WINNER"
    assert by_name["Arvena Ergo Pro"]["stage_counts"]["PRICE"] == 5
    assert by_name["Arvena Ergo Pro"]["stage_counts"]["PURCHASE_INTENT"] == 1
    assert any(item["type"] == "OBJECTION_CONCENTRATION" and item["product"] == "Arvena Ergo Pro" for item in data["insights"])
    assert any(item["type"] == "KNOWLEDGE_GAP" for item in data["insights"])
    # Historical WAITING_ON_US events are evidence about the period, not proof
    # that the customer is still waiting now. Current owner attention is derived
    # from the latest conversation turn and is covered by the actionable tests.
    assert not any(item["type"] == "OWNER_RESPONSE_LEAKAGE" for item in data["insights"])
    assert data["summary"]["waiting_on_us"] == 0
    assert data["summary"]["confirmed_orders"] is None
    assert data["summary"]["paid_outcomes"] is None
    assert data["summary"]["paid_conversations"] is None
    assert data["summary"]["outcome_coverage"] == {"orders": "not_connected", "payments": "not_connected"}
    assert "conversion" not in json.dumps(data).casefold()


def test_small_sample_stays_insufficient(db, commercial_company):
    lead = Lead(company_id=commercial_company, name="Tiny", phone=f"01{uuid.uuid4().int % 10**9:09d}")
    db.add(lead)
    db.flush()
    db.add(
        CommercialEvent(
            company_id=commercial_company,
            lead_id=lead.id,
            source_message_internal_id=f"tiny-{uuid.uuid4().hex}",
            channel="VELOR_WEB_CHAT",
            event_type="PRODUCT_ASKED_ABOUT",
            product_ref="Tiny Product",
            stage="INQUIRY",
            source_text="tiny",
            evidence_json="{}",
            provenance="test",
            event_hash=hashlib.sha256(uuid.uuid4().bytes).hexdigest(),
            observed_at=datetime.now(timezone.utc),
        )
    )
    db.commit()
    data = build_business_commercial_intelligence(db, commercial_company)
    tiny = next(item for item in data["products"] if item["product"] == "Tiny Product")
    assert tiny["classification"] == "INSUFFICIENT_EVIDENCE"


def test_business_intelligence_excludes_events_from_test_leads(db, commercial_company):
    real_lead = Lead(
        company_id=commercial_company,
        name="Eligible customer",
        phone=f"01{uuid.uuid4().int % 10**9:09d}",
        is_test=False,
    )
    test_lead = Lead(
        company_id=commercial_company,
        name="Synthetic customer",
        phone=f"01{uuid.uuid4().int % 10**9:09d}",
        is_test=True,
    )
    db.add_all([real_lead, test_lead])
    db.flush()
    for lead, product in ((real_lead, "Eligible Product"), (test_lead, "Synthetic Product")):
        source_id = f"truth-exclusion-{uuid.uuid4().hex}"
        db.add(
            CommercialEvent(
                company_id=commercial_company,
                lead_id=lead.id,
                source_message_internal_id=source_id,
                channel="VELOR_WEB_CHAT",
                event_type=CommercialEventType.PRODUCT_ASKED_ABOUT.value,
                product_ref=product,
                stage="INQUIRY",
                source_text=product,
                evidence_json="{}",
                provenance="truth_exclusion_test",
                event_hash=hashlib.sha256(source_id.encode()).hexdigest(),
                observed_at=datetime.now(timezone.utc),
            )
        )
    db.commit()

    data = build_business_commercial_intelligence(db, commercial_company)
    serialized = json.dumps(data, ensure_ascii=False)

    assert data["summary"]["source_conversations"] == 1
    assert data["summary"]["commercial_events"] == 1
    assert "Eligible Product" in serialized
    assert "Synthetic Product" not in serialized
    assert "Synthetic customer" not in serialized


@pytest.mark.asyncio
async def test_business_ask_velor_is_deterministic_and_grounded(db, commercial_company):
    _seed_business_fixture(db, commercial_company)
    payload = answer_business_question(db, commercial_company, "ليه Ergo Pro بيتسأل عليه كتير ومش بيتقدم؟")
    assert payload["llm_used"] is False
    assert payload["grounding"] == "deterministic_commercial_events"
    assert "ليست نسبة تحويل" in payload["answer"]
    assert payload["business_intelligence"]["insights"][0]["type"] == "LEAKAGE_CANDIDATE"


def _tenant_token(company_id):
    return jwt.encode(
        {"company_id": company_id, "role": "tenant", "token_type": "access"},
        "super-secret-test-key-32-chars-long",
        algorithm="HS256",
    )


def test_business_intelligence_owner_api_uses_deterministic_contract(client, db, commercial_company):
    _seed_business_fixture(db, commercial_company)
    response = client.get(
        "/api/v1/intelligence/business-insights",
        cookies={"access_token": _tenant_token(commercial_company)},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["data_source"] == "deterministic_commercial_events"
    assert data["insights"][0]["evidence"]
    assert {"observed", "hypothesis", "unknown", "recommendation", "experiment", "measure", "do_not_conclude"}.issubset(data["insights"][0])
    assert data["summary"]["confirmed_orders"] is None
    assert data["summary"]["paid_outcomes"] is None
    assert data["summary"]["paid_conversations"] is None


def test_customer_workspace_exposes_owner_readable_commercial_lineage(client, db, commercial_company):
    lead = Lead(company_id=commercial_company, name="Workspace Proof", phone=f"01{uuid.uuid4().int % 10**9:09d}")
    db.add(lead)
    db.flush()
    db.add(
        CommercialDecisionLineage(
            company_id=commercial_company,
            lead_id=lead.id,
            source_message_internal_id=f"workspace-{uuid.uuid4().hex}",
            objective="QUALIFY_CONSTRAINT",
            strategy="CLARIFY_CRITERION",
            next_move="ASK_BUDGET_OR_VALUE_CLARIFIER",
            decision_json=json.dumps({"owner_explanation": "سبب اعتراض السعر غير مثبت؛ نحتاج سؤالًا واحدًا."}, ensure_ascii=False),
            evidence_json=json.dumps([{"type": "current_customer_message", "value": "غالي"}], ensure_ascii=False),
            escalation_required=False,
        )
    )
    db.commit()
    response = client.get(
        f"/api/v1/crm/customers/{lead.id}",
        cookies={"access_token": _tenant_token(commercial_company)},
    )
    assert response.status_code == 200
    execution = response.json()["customer"]["commercial_execution"]
    assert execution["current"]["objective"] == "QUALIFY_CONSTRAINT"
    assert execution["current"]["owner_explanation"].startswith("سبب اعتراض السعر")
    assert "لا تثبت" in execution["note"]


def test_web_chat_turn_persists_commercial_decision_and_events(client, db, commercial_company, monkeypatch):
    import brain

    company = db.query(Company).filter(Company.company_id == commercial_company).one()
    company.is_web_chat_enabled = True
    company.public_chat_slug = f"commercial-{uuid.uuid4().hex[:8]}"
    db.commit()

    class FailingCompletions:
        async def create(self, *args, **kwargs):
            raise RuntimeError("proof provider outage")

    monkeypatch.setattr(brain.groq_client.chat, "completions", FailingCompletions())

    async def no_sleep(*args, **kwargs):
        return None

    monkeypatch.setattr(brain.asyncio, "sleep", no_sleep)
    session = client.post(f"/api/public/companies/{company.public_chat_slug}/session").json()
    response = client.post(
        "/api/public/chat",
        json={"message": "أنا آخري 7000", "client_message_id": str(uuid.uuid4())},
        headers={"Authorization": f"Bearer {session['token']}"},
    )
    assert response.status_code == 200
    lead = db.query(Lead).filter(Lead.company_id == commercial_company, Lead.external_customer_id == session["visitor_id"]).one()
    lineage = db.query(CommercialDecisionLineage).filter(CommercialDecisionLineage.lead_id == lead.id).one()
    assert lineage.strategy == "OFFER_TRUSTED_ALTERNATIVE"
    constraint = db.query(CommercialEvent).filter(CommercialEvent.lead_id == lead.id, CommercialEvent.event_type == "HARD_CONSTRAINT_STATED").one()
    assert json.loads(constraint.evidence_json)["constraint_value"] == 7000
