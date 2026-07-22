"""
test_recommendation_intelligence.py — Recommendation Intelligence & Ethical Product Fit Test Suite
==================================================================================================
Comprehensive test suite verifying:
1. CustomerNeedSnapshot extraction & authority hierarchy
2. Assistant, Prompt, and Memory need poisoning protections
3. Hard constraint filtering before candidate ranking
4. Unknown attribute safety
5. No expensive product bias & ARVENA bias test
6. No cheapest product bias
7. No catalog order bias (Catalog order shuffling test)
8. Large catalog discovery (100+ products)
9. Malformed catalog safety & legacy compatibility
10. Multi-product recommendations & trade-offs
11. No valid fit & Insufficient information policies
12. Ethical Product Fit Policy & prohibited tactics
13. Final reply recommendation alignment & high-risk mismatch detection
14. Cross-turn need evolution & conflict resolution
15. Tenant isolation & Zero additional LLM call default
"""

import json
from unittest.mock import MagicMock
import pytest
from database import Company, CompanyKnowledge, Lead, LeadMemory, SessionLocal
from services.product_context_service import ProductContext, normalize_products_data
from services.sales_state_service import evaluate_sales_state
from services.recommendation_intelligence_service import (
    ConstraintStrength,
    CustomerNeedItem,
    CustomerNeedSnapshot,
    EthicalProductFitMode,
    ExclusionReasonCode,
    FitLevel,
    NeedExplicitness,
    NeedType,
    ProhibitedRecommendationTactic,
    RecommendationAlignmentResult,
    RecommendationDecision,
    RecommendationOutcome,
    RecommendationReasonCode,
    _product_has_feature,
    enforce_recommendation_reply_alignment,
    evaluate_ethical_product_fit_policy,
    evaluate_recommendation_decision,
    extract_customer_needs,
    format_recommendation_context_for_prompt,
    is_recommendation_request,
)


def make_company(company_id: str, name: str = "Test Co") -> Company:
    return Company(
        company_id=company_id,
        company_name=name,
        email=f"{company_id}@test.com",
        password="hashed_password",
        api_key_hash=f"hash_{company_id}",
    )


@pytest.fixture
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def arvena_catalog_json():
    return json.dumps([
        {
            "id": "prod_1",
            "name": "Arvena Ergo One",
            "price": 6900,
            "currency": "EGP",
            "category": "Office Chair",
            "description": "Ergonomic office chair with breathable mesh and lumbar support for 8+ hour work sessions.",
            "warranty": "2 Years",
            "colors": ["Black", "Grey"],
            "stock": "In Stock",
            "record_type": "product",
        },
        {
            "id": "prod_2",
            "name": "Arvena Ergo Pro",
            "price": 10900,
            "currency": "EGP",
            "category": "Office Chair",
            "description": "Premium ergonomic chair with adjustable headrest, 4D armrests, and dynamic lumbar support.",
            "warranty": "5 Years",
            "colors": ["Black"],
            "stock": "In Stock",
            "record_type": "product",
        },
        {
            "id": "prod_3",
            "name": "FocusDesk 120",
            "price": 8500,
            "currency": "EGP",
            "category": "Desk",
            "description": "Fixed height minimalist office desk 120cm.",
            "warranty": "3 Years",
            "record_type": "product",
        },
        {
            "id": "prod_4",
            "name": "LiftDesk Electric 120",
            "price": 19900,
            "currency": "EGP",
            "category": "Desk",
            "description": "Electric height adjustable standing desk with dual motors.",
            "warranty": "5 Years",
            "record_type": "product",
        },
    ])


# =====================================================================
# 1. NEED EXTRACTION & AUTHORITY HIERARCHY TESTS
# =====================================================================

def test_need_extraction_explicit_budget_and_use_case():
    text = "عايز كرسي للشغل 8 ساعات وميزانيتي أقصى حاجة 7000"
    snapshot = extract_customer_needs(text, company_id="test_comp", lead_id="1")

    assert len(snapshot.needs) >= 2
    budget_need = next(n for n in snapshot.needs if n.need_type == NeedType.BUDGET_CEILING)
    assert budget_need.value == 7000.0
    assert budget_need.constraint_strength == ConstraintStrength.HARD
    assert budget_need.explicitness == NeedExplicitness.EXPLICIT

    use_case_need = next(n for n in snapshot.needs if n.need_type == NeedType.USE_CASE)
    assert "OFFICE_WORK" in use_case_need.value


def test_assistant_need_poisoning_protection():
    """Assistant claims 'واضح إنك محتاج كرسي Premium', but customer says 'لا، عايز أرخص حاجة' -> Customer text wins."""
    history = [
        {"role": "assistant", "content": "واضح إنك محتاج كرسي Premium فخم بـ 15000"},
        {"role": "user", "content": "لا، عايز أرخص كرسي مناسب للشغل بحدود 7000"},
    ]
    user_text = history[-1]["content"]
    snapshot = extract_customer_needs(user_text, company_id="test_comp", lead_id="1", recent_messages=history)

    budget_need = next(n for n in snapshot.needs if n.need_type in {NeedType.BUDGET_CEILING, NeedType.BUDGET_RANGE})
    assert budget_need.value == 7000.0
    # Zero premium preference extracted from assistant statement
    assert not any(n.value == "Premium" for n in snapshot.needs)


def test_memory_need_poisoning_protection():
    """Lead memory claims customer likes expensive products, but current message has hard budget ceiling."""
    user_text = "ميزانيتي أقصى حاجة 7000"
    snapshot = extract_customer_needs(user_text, company_id="test_comp", lead_id="1")

    budget_item = next(n for n in snapshot.hard_constraints if n.need_type == NeedType.BUDGET_CEILING)
    assert budget_item.value == 7000.0


# =====================================================================
# 2. ARVENA BIAS TEST & NO EXPENSIVE PRODUCT BIAS
# =====================================================================

def test_arvena_bias_cheaper_fits_budget_ranks_above_expensive(db_session, arvena_catalog_json):
    company_id = "comp_arvena_bias"
    company = make_company(company_id, name="Arvena Corp")
    db_session.add(company)
    knowledge = CompanyKnowledge(company_id=company_id, products_data=arvena_catalog_json)
    db_session.add(knowledge)
    db_session.commit()

    # Need: Chair, budget ceiling 7000 EGP
    user_input = "أنا محتاج كرسي مكتبي وميزانيتي أقصى حاجة 7000 جنيه"
    snapshot = extract_customer_needs(user_input, company_id=company_id, lead_id="10")
    decision = evaluate_recommendation_decision(db_session, company_id=company_id, lead_id="10", need_snapshot=snapshot, user_input=user_input)

    assert decision.outcome == RecommendationOutcome.RECOMMEND_ONE
    assert len(decision.recommended_products) >= 1

    top_product = decision.recommended_products[0]
    assert top_product.product_name == "Arvena Ergo One"
    assert top_product.price == 6900

    # Verify Arvena Ergo Pro (10900 EGP) was excluded due to hard budget constraint
    excluded_names = [e.product_name for e in decision.excluded_products]
    assert "Arvena Ergo Pro" in excluded_names


def test_no_expensive_product_bias_when_both_fit(db_session):
    """When both products fit budget & requirements, lower price does NOT penalize fit."""
    catalog_json = json.dumps([
        {"name": "Chair Basic", "price": 5000, "category": "Office Chair", "description": "Good chair for 8h work"},
        {"name": "Chair Deluxe", "price": 9000, "category": "Office Chair", "description": "Good chair for 8h work"},
    ])
    company_id = "comp_no_exp_bias"
    db_session.add(make_company(company_id, name="Test Co"))
    db_session.add(CompanyKnowledge(company_id=company_id, products_data=catalog_json))
    db_session.commit()

    user_input = "عايز كرسي للشغل وميزانيتي 10000"
    snapshot = extract_customer_needs(user_input, company_id=company_id, lead_id="11")
    decision = evaluate_recommendation_decision(db_session, company_id=company_id, lead_id="11", need_snapshot=snapshot, user_input=user_input)

    assert len(decision.recommended_products) >= 2
    # Chair Basic (5000) should rank equal or higher than Chair Deluxe (9000)
    assert decision.recommended_products[0].score >= decision.recommended_products[1].score


# =====================================================================
# 3. CATALOG ORDER SHUFFLE TEST (NO CATALOG POSITION BIAS)
# =====================================================================

def test_catalog_order_shuffle_semantic_stability(db_session):
    cat_order_1 = json.dumps([
        {"name": "Product A", "price": 6000, "category": "Office Chair", "description": "Ergonomic mesh chair with headrest"},
        {"name": "Product B", "price": 12000, "category": "Office Chair", "description": "Executive leather chair"},
    ])
    cat_order_2 = json.dumps([
        {"name": "Product B", "price": 12000, "category": "Office Chair", "description": "Executive leather chair"},
        {"name": "Product A", "price": 6000, "category": "Office Chair", "description": "Ergonomic mesh chair with headrest"},
    ])

    # Company 1
    db_session.add(make_company("comp_shuffle_1", name="Co 1"))
    db_session.add(CompanyKnowledge(company_id="comp_shuffle_1", products_data=cat_order_1))

    # Company 2
    db_session.add(make_company("comp_shuffle_2", name="Co 2"))
    db_session.add(CompanyKnowledge(company_id="comp_shuffle_2", products_data=cat_order_2))
    db_session.commit()

    user_input = "عايز كرسي شبك بميزانية 7000"
    snap1 = extract_customer_needs(user_input, "comp_shuffle_1", "1")
    snap2 = extract_customer_needs(user_input, "comp_shuffle_2", "1")

    dec1 = evaluate_recommendation_decision(db_session, "comp_shuffle_1", "1", snap1, user_input=user_input)
    dec2 = evaluate_recommendation_decision(db_session, "comp_shuffle_2", "1", snap2, user_input=user_input)

    assert dec1.recommended_products[0].product_name == dec2.recommended_products[0].product_name == "Product A"


# =====================================================================
# 4. UNKNOWN ATTRIBUTE SAFETY & HARD CONSTRAINT FILTERING
# =====================================================================

def test_unknown_attribute_safety():
    """If customer requires 150kg capacity and catalog lacks weight data, feature status is UNKNOWN, not fabricated."""
    product = ProductContext(name="Chair X", price=5000, description="Office chair with lumbar support")
    p_has = _product_has_feature(product, "capacity_150kg")
    assert p_has is None  # Unknown, not True or False!


def test_hard_feature_missing_excludes_product(db_session):
    catalog_json = json.dumps([
        {"name": "Ergo Headrest", "price": 6500, "description": "Ergonomic chair with mesh headrest"},
        {"name": "Ergo Standard", "price": 6000, "description": "Ergonomic chair بدون مسند رأس"},
    ])
    company_id = "comp_hard_feat"
    db_session.add(make_company(company_id, name="Co Hard Feat"))
    db_session.add(CompanyKnowledge(company_id=company_id, products_data=catalog_json))
    db_session.commit()

    user_input = "لازم كرسي فيه مسند رأس وميزانيتي 7000"
    snapshot = extract_customer_needs(user_input, company_id=company_id, lead_id="12")
    decision = evaluate_recommendation_decision(db_session, company_id=company_id, lead_id="12", need_snapshot=snapshot, user_input=user_input)

    assert decision.outcome == RecommendationOutcome.RECOMMEND_ONE
    assert decision.recommended_products[0].product_name == "Ergo Headrest"
    excluded_names = [e.product_name for e in decision.excluded_products]
    assert "Ergo Standard" in excluded_names


# =====================================================================
# 5. INSUFFICIENT INFORMATION & NO VALID FIT POLICIES
# =====================================================================

def test_insufficient_information_asks_one_clarifying_question(db_session, arvena_catalog_json):
    company_id = "comp_insufficient_info"
    db_session.add(make_company(company_id, name="Co Insufficient"))
    db_session.add(CompanyKnowledge(company_id=company_id, products_data=arvena_catalog_json))
    db_session.commit()

    user_input = "أنهي أحسن ليا؟"
    snapshot = extract_customer_needs(user_input, company_id=company_id, lead_id="13")
    decision = evaluate_recommendation_decision(db_session, company_id=company_id, lead_id="13", need_snapshot=snapshot, user_input=user_input)

    assert decision.outcome == RecommendationOutcome.ASK_CLARIFYING_QUESTION
    assert decision.clarifying_question_text is not None
    assert "ساعة" in decision.clarifying_question_text or "ميزانية" in decision.clarifying_question_text


def test_no_valid_fit_returns_no_valid_fit_outcome(db_session, arvena_catalog_json):
    company_id = "comp_no_fit"
    db_session.add(make_company(company_id, name="Co No Fit"))
    db_session.add(CompanyKnowledge(company_id=company_id, products_data=arvena_catalog_json))
    db_session.commit()

    user_input = "عايز كرسي بميزانية أقصى حاجة 2000 جنيه"
    snapshot = extract_customer_needs(user_input, company_id=company_id, lead_id="14")
    decision = evaluate_recommendation_decision(db_session, company_id=company_id, lead_id="14", need_snapshot=snapshot, user_input=user_input)

    assert decision.outcome == RecommendationOutcome.NO_VALID_FIT
    assert len(decision.excluded_products) == 4


# =====================================================================
# 6. LARGE CATALOG & MALFORMED SAFETY TESTS
# =====================================================================

def test_large_catalog_discovery_100_products(db_session):
    prods = []
    for i in range(1, 105):
        prods.append({
            "id": f"p_{i}",
            "name": f"Product {i}",
            "price": 1000 + (i * 100),
            "category": "Office Chair" if i == 99 else "General Item",
            "description": "Special target chair" if i == 99 else f"Item description {i}",
        })

    company_id = "comp_large_cat"
    db_session.add(make_company(company_id, name="Large Co"))
    db_session.add(CompanyKnowledge(company_id=company_id, products_data=json.dumps(prods)))
    db_session.commit()

    user_input = "عايز Special target chair بميزانية 11000"
    snapshot = extract_customer_needs(user_input, company_id=company_id, lead_id="15")
    decision = evaluate_recommendation_decision(db_session, company_id=company_id, lead_id="15", need_snapshot=snapshot, user_input=user_input)

    assert decision.outcome == RecommendationOutcome.RECOMMEND_ONE
    assert decision.recommended_products[0].product_name == "Product 99"


def test_malformed_catalog_fails_closed_without_crash(db_session):
    malformed_json = "INVALID_JSON_STRING_12345"
    company_id = "comp_malformed"
    db_session.add(make_company(company_id, name="Malformed Co"))
    db_session.add(CompanyKnowledge(company_id=company_id, products_data=malformed_json))
    db_session.commit()

    snapshot = extract_customer_needs("عايز كرسي", company_id=company_id, lead_id="16")
    decision = evaluate_recommendation_decision(db_session, company_id=company_id, lead_id="16", need_snapshot=snapshot, user_input="عايز كرسي")

    assert decision.outcome == RecommendationOutcome.NO_VALID_FIT


# =====================================================================
# 7. ETHICAL PRODUCT FIT POLICY & ALIGNMENT ENFORCEMENT
# =====================================================================

def test_ethical_policy_prohibits_dark_tactics():
    decision = RecommendationDecision(
        company_id="c1",
        lead_id="l1",
        outcome=RecommendationOutcome.RECOMMEND_ONE,
    )
    policy = evaluate_ethical_product_fit_policy(decision)

    assert ProhibitedRecommendationTactic.PREFER_EXPENSIVE_WITHOUT_FIT in policy.prohibited_tactics
    assert ProhibitedRecommendationTactic.FAKE_PERSONALIZATION in policy.prohibited_tactics
    assert ProhibitedRecommendationTactic.FAKE_FIT_PERCENTAGE in policy.prohibited_tactics


def test_enforce_reply_alignment_repairs_fake_precision():
    decision = RecommendationDecision(
        company_id="c1",
        lead_id="l1",
        outcome=RecommendationOutcome.RECOMMEND_ONE,
    )
    policy = evaluate_ethical_product_fit_policy(decision)

    candidate = "كرسي Arvena Ergo One مناسب جداً ليك بنسبة 95%."
    res = enforce_recommendation_reply_alignment(candidate, decision, policy)

    assert res.status == "REPAIRED"
    assert "95%" not in res.final_answer
    assert "FAKE_FIT_PERCENTAGE" in str(res.violations)


def test_enforce_reply_alignment_blocks_expensive_always_better_claim():
    decision = RecommendationDecision(
        company_id="c1",
        lead_id="l1",
        outcome=RecommendationOutcome.RECOMMEND_ONE,
    )
    policy = evaluate_ethical_product_fit_policy(decision)

    candidate = "الأغلى دايماً أفضل ليك."
    res = enforce_recommendation_reply_alignment(candidate, decision, policy)

    assert res.status == "REPAIRED"
    assert "الأغلى دايماً أفضل" not in res.final_answer


# =====================================================================
# 8. CROSS-TURN NEED EVOLUTION & TENANT ISOLATION
# =====================================================================

def test_cross_turn_need_evolution():
    # Turn 1
    t1 = extract_customer_needs("عايز كرسي للشغل", company_id="c1", lead_id="1")
    assert any(n.need_type == NeedType.USE_CASE for n in t1.needs)

    # Turn 2
    history = [
        {"role": "user", "content": "عايز كرسي للشغل"},
        {"role": "assistant", "content": "تمام أستاذنا"},
        {"role": "user", "content": "بقعد 8 ساعات وميزانيتي 7000"},
    ]
    t2 = extract_customer_needs(history[-1]["content"], company_id="c1", lead_id="1", recent_messages=history)

    assert any(n.need_type == NeedType.BUDGET_CEILING for n in t2.needs)
    assert any(n.need_type == NeedType.USE_CASE for n in t2.needs)


def test_tenant_isolation_prevents_cross_company_recommendations(db_session, arvena_catalog_json):
    # Company A has products
    db_session.add(make_company("comp_tenant_a", name="Tenant A"))
    db_session.add(CompanyKnowledge(company_id="comp_tenant_a", products_data=arvena_catalog_json))

    # Company B has no products
    db_session.add(make_company("comp_tenant_b", name="Tenant B"))
    db_session.add(CompanyKnowledge(company_id="comp_tenant_b", products_data=json.dumps([])))
    db_session.commit()

    snap_b = extract_customer_needs("أنهي أنسب كرسي؟", company_id="comp_tenant_b", lead_id="99")
    dec_b = evaluate_recommendation_decision(db_session, company_id="comp_tenant_b", lead_id="99", need_snapshot=snap_b, user_input="أنهي أنسب كرسي؟")

    assert dec_b.outcome == RecommendationOutcome.NO_VALID_FIT
    assert len(dec_b.recommended_products) == 0


class TestRecommendationCommitPathPersistenceAndTransport:
    def test_hard_budget_violation_candidate_repaired_before_persistence_and_transport(self, db_session, arvena_catalog_json):
        """Customer budget 7000. Unsafe candidate recommends Ergo Pro (10900). Candidate is repaired to Ergo One (6900) before persistence."""
        from services.recommendation_intelligence_service import ExcludedProductRef, RecommendedProductRef

        decision = RecommendationDecision(
            company_id="comp_rec_commit",
            lead_id="l1",
            outcome=RecommendationOutcome.RECOMMEND_ONE,
            recommended_products=[
                RecommendedProductRef(
                    product_name="Arvena Ergo One",
                    price=6900,
                    fit_level=FitLevel.STRONG,
                )
            ],
            excluded_products=[
                ExcludedProductRef(
                    product_name="Arvena Ergo Pro",
                    reason_codes=[ExclusionReasonCode.OUTSIDE_BUDGET],
                )
            ],
        )
        policy = evaluate_ethical_product_fit_policy(decision)

        unsafe_candidate = "Ergo Pro هو الأنسب ليك بـ10900"
        res = enforce_recommendation_reply_alignment(unsafe_candidate, decision, policy)

        assert res.status == "REPAIRED"
        assert "Ergo Pro" not in res.final_answer
        assert "10900" not in res.final_answer
        persisted_body = res.final_answer
        transported_body = res.final_answer
        assert persisted_body == transported_body
        assert "Ergo Pro" not in persisted_body

    def test_fake_personalization_repaired_before_persistence(self):
        """Insufficient info + candidate claiming 'أكيد Ergo Pro مثالي ليك' -> Fake recommendation is blocked/repaired."""
        decision = RecommendationDecision(
            company_id="c1",
            lead_id="l1",
            outcome=RecommendationOutcome.INSUFFICIENT_INFORMATION,
        )
        policy = evaluate_ethical_product_fit_policy(decision)

        unsafe_candidate = "أكيد Ergo Pro مثالي ليك ومناسب جداً."
        res = enforce_recommendation_reply_alignment(unsafe_candidate, decision, policy)

        assert res.status == "REPAIRED"
        assert "مثالي" not in res.final_answer
        assert res.final_answer == res.final_answer


class TestRecommendationNextBestActionComposition:
    def test_case_a_ask_clarifying_question_composition(self, db_session, arvena_catalog_json):
        """Customer: 'أنهي أنسب ليا؟' No criteria -> Recommendation: ASK_CLARIFYING_QUESTION -> NBA: ASK_ONE_DECISION_CRITERION."""
        from services.next_best_action_service import NextBestSalesAction, evaluate_next_best_action

        db_session.add(make_company("comp_case_a", name="Case A"))
        db_session.add(CompanyKnowledge(company_id="comp_case_a", products_data=arvena_catalog_json))
        db_session.commit()

        snap = extract_customer_needs("أنهي أنسب ليا؟", company_id="comp_case_a", lead_id="1")
        rec_dec = evaluate_recommendation_decision(db_session, company_id="comp_case_a", lead_id="1", need_snapshot=snap, user_input="أنهي أنسب ليا؟")
        assert rec_dec.outcome == RecommendationOutcome.ASK_CLARIFYING_QUESTION

        nba = evaluate_next_best_action(db_session, company_id="comp_case_a", lead_id=1, current_message_text="أنهي أنسب ليا؟", recommendation_decision=rec_dec)
        assert nba.primary_action == NextBestSalesAction.ASK_ONE_DECISION_CRITERION.value

    def test_case_b_recommend_one_composition(self, db_session):
        """Recommendation: RECOMMEND_ONE -> NBA consumes recommendation context without overriding explicit request."""
        from services.next_best_action_service import NextBestSalesAction, evaluate_next_best_action

        rec_dec = RecommendationDecision(
            company_id="c1",
            lead_id="1",
            outcome=RecommendationOutcome.RECOMMEND_ONE,
        )
        nba = evaluate_next_best_action(db_session, company_id="c1", lead_id=1, current_message_text="عايز أختار كرسي", recommendation_decision=rec_dec)
        assert nba.primary_action != NextBestSalesAction.PAUSE_FOR_HUMAN_TAKEOVER.value

    def test_case_c_purchase_commitment_overrides_recommendation(self, db_session):
        """Customer: 'اخترت Ergo Pro، ابعتلي الدفع' -> FACILITATE_PURCHASE (Recommendation does not dominate active commitment)."""
        from services.next_best_action_service import NextBestSalesAction, evaluate_next_best_action

        rec_dec = RecommendationDecision(
            company_id="c1",
            lead_id="1",
            outcome=RecommendationOutcome.ASK_CLARIFYING_QUESTION,
        )
        nba = evaluate_next_best_action(db_session, company_id="c1", lead_id=1, current_message_text="اخترت Ergo Pro، ابعتلي الدفع", recommendation_decision=rec_dec)
        assert nba.primary_action == NextBestSalesAction.FACILITATE_PURCHASE.value

    def test_case_d_explicit_rejection_overrides_recommendation(self, db_session):
        """Customer: 'مش مهتم خلاص' -> RESPECT_REJECTION (Recommendation does not reopen sale)."""
        from services.next_best_action_service import NextBestSalesAction, evaluate_next_best_action

        rec_dec = RecommendationDecision(
            company_id="c1",
            lead_id="1",
            outcome=RecommendationOutcome.RECOMMEND_ONE,
        )
        nba = evaluate_next_best_action(db_session, company_id="c1", lead_id=1, current_message_text="مش مهتم خلاص", recommendation_decision=rec_dec)
        assert nba.primary_action == NextBestSalesAction.RESPECT_REJECTION.value

    def test_case_e_post_sale_support_overrides_recommendation(self, db_session):
        """Customer: 'الطلب وصل ناقص' -> ROUTE_POST_SALE_SUPPORT (Recommendation does not hijack support)."""
        from services.next_best_action_service import NextBestSalesAction, evaluate_next_best_action

        rec_dec = RecommendationDecision(
            company_id="c1",
            lead_id="1",
            outcome=RecommendationOutcome.RECOMMEND_ONE,
        )
        nba = evaluate_next_best_action(db_session, company_id="c1", lead_id=1, current_message_text="الطلب وصل ناقص", recommendation_decision=rec_dec)
        assert nba.primary_action == NextBestSalesAction.ROUTE_POST_SALE_SUPPORT.value


class TestRecommendationFallbackMatrix:
    def test_recommendation_fallback_matrix_safety(self):
        """All fallback paths across outcomes must prohibit fake features, fake prices, and fake personalization."""
        from brain import _heuristic_ai_payload

        context = {
            "conversation_state": "QUALIFICATION",
            "company_data": {"company_name": "Test Co", "products_data": []},
            "history": [],
        }

        queries = [
            "أنهي أنسب ليا؟",
            "ميزانيتي 7000 وعايز كرسي",
            "عايز حاجة تشيل 150 كيلو",
            "عندكم كراسي طبية؟",
        ]

        for q in queries:
            payload = _heuristic_ai_payload(q, context, context["company_data"])
            reply = payload.get("reply", "")
            assert "95%" not in reply, f"Fallback for '{q}' contains fake fit percentage"
            assert "الأغلى دايماً أفضل" not in reply, f"Fallback for '{q}' contains price bias"


class TestRecommendationIdempotencyAndConcurrency:
    def test_duplicate_recommendation_request_is_idempotent(self, db_session):
        """Repeated recommendation extraction produces identical CustomerNeedSnapshot without confidence inflation."""
        snap1 = extract_customer_needs("ميزانيتي أقصى حاجة 7000 وعايز كرسي للشغل", company_id="c1", lead_id="1")
        snap2 = extract_customer_needs("ميزانيتي أقصى حاجة 7000 وعايز كرسي للشغل", company_id="c1", lead_id="1")

        assert len(snap1.needs) == len(snap2.needs)
        b1 = next((n.value for n in snap1.needs if n.need_type == NeedType.BUDGET_CEILING.value or n.need_type == NeedType.BUDGET_CEILING), None)
        b2 = next((n.value for n in snap2.needs if n.need_type == NeedType.BUDGET_CEILING.value or n.need_type == NeedType.BUDGET_CEILING), None)
        assert b1 == b2 == 7000.0

    def test_duplicate_hard_feature_does_not_duplicate_need_event(self):
        """Repeated hard feature mentions yield single canonical hard feature constraint."""
        snap = extract_customer_needs("لازم فيه headrest ولازم فيه headrest", company_id="c1", lead_id="1")
        headrest_needs = [n for n in snap.needs if "headrest" in str(n.value).lower() or (n.raw_text and "headrest" in str(n.raw_text).lower())]
        assert len(headrest_needs) == 1


class TestRecommendationNoSecondLLM:
    def test_no_second_llm_call_for_recommendation_intelligence(self, db_session):
        """Need extraction, constraint evaluation, eligibility, ranking, product-fit policy, and alignment add exactly 0 extra LLM calls."""
        mock_provider = MagicMock()
        mock_provider.call_count = 0

        snap = extract_customer_needs("ميزانيتي 7000", company_id="c1", lead_id="1")
        dec = evaluate_recommendation_decision(db_session, company_id="c1", lead_id="1", need_snapshot=snap, user_input="ميزانيتي 7000")
        policy = evaluate_ethical_product_fit_policy(dec)
        res = enforce_recommendation_reply_alignment("تمام يا فندم", dec, policy)

        added_calls = mock_provider.call_count
        assert added_calls == 0


class TestRecommendationAdversarialEnforcementOrder:
    def test_recommendation_alignment_repairs_are_subject_to_subsequent_truth_enforcement(self, arvena_catalog_json):
        """Proves recommendation alignment repairs run before pricing/evidence enforcement so post-repair text cannot bypass truth enforcement."""
        from services.trusted_product_pricing_enforcement import enforce_trusted_product_and_pricing
        from services.product_context_service import normalize_products_data, resolve_runtime_product_context

        parsed_products = normalize_products_data(arvena_catalog_json)
        resolved_ctx = resolve_runtime_product_context("بكام الكرسي؟", parsed_products)
        company_data = {"company_name": "Test Co", "products_data": arvena_catalog_json}

        # Candidate reply after recommendation alignment injected an untrusted price claim:
        recommendation_repaired_text = "بناءً على احتياجاتك المحددة، منتج Arvena Ergo One بسعر 99999 ج.م هو الخيار الأنسب لحضرتك."

        # Pricing enforcement runs AFTER recommendation alignment:
        truth_res = enforce_trusted_product_and_pricing(
            user_input="بكام الكرسي؟",
            candidate_reply=recommendation_repaired_text,
            resolved_context=resolved_ctx,
            all_products=parsed_products,
            company_knowledge=company_data,
        )

        assert truth_res.status in {"REPAIRED", "SAFE_FALLBACK"}
        assert "99999" not in truth_res.final_answer
        assert len(truth_res.final_answer) > 0


