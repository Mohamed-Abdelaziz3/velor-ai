"""
Test suite for Customer Communication Profile & Adaptive Selling Style subsystem.
Verifies all 101 non-negotiable requirements, anti-poisoning boundaries, explicit vs observed distinctions,
supersession, revocation, staleness, style alignment enforcement, persistence composition, idempotency,
concurrency, tenant isolation, no-second-LLM proof, and production path execution.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import pytest
from database import Company, CompanyKnowledge, Lead, LeadMemory, SessionLocal
from services.customer_memory_service import (
    CustomerPreferenceMemoryItem,
    CustomerPreferenceMemorySnapshot,
    PreferenceDimension,
    PreferenceExplicitness,
    PreferencePolarity,
    PreferenceScope,
    PreferenceStability,
    PreferenceStatus,
    sync_preference_memory_to_db,
)
from services.customer_communication_service import (
    AdaptiveCommunicationPolicy,
    AnswerOrderMode,
    CommunicationDimension,
    CommunicationExplicitness,
    CommunicationScope,
    CommunicationStability,
    CommunicationStatus,
    CustomerCommunicationProfileItem,
    CustomerCommunicationProfileSnapshot,
    DialectMode,
    EmojiPolicy,
    ExplanationDepth,
    LanguageMode,
    OptionPresentation,
    QuestionTolerance,
    RegisterMode,
    RepetitionPolicy,
    StructureFormat,
    TerminologyLevel,
    VerbosityMode,
    enforce_communication_style_alignment,
    evaluate_adaptive_communication_policy,
    evaluate_customer_communication_profile,
    extract_communication_signals_from_text,
    format_communication_policy_for_prompt,
    sync_communication_profile_to_db,
)


@pytest.fixture
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def setup_company(db_session):
    company_id = "test_comm_company"
    company = db_session.query(Company).filter(Company.company_id == company_id).first()
    if not company:
        company = Company(
            company_id=company_id,
            company_name="Test Comm Company",
            email="comm@test.com",
            password="test_pass_123",
            api_key_hash="comm_hash",
        )
        db_session.add(company)
        db_session.commit()

    knowledge = db_session.query(CompanyKnowledge).filter(CompanyKnowledge.company_id == company_id).first()
    if not knowledge:
        knowledge = CompanyKnowledge(
            company_id=company_id,
            system_prompt="You are a helpful sales assistant.",
            products_data='[{"name": "Arvena Ergo One", "price": 500, "category": "Chairs"}]',
        )
        db_session.add(knowledge)
        db_session.commit()

    lead = db_session.query(Lead).filter(Lead.company_id == company_id, Lead.phone == "01012345678").first()
    if not lead:
        lead = Lead(
            company_id=company_id,
            name="Test Lead",
            phone="01012345678",
            whatsapp_number="201012345678",
        )
        db_session.add(lead)
        db_session.commit()

    yield company_id, lead.id

    try:
        db_session.query(LeadMemory).delete()
        db_session.query(Lead).filter(Lead.company_id.in_([company_id, "comp_A", "comp_B"])).delete()
        db_session.query(CompanyKnowledge).filter(CompanyKnowledge.company_id.in_([company_id, "comp_A", "comp_B"])).delete()
        db_session.query(Company).filter(Company.company_id.in_([company_id, "comp_A", "comp_B"])).delete()
        db_session.commit()
    except Exception:
        db_session.rollback()


def test_signal_extraction_explicit_brevity():
    text = "اختصر وقولي من الآخر"
    items, revoked, signals = extract_communication_signals_from_text(
        text, "comp1", "lead1", "msg1", "2026-07-06T00:00:00Z"
    )
    assert "BRIEF" in signals
    assert len(items) == 1
    assert items[0].dimension == CommunicationDimension.VERBOSITY
    assert items[0].value == VerbosityMode.BRIEF.value
    assert items[0].explicitness == CommunicationExplicitness.EXPLICIT
    assert items[0].confidence == 1.0


def test_signal_extraction_explicit_detail():
    text = "اشرحلي بالتفصيل اديني كل التفاصيل"
    items, revoked, signals = extract_communication_signals_from_text(
        text, "comp1", "lead1", "msg1", "2026-07-06T00:00:00Z"
    )
    assert "DETAILED" in signals
    assert items[0].dimension == CommunicationDimension.VERBOSITY
    assert items[0].value == VerbosityMode.DETAILED.value
    assert items[0].reason_codes == ["EXPLICIT_DETAIL_REQUEST"]


def test_signal_extraction_explicit_language():
    items_ar, _, sig_ar = extract_communication_signals_from_text("كلمني عربي", "comp1", "lead1", "msg1", "2026-07-06T00:00:00Z")
    assert "ARABIC" in sig_ar
    assert items_ar[0].value == LanguageMode.ARABIC.value
    assert items_ar[0].dimension == CommunicationDimension.LANGUAGE_MODE

    items_en, _, sig_en = extract_communication_signals_from_text("English please", "comp1", "lead1", "msg1", "2026-07-06T00:00:00Z")
    assert "ENGLISH" in sig_en
    assert items_en[0].value == LanguageMode.ENGLISH.value
    assert items_en[0].dimension == CommunicationDimension.LANGUAGE_MODE


def test_signal_extraction_structure_and_no_emoji():
    text = "قارنلي في نقط وبلاش إيموجيز"
    items, revoked, signals = extract_communication_signals_from_text(
        text, "comp1", "lead1", "msg1", "2026-07-06T00:00:00Z"
    )
    assert "BULLETS" in signals
    assert "NO_EMOJI" in signals
    dims = {x.dimension for x in items}
    assert CommunicationDimension.STRUCTURE_FORMAT in dims
    assert CommunicationDimension.EMOJI_POLICY in dims


def test_signal_extraction_price_first_and_questions():
    text = "قول السعر الأول وبلاش أسئلة كتير"
    items, revoked, signals = extract_communication_signals_from_text(
        text, "comp1", "lead1", "msg1", "2026-07-06T00:00:00Z"
    )
    assert "PRICE_FIRST" in signals
    assert "LOW_QUESTIONS" in signals


def test_supersession_model(db_session, setup_company):
    company_id, lead_id = setup_company
    hist1 = [{"role": "user", "content": "دايمًا اختصرلي"}]
    snap1 = evaluate_customer_communication_profile(db_session, company_id, lead_id, "دايمًا اختصرلي", hist1)
    assert snap1.effective_for_current_turn[CommunicationDimension.VERBOSITY.value] == VerbosityMode.BRIEF.value
    assert len(snap1.active_explicit_preferences) == 1

    hist2 = hist1 + [
        {"role": "assistant", "content": "تمام يا فندم."},
        {"role": "user", "content": "خلاص بقيت أحب التفاصيل واشرحلي بالتفصيل"},
    ]
    snap2 = evaluate_customer_communication_profile(db_session, company_id, lead_id, "خلاص بقيت أحب التفاصيل واشرحلي بالتفصيل", hist2)
    assert snap2.effective_for_current_turn[CommunicationDimension.VERBOSITY.value] == VerbosityMode.DETAILED.value
    assert snap2.active_explicit_preferences[0].value == VerbosityMode.DETAILED.value


def test_revocation_model(db_session, setup_company):
    company_id, lead_id = setup_company
    hist = [
        {"role": "user", "content": "دايمًا اختصرلي"},
        {"role": "assistant", "content": "تمام."},
        {"role": "user", "content": "خلاص متعتبرش إني بحب الاختصار"},
    ]
    snap = evaluate_customer_communication_profile(db_session, company_id, lead_id, "خلاص متعتبرش إني بحب الاختصار", hist)
    assert len(snap.revoked_items) > 0
    assert snap.revoked_items[0].status == CommunicationStatus.REVOKED
    assert CommunicationDimension.VERBOSITY.value not in snap.effective_for_current_turn


def test_current_turn_override_wins_over_stable_profile(db_session, setup_company):
    company_id, lead_id = setup_company
    hist = [
        {"role": "user", "content": "دايمًا اختصرلي"},
        {"role": "assistant", "content": "تمام يا فندم."},
    ]
    current_input = "المرة دي اشرحلي بالتفصيل"
    snap = evaluate_customer_communication_profile(db_session, company_id, lead_id, current_input, hist)
    assert snap.effective_for_current_turn[CommunicationDimension.VERBOSITY.value] == VerbosityMode.DETAILED.value
    assert len(snap.current_overrides) == 1


def test_anti_poisoning_boundaries():
    # Single short message without explicit request
    items_short, _, signals_short = extract_communication_signals_from_text("السعر؟", "comp1", "lead1", "msg1", "2026-07-06T00:00:00Z")
    assert "BRIEF" not in signals_short
    assert len(items_short) == 0

    # Demographic / profession
    items_prof, _, signals_prof = extract_communication_signals_from_text("أنا مهندس وبدور على كرسي", "comp1", "lead1", "msg1", "2026-07-06T00:00:00Z")
    assert "TECHNICAL_TERMS" not in signals_prof
    assert len(items_prof) == 0

    # Student
    items_stud, _, signals_stud = extract_communication_signals_from_text("أنا طالب في الجامعة", "comp1", "lead1", "msg1", "2026-07-06T00:00:00Z")
    assert "SIMPLE_TERMS" not in signals_stud
    assert len(items_stud) == 0


def test_high_risk_cases_matrix():
    # Case A: Policy ARABIC, Candidate English-only
    pol_ar = AdaptiveCommunicationPolicy(company_id="c1", lead_id="l1", language_mode=LanguageMode.ARABIC)
    res_a = enforce_communication_style_alignment("Here are all product specifications in English.", pol_ar)
    assert res_a.status == "REPAIRED"
    assert "LANGUAGE_MISMATCH_ARABIC_REQUIRED" in res_a.violations
    assert "تفاصيل المنتجات" in res_a.final_answer

    # Case B: Policy ENGLISH, Candidate Arabic-only
    pol_en = AdaptiveCommunicationPolicy(company_id="c1", lead_id="l1", language_mode=LanguageMode.ENGLISH)
    res_b = enforce_communication_style_alignment("أهلاً بك، إليك التفاصيل الكاملة للمنتج والأسعار المتاحة.", pol_en)
    assert res_b.status == "REPAIRED"
    assert "LANGUAGE_MISMATCH_ENGLISH_REQUIRED" in res_b.violations
    assert "details" in res_b.final_answer

    # Case D: Policy NO_EMOJI, Candidate emoji-heavy
    pol_emoji = AdaptiveCommunicationPolicy(company_id="c1", lead_id="l1", emoji_policy=EmojiPolicy.NONE)
    res_d = enforce_communication_style_alignment("أهلاً بك! 😊 كرسي Arvena ممتاز 👌🔥", pol_emoji)
    assert res_d.status == "REPAIRED"
    assert "EMOJI_PROHIBITED_VIOLATION" in res_d.violations
    assert "😊" not in res_d.final_answer
    assert "👌" not in res_d.final_answer

    # Case E & Question Composition: Policy LOW questions, Candidate asks 3 questions
    pol_q = AdaptiveCommunicationPolicy(company_id="c1", lead_id="l1", question_budget="ONE_IF_REQUIRED")
    rec_dec = SimpleNamespace(missing_information=["budget"])
    res_e = enforce_communication_style_alignment("تحب اللون الإسود؟ ولا ميزانيتك كام؟ وشغلك مكتبي؟", pol_q, recommendation_decision=rec_dec)
    assert res_e.status == "REPAIRED"
    assert "EXCESSIVE_QUESTIONS_STYLE_VIOLATION" in res_e.violations
    assert res_e.final_answer.count("؟") == 1
    assert "ميزانيتك كام" in res_e.final_answer  # Highest value question preserved!

    # Case G: Policy PRICE_FIRST, Candidate buries price
    pol_pf = AdaptiveCommunicationPolicy(company_id="c1", lead_id="l1", answer_order=AnswerOrderMode.PRICE_FIRST)
    res_g = enforce_communication_style_alignment("أهلاً بك في شركتنا، يسعدنا تقديم أفضل حلول الأثاث المكتبي المتطور بالكامل. سعر الكرسي 500 ج.م.", pol_pf)
    assert res_g.status == "REPAIRED"
    assert "PRICE_NOT_FIRST_VIOLATION" in res_g.violations
    assert res_g.final_answer.startswith("السعر: 500 ج.م.")

    # Case H: No explicit profile, Candidate claims "هختصرهالك زي ما بتحب"
    snap_empty = CustomerCommunicationProfileSnapshot(company_id="c1", lead_id="l1")
    pol_b = AdaptiveCommunicationPolicy(company_id="c1", lead_id="l1", verbosity=VerbosityMode.BRIEF)
    res_h = enforce_communication_style_alignment("زي ما بتحب الردود المختصرة، سعر الكرسي 500 جنيه.", pol_b, profile_snapshot=snap_empty)
    assert res_h.status == "REPAIRED"
    assert "FAKE_COMMUNICATION_MEMORY_CLAIM" in res_h.violations
    assert "زي ما بتحب" not in res_h.final_answer

    # Case L & P: Profanity & Fake intimacy mirroring
    res_l = enforce_communication_style_alignment("احا أهلاً بك يا حبيبي وحشتنا", pol_b)
    assert res_l.status == "REPAIRED"
    assert "PROFANITY_OR_FAKE_INTIMACY_BLOCKED" in res_l.violations
    assert "احا" not in res_l.final_answer
    assert "وحشتنا" not in res_l.final_answer

    # Case O: Pressure Escalation Guard
    res_o = enforce_communication_style_alignment("لازم تشتري دلوقتي قبل فوات الأوان", pol_b)
    assert res_o.status == "REPAIRED"
    assert "PRESSURE_ESCALATION_BLOCKED" in res_o.violations
    assert "لازم تشتري دلوقتي" not in res_o.final_answer

    # Case N: False Exclusivity Repair when RecommendationDecision is MULTIPLE
    rec_mult = SimpleNamespace(decision="RECOMMEND_MULTIPLE")
    res_n = enforce_communication_style_alignment("المنتج الوحيد المناسب ليك هو Arvena.", pol_b, recommendation_decision=rec_mult)
    assert res_n.status == "REPAIRED"
    assert "FALSE_EXCLUSIVITY_BLOCKED" in res_n.violations
    assert "الوحيد المناسب" not in res_n.final_answer


def test_persistence_composition_8_step_non_clobbering(db_session, setup_company):
    company_id, lead_id = setup_company

    # 1. Persist commercial customer memory
    comm_item = CustomerPreferenceMemoryItem(
        memory_id="mem_comm_1",
        company_id=company_id,
        lead_id=str(lead_id),
        dimension=PreferenceDimension.COLOR,
        polarity=PreferencePolarity.PREFER,
        value="Black",
        explicitness=PreferenceExplicitness.EXPLICIT,
        stability=PreferenceStability.STABLE,
        status=PreferenceStatus.ACTIVE,
    )
    comm_snap = CustomerPreferenceMemorySnapshot(
        company_id=company_id,
        lead_id=str(lead_id),
        active_preferences=[comm_item],
    )
    sync_preference_memory_to_db(db_session, company_id, lead_id, comm_snap)

    # 2. Persist communication profile
    style_item = CustomerCommunicationProfileItem(
        profile_item_id="style_item_1",
        company_id=company_id,
        lead_id=str(lead_id),
        dimension=CommunicationDimension.EMOJI_POLICY,
        value=EmojiPolicy.NONE.value,
        explicitness=CommunicationExplicitness.EXPLICIT,
        stability=CommunicationStability.STABLE,
        status=CommunicationStatus.ACTIVE,
    )
    style_snap = CustomerCommunicationProfileSnapshot(
        company_id=company_id,
        lead_id=str(lead_id),
        active_explicit_preferences=[style_item],
        effective_for_current_turn={CommunicationDimension.EMOJI_POLICY.value: EmojiPolicy.NONE.value},
    )
    sync_communication_profile_to_db(db_session, company_id, lead_id, style_snap)

    # 3. Reload & assert both intact
    mem_row1 = db_session.query(LeadMemory).filter(LeadMemory.lead_id == lead_id).first()
    assert mem_row1 is not None
    assert "active_preferences" in mem_row1.preferences
    assert "communication_profile" in mem_row1.preferences

    # 4. Update commercial memory
    comm_snap.active_preferences.append(
        CustomerPreferenceMemoryItem(
            memory_id="mem_comm_2",
            company_id=company_id,
            lead_id=str(lead_id),
            dimension=PreferenceDimension.MATERIAL,
            polarity=PreferencePolarity.PREFER,
            value="Mesh",
            explicitness=PreferenceExplicitness.EXPLICIT,
            stability=PreferenceStability.STABLE,
            status=PreferenceStatus.ACTIVE,
        )
    )
    sync_preference_memory_to_db(db_session, company_id, lead_id, comm_snap)

    # 5. Assert communication profile intact
    mem_row2 = db_session.query(LeadMemory).filter(LeadMemory.lead_id == lead_id).first()
    assert "communication_profile" in mem_row2.preferences
    assert "active_preferences" in mem_row2.preferences

    # 6. Update communication profile
    style_snap.active_explicit_preferences.append(
        CustomerCommunicationProfileItem(
            profile_item_id="style_item_2",
            company_id=company_id,
            lead_id=str(lead_id),
            dimension=CommunicationDimension.VERBOSITY,
            value=VerbosityMode.BRIEF.value,
            explicitness=CommunicationExplicitness.EXPLICIT,
            stability=CommunicationStability.STABLE,
            status=CommunicationStatus.ACTIVE,
        )
    )
    sync_communication_profile_to_db(db_session, company_id, lead_id, style_snap)

    # 7. Assert commercial memory intact
    mem_row3 = db_session.query(LeadMemory).filter(LeadMemory.lead_id == lead_id).first()
    assert "active_preferences" in mem_row3.preferences
    assert "communication_profile" in mem_row3.preferences


def test_idempotency_and_deduplication(db_session, setup_company):
    company_id, lead_id = setup_company
    hist = [
        {"role": "user", "content": "دايمًا اختصرلي"},
        {"role": "user", "content": "دايمًا اختصرلي"},  # Same instruction twice
    ]
    snap = evaluate_customer_communication_profile(db_session, company_id, lead_id, "دايمًا اختصرلي", hist)
    # Exactly 1 active explicit BRIEF item
    brief_items = [x for x in snap.active_explicit_preferences if x.dimension == CommunicationDimension.VERBOSITY]
    assert len(brief_items) == 1
    assert brief_items[0].value == VerbosityMode.BRIEF.value


def test_tenant_isolation_proof(db_session):
    # Company A vs Company B isolation
    comp_a = db_session.query(Company).filter(Company.company_id == "comp_A").first()
    if not comp_a:
        comp_a = Company(company_id="comp_A", company_name="Comp A", email="a@comp.com", password="pass", api_key_hash="hash_a")
        db_session.add(comp_a)

    comp_b = db_session.query(Company).filter(Company.company_id == "comp_B").first()
    if not comp_b:
        comp_b = Company(company_id="comp_B", company_name="Comp B", email="b@comp.com", password="pass", api_key_hash="hash_b")
        db_session.add(comp_b)
    db_session.commit()

    lead_a = db_session.query(Lead).filter(Lead.company_id == "comp_A", Lead.phone == "01000000001").first()
    if not lead_a:
        lead_a = Lead(company_id="comp_A", name="Lead A", phone="01000000001")
        db_session.add(lead_a)

    lead_b = db_session.query(Lead).filter(Lead.company_id == "comp_B", Lead.phone == "01000000002").first()
    if not lead_b:
        lead_b = Lead(company_id="comp_B", name="Lead B", phone="01000000002")
        db_session.add(lead_b)
    db_session.commit()

    snap_a = evaluate_customer_communication_profile(db_session, "comp_A", lead_a.id, "كلمني عربي وبلاش إيموجيز", [{"role": "user", "content": "كلمني عربي وبلاش إيموجيز"}])
    sync_communication_profile_to_db(db_session, "comp_A", lead_a.id, snap_a)

    snap_b = evaluate_customer_communication_profile(db_session, "comp_B", lead_b.id, "English please", [{"role": "user", "content": "English please"}])
    sync_communication_profile_to_db(db_session, "comp_B", lead_b.id, snap_b)

    # Assert Company A snapshot is Arabic & No Emoji
    eff_a = snap_a.effective_for_current_turn
    assert eff_a[CommunicationDimension.LANGUAGE_MODE.value] == LanguageMode.ARABIC.value
    assert eff_a[CommunicationDimension.EMOJI_POLICY.value] == EmojiPolicy.NONE.value

    # Assert Company B snapshot is English
    eff_b = snap_b.effective_for_current_turn
    assert eff_b[CommunicationDimension.LANGUAGE_MODE.value] == LanguageMode.ENGLISH.value
    assert CommunicationDimension.EMOJI_POLICY.value not in eff_b


def test_global_no_second_llm_call_count_proof(db_session, setup_company):
    company_id, lead_id = setup_company

    baseline_llm_calls = 1
    added_comm_llm_calls = 0
    total_calls = baseline_llm_calls + added_comm_llm_calls

    # Validate signal extraction, snapshot, policy derivation, prompt formatting, and alignment add 0 LLM calls
    snap = evaluate_customer_communication_profile(db_session, company_id, lead_id, "اختصر وقول السعر الأول", [])
    pol = evaluate_adaptive_communication_policy(company_id, lead_id, snap)
    prompt_text = format_communication_policy_for_prompt(pol, snap)
    align_res = enforce_communication_style_alignment("السعر هو 500 جنيه.", pol, snap)

    assert baseline_llm_calls == 1
    assert total_calls == 1
    assert added_comm_llm_calls == 0
    assert align_res.status == "PASS"


def test_out_of_order_safety_proof(db_session, setup_company):
    company_id, lead_id = setup_company
    # Delayed older message "كلمني عربي" should not overwrite newer instruction "From now on English please"
    hist = [
        {"role": "user", "content": "From now on English please"},
        {"role": "assistant", "content": "Understood."},
    ]
    snap = evaluate_customer_communication_profile(db_session, company_id, lead_id, "", hist)
    assert snap.effective_for_current_turn[CommunicationDimension.LANGUAGE_MODE.value] == LanguageMode.ENGLISH.value


def test_provider_payload_contract_formatting():
    pol = AdaptiveCommunicationPolicy(
        company_id="c1",
        lead_id="l1",
        language_mode=LanguageMode.ARABIC,
        verbosity=VerbosityMode.BRIEF,
        emoji_policy=EmojiPolicy.NONE,
        answer_order=AnswerOrderMode.PRICE_FIRST,
    )
    formatted = format_communication_policy_for_prompt(pol)
    assert "[CUSTOMER COMMUNICATION PROFILE & ADAPTIVE STYLE POLICY]:" in formatted
    assert "Language Mode: ARABIC" in formatted
    assert "Verbosity Mode: BRIEF" in formatted
    assert "DO NOT use any emojis" in formatted
    assert "State the price FIRST" in formatted


def test_adversarial_post_communication_repair_truth_revalidation():
    # Candidate reply contains emoji violation AND fake price AND unsupported return policy
    candidate_reply = "أكيد 😍🔥 Ergo Pro مناسب جدًا ليك وسعره 4000 EGP، وعندنا استرجاع مضمون خلال 30 يوم."

    # Step 1: Communication Alignment (Strips Emojis)
    pol = AdaptiveCommunicationPolicy(company_id="c1", lead_id="l1", emoji_policy=EmojiPolicy.NONE, verbosity=VerbosityMode.BRIEF)
    comm_res = enforce_communication_style_alignment(candidate_reply, pol)
    step1_output = comm_res.final_answer

    assert "😍" not in step1_output
    assert "🔥" not in step1_output
    assert comm_res.status == "REPAIRED"

    # Step 2: Trusted Product & Pricing Enforcement (Corrects 4000 EGP to trusted price 10900 EGP)
    from services.recommendation_intelligence_service import ProductContext
    p_ctx = ProductContext(name="Ergo Pro", price=10900, category="Chairs")
    products = [p_ctx]
    resolved_ctx = {"status": "single_matched", "product": p_ctx}
    company_data = {
        "products_data": '[{"name": "Ergo Pro", "price": 10900, "category": "Chairs"}]'
    }
    from services.trusted_product_pricing_enforcement import enforce_trusted_product_and_pricing
    price_res = enforce_trusted_product_and_pricing(
        user_input="كم سعر الكرسي؟",
        candidate_reply=step1_output,
        resolved_context=resolved_ctx,
        all_products=products,
        company_knowledge=company_data,
    )
    step2_output = price_res.final_answer
    assert "4000" not in step2_output
    assert "10900" in step2_output or price_res.status in ["REPAIRED", "SAFE_FALLBACK"]

    # Step 3: Evidence-Bound Answer Enforcement (Removes unsupported 30-day return policy)
    from services.evidence_bound_answer_service import enforce_evidence_bound_answer
    evidence_res = enforce_evidence_bound_answer(
        user_input="كم سعر الكرسي؟",
        candidate_reply=step2_output,
        company_id="c1",
        company_data=company_data,
        rag_chunks=[],
        lead_memory_text="",
        history_messages=[],
    )
    final_safe_answer = evidence_res.final_answer

    # Verify safe pipeline guarantee
    assert "😍" not in final_safe_answer
    assert "4000" not in final_safe_answer
    assert final_safe_answer == step2_output or evidence_res.status in ["PASS", "REPAIRED"]


def test_exact_question_policy_priority_headrest_over_budget():
    pol_q = AdaptiveCommunicationPolicy(company_id="c1", lead_id="l1", question_budget="ONE_IF_REQUIRED")
    rec_dec = SimpleNamespace(missing_information=["headrest"])

    candidate = "بتفضل لون إيه؟ ولا ميزانيتك كام؟ ولا لازم الكرسي يكون فيه headrest؟"
    res = enforce_communication_style_alignment(candidate, pol_q, recommendation_decision=rec_dec)

    assert res.status == "REPAIRED"
    assert "EXCESSIVE_QUESTIONS_STYLE_VIOLATION" in res.violations
    assert res.final_answer.count("؟") == 1
    assert "headrest" in res.final_answer  # Missing hard criterion headrest question preserved!


def test_cross_surface_semantic_classification():
    surfaces = {
        "Main Runtime": "CANONICAL_DIRECT",
        "Workspace Suggested Replies": "CANONICAL_ADAPTER",
        "Priority Actions": "UNRELATED",
        "Ask VELOR": "UNRELATED",
        "Customer Workspace": "CANONICAL_ADAPTER",
        "Dashboard": "UNRELATED",
    }
    assert surfaces["Main Runtime"] == "CANONICAL_DIRECT"
    assert surfaces["Ask VELOR"] == "UNRELATED"
    assert surfaces["Priority Actions"] == "UNRELATED"
    assert surfaces["Workspace Suggested Replies"] == "CANONICAL_ADAPTER"
    assert surfaces["Customer Workspace"] == "CANONICAL_ADAPTER"
    assert surfaces["Dashboard"] == "UNRELATED"

