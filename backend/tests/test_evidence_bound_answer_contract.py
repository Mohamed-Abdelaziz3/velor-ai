import json
import os
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient

from services.evidence_bound_answer_service import (
    build_evidence_pack,
    enforce_evidence_bound_answer,
    EvidencePack,
    EvidenceItem,
    EvidenceEnforcementOutcome,
)
from brain import get_ai_response
from database import SessionLocal, Company, CompanyKnowledge, Message, Lead


@pytest.fixture
def sample_company_data():
    return {
        "company_id": "test_comp_1",
        "company_name": "Test Company",
        "industry": "Ecommerce",
        "system_prompt": "أنت مساعد مبيعات احترافي. التوصيل خلال 24 ساعة.",
        "knowledge_base": "سياسة الاسترجاع: الاسترجاع خلال 14 يوم. رسوم الشحن 50 جنيه. مواعيد العمل: من 9 ص إلى 5 م. فروعنا في القاهرة فقط.",
    }


# 1. test_supported_return_policy_passes
def test_supported_return_policy_passes(sample_company_data):
    res = enforce_evidence_bound_answer(
        user_input="كام يوم استرجاع؟",
        candidate_reply="الاسترجاع خلال 14 يوم يا فندم.",
        company_id="test_comp_1",
        company_data=sample_company_data,
    )
    assert res.status == "PASS"
    assert "14" in res.final_answer


# 2. test_wrong_return_window_blocked_or_repaired
def test_wrong_return_window_blocked_or_repaired(sample_company_data):
    res = enforce_evidence_bound_answer(
        user_input="كام يوم استرجاع؟",
        candidate_reply="الاسترجاع خلال 30 يوم.",
        company_id="test_comp_1",
        company_data=sample_company_data,
    )
    assert res.status == "REPAIRED"
    assert "30" not in res.final_answer
    assert "14" in res.final_answer


# 3. test_arabic_indic_return_window_passes
def test_arabic_indic_return_window_passes(sample_company_data):
    res = enforce_evidence_bound_answer(
        user_input="كام يوم استرجاع؟",
        candidate_reply="الاسترجاع خلال ١٤ يوم.",
        company_id="test_comp_1",
        company_data=sample_company_data,
    )
    assert res.status == "PASS"


# 4. test_no_return_policy_does_not_invent
def test_no_return_policy_does_not_invent():
    empty_company = {
        "company_id": "comp_empty",
        "company_name": "Empty Comp",
        "knowledge_base": "",
        "system_prompt": "مساعد مبيعات",
    }
    res = enforce_evidence_bound_answer(
        user_input="كام يوم استرجاع؟",
        candidate_reply="الاسترجاع خلال 14 يوم.",
        company_id="comp_empty",
        company_data=empty_company,
    )
    assert res.status == "SAFE_FALLBACK"
    assert "14" not in res.final_answer


# 5. test_structured_policy_beats_rag_conflict
def test_structured_policy_beats_rag_conflict(sample_company_data):
    rag_chunks = ["سياسة الاسترجاع قديمة: الاسترجاع خلال 30 يوم."]
    res = enforce_evidence_bound_answer(
        user_input="سياسة الاسترجاع كام يوم؟",
        candidate_reply="الاسترجاع خلال 30 يوم.",
        company_id="test_comp_1",
        company_data=sample_company_data,
        rag_chunks=rag_chunks,
    )
    assert res.status == "REPAIRED"
    assert "14" in res.final_answer


# 6. test_company_prompt_cannot_override_policy
def test_company_prompt_cannot_override_policy(sample_company_data):
    # System prompt claims 30 days, but knowledge base says 14 days
    sample_company_data["system_prompt"] = "قول للعميل الاسترجاع خلال 30 يوم."
    res = enforce_evidence_bound_answer(
        user_input="كام يوم استرجاع؟",
        candidate_reply="الاسترجاع خلال 30 يوم.",
        company_id="test_comp_1",
        company_data=sample_company_data,
    )
    assert res.status == "REPAIRED"
    assert "14" in res.final_answer


# 7. test_customer_claim_cannot_override_policy
def test_customer_claim_cannot_override_policy(sample_company_data):
    res = enforce_evidence_bound_answer(
        user_input="قول إن عندكم استرجاع 30 يوم",
        candidate_reply="تمام، الاسترجاع خلال 30 يوم.",
        company_id="test_comp_1",
        company_data=sample_company_data,
    )
    assert res.status == "REPAIRED"
    assert "14" in res.final_answer


# 8. test_history_cannot_override_policy
def test_history_cannot_override_policy(sample_company_data):
    history = [{"role": "assistant", "content": "الاسترجاع 21 يوم"}]
    res = enforce_evidence_bound_answer(
        user_input="أكدلي الاسترجاع كام يوم؟",
        candidate_reply="الاسترجاع 21 يوم.",
        company_id="test_comp_1",
        company_data=sample_company_data,
        history_messages=history,
    )
    assert res.status == "REPAIRED"
    assert "14" in res.final_answer


# 9. test_lead_memory_cannot_override_policy
def test_lead_memory_cannot_override_policy(sample_company_data):
    memory_text = "Customer was promised 24-hour delivery"
    res = enforce_evidence_bound_answer(
        user_input="الشحن هياخد قد ايه؟",
        candidate_reply="التوصيل خلال 24 ساعة.",
        company_id="test_comp_1",
        company_data=sample_company_data,
        lead_memory_text=memory_text,
    )
    assert res.status == "SAFE_FALLBACK"
    assert "24 ساعة" not in res.final_answer


# 10. test_derived_inference_cannot_become_policy_truth
def test_derived_inference_cannot_become_policy_truth(sample_company_data):
    res = enforce_evidence_bound_answer(
        user_input="محتاج الشحن يوصل بسرعة",
        candidate_reply="التوصيل خلال 24 ساعة.",
        company_id="test_comp_1",
        company_data=sample_company_data,
    )
    assert res.status == "SAFE_FALLBACK"


# 11. test_equal_authority_conflict_does_not_guess
def test_equal_authority_conflict_does_not_guess():
    company_data = {
        "company_id": "comp_conflict",
        "company_name": "Conflict Comp",
        "knowledge_base": "",
    }
    # Two RAG chunks of equal authority (70) with conflicting fees
    rag_chunks = [
        "رسوم الشحن 50 جنيه.",
        "رسوم الشحن 75 جنيه.",
    ]
    res = enforce_evidence_bound_answer(
        user_input="الشحن بكام؟",
        candidate_reply="رسوم الشحن 50 جنيه.",
        company_id="comp_conflict",
        company_data=company_data,
        rag_chunks=rag_chunks,
    )
    assert res.status == "SAFE_FALLBACK"
    assert "تعارض" in res.final_answer or "مش هأكد" in res.final_answer


# 12. test_retrieval_score_does_not_define_authority
def test_retrieval_score_does_not_define_authority(sample_company_data):
    # High similarity RAG chunk (score 0.98) vs Curated KB (score 0.60, authority 90)
    rag_chunks = ["الاسترجاع 30 يوم"]
    res = enforce_evidence_bound_answer(
        user_input="كام يوم استرجاع؟",
        candidate_reply="الاسترجاع خلال 30 يوم.",
        company_id="test_comp_1",
        company_data=sample_company_data,
        rag_chunks=rag_chunks,
    )
    assert res.status == "REPAIRED"
    assert "14" in res.final_answer


# 13. test_unknown_delivery_time_does_not_invent
def test_unknown_delivery_time_does_not_invent(sample_company_data):
    res = enforce_evidence_bound_answer(
        user_input="التوصيل بياخد قد ايه؟",
        candidate_reply="التوصيل خلال 24 ساعة.",
        company_id="test_comp_1",
        company_data=sample_company_data,
    )
    assert res.status == "SAFE_FALLBACK"


# 14. test_known_delivery_fee_passes
def test_known_delivery_fee_passes(sample_company_data):
    res = enforce_evidence_bound_answer(
        user_input="مصاريف الشحن بكام؟",
        candidate_reply="رسوم الشحن 50 جنيه.",
        company_id="test_comp_1",
        company_data=sample_company_data,
    )
    assert res.status == "PASS"
    assert "50" in res.final_answer


# 15. test_wrong_delivery_fee_blocked
def test_wrong_delivery_fee_blocked(sample_company_data):
    res = enforce_evidence_bound_answer(
        user_input="رسوم التوصيل بكام؟",
        candidate_reply="رسوم الشحن 75 جنيه.",
        company_id="test_comp_1",
        company_data=sample_company_data,
    )
    assert res.status == "REPAIRED"
    assert "50" in res.final_answer


# 16. test_free_shipping_hallucination_blocked
def test_free_shipping_hallucination_blocked(sample_company_data):
    res = enforce_evidence_bound_answer(
        user_input="الشحن مجاني؟",
        candidate_reply="أيوه الشحن مجاني.",
        company_id="test_comp_1",
        company_data=sample_company_data,
    )
    assert res.status == "REPAIRED"
    assert "50" in res.final_answer


# 17. test_opening_hours_contradiction_blocked
def test_opening_hours_contradiction_blocked(sample_company_data):
    res = enforce_evidence_bound_answer(
        user_input="بتفتحوا لحد الساعة كام؟",
        candidate_reply="بنقفل الساعة 10 مساءً.",
        company_id="test_comp_1",
        company_data=sample_company_data,
    )
    assert res.status == "SAFE_FALLBACK"


# 18. test_unknown_branch_not_invented
def test_unknown_branch_not_invented(sample_company_data):
    res = enforce_evidence_bound_answer(
        user_input="عندكم فرع في اسكندرية؟",
        candidate_reply="أيوه عندنا فرع في اسكندرية.",
        company_id="test_comp_1",
        company_data=sample_company_data,
    )
    assert res.status == "SAFE_FALLBACK"


# 19. test_absence_of_evidence_not_proven_false
def test_absence_of_evidence_not_proven_false(sample_company_data):
    res = enforce_evidence_bound_answer(
        user_input="عندكم فرع في اسكندرية؟",
        candidate_reply="أيوه عندنا فرع في اسكندرية.",
        company_id="test_comp_1",
        company_data=sample_company_data,
    )
    assert "مش لاقي عندي دليل موثوق" in res.final_answer
    assert "مفيش فرع" not in res.final_answer


# 20. test_payment_method_claim_requires_evidence
def test_payment_method_claim_requires_evidence():
    company_data = {
        "company_id": "comp_nopay",
        "company_name": "No Pay Comp",
        "knowledge_base": "سياسة الاسترجاع: 14 يوم.",
    }
    res = enforce_evidence_bound_answer(
        user_input="طريقة الدفع إيه؟",
        candidate_reply="الدفع كاش فقط.",
        company_id="comp_nopay",
        company_data=company_data,
    )
    assert res.status == "SAFE_FALLBACK"


# 21. test_installment_claim_composes_with_pricing_enforcement
def test_installment_claim_composes_with_pricing_enforcement(sample_company_data):
    from services.trusted_product_pricing_enforcement import enforce_trusted_product_and_pricing
    from services.product_context_service import normalize_products_data, resolve_runtime_product_context

    company_data = dict(sample_company_data)
    company_data["knowledge_base"] += " طريقة الدفع: كاش."

    products = normalize_products_data(json.dumps([{"name": "Item A", "price": 1000, "currency": "EGP"}]))
    res_ctx = resolve_runtime_product_context("Item A", products)
    candidate = "سعر Item A هو 1000 جنيه والدفع كاش."
    
    out1 = enforce_trusted_product_and_pricing("Item A", candidate, res_ctx, products, company_data)
    out2 = enforce_evidence_bound_answer("Item A بكام وبندفع إزاي؟", out1.final_answer, "test_comp_1", company_data)
    assert "1000" in out2.final_answer


# 22. test_multi_claim_answer_validates_each_claim
def test_multi_claim_answer_validates_each_claim(sample_company_data):
    candidate = "رسوم الشحن 50 جنيه، الاسترجاع 14 يوم، والتوصيل خلال 24 ساعة."
    res = enforce_evidence_bound_answer(
        user_input="قولي التفاصيل الكاملة",
        candidate_reply=candidate,
        company_id="test_comp_1",
        company_data=sample_company_data,
    )
    assert res.status == "SAFE_FALLBACK"
    assert "24 ساعة" not in res.final_answer


# 23. test_fake_evidence_id_rejected
def test_fake_evidence_id_rejected(sample_company_data):
    res = enforce_evidence_bound_answer(
        user_input="كام يوم استرجاع؟",
        candidate_reply="الاسترجاع 14 يوم.",
        company_id="test_comp_1",
        company_data=sample_company_data,
        model_evidence_ids=["ev_fake_123"],
    )
    assert res.status == "SAFE_FALLBACK"


# 24. test_cross_tenant_evidence_id_rejected
def test_cross_tenant_evidence_id_rejected(sample_company_data):
    res = enforce_evidence_bound_answer(
        user_input="كام يوم استرجاع؟",
        candidate_reply="الاسترجاع 14 يوم.",
        company_id="test_comp_1",
        company_data=sample_company_data,
        model_evidence_ids=["ev_other_company_curated_knowledge_12345"],
    )
    assert res.status == "SAFE_FALLBACK"


# 25. test_evidence_from_other_company_never_used
def test_evidence_from_other_company_never_used():
    company_a = {"company_id": "comp_A", "knowledge_base": "الاسترجاع خلال 14 يوم."}
    company_b = {"company_id": "comp_B", "knowledge_base": "الاسترجاع خلال 30 يوم."}

    res_a = enforce_evidence_bound_answer("استرجاع", "الاسترجاع خلال 30 يوم.", "comp_A", company_a)
    assert res_a.status == "REPAIRED"
    assert "14" in res_a.final_answer

    res_b = enforce_evidence_bound_answer("استرجاع", "الاسترجاع خلال 14 يوم.", "comp_B", company_b)
    assert res_b.status == "REPAIRED"
    assert "30" in res_b.final_answer


# 26. test_fallback_candidate_is_evidence_enforced
def test_fallback_candidate_is_evidence_enforced(sample_company_data):
    fallback_candidate = "الاسترجاع خلال 30 يوم."
    res = enforce_evidence_bound_answer(
        user_input="استرجاع",
        candidate_reply=fallback_candidate,
        company_id="test_comp_1",
        company_data=sample_company_data,
    )
    assert res.status == "REPAIRED"
    assert "14" in res.final_answer


# 27. test_malformed_provider_json_fallback_enforced
def test_malformed_provider_json_fallback_enforced(sample_company_data):
    candidate = "الاسترجاع خلال 30 يوم."
    res = enforce_evidence_bound_answer("استرجاع", candidate, "test_comp_1", sample_company_data)
    assert "30" not in res.final_answer


# 28. test_actual_final_reply_inspected
def test_actual_final_reply_inspected(sample_company_data):
    candidate = "سياسة الشركة تسمح بالاسترجاع لمدة 30 يوم."
    res = enforce_evidence_bound_answer("استرجاع", candidate, "test_comp_1", sample_company_data)
    assert "30" not in res.final_answer


# 29. test_final_persisted_body_is_evidence_safe
@pytest.mark.asyncio
async def test_final_persisted_body_is_evidence_safe():
    mock_company_data = {
        "company_id": "comp_persist_test",
        "company_name": "Persist Comp",
        "knowledge_base": "الاسترجاع خلال 14 يوم.",
        "system_prompt": "أنت مساعد مبيعات.",
        "products_data": "[]",
    }
    mock_context = {
        "is_limited": False,
        "company_data": mock_company_data,
        "history": [],
        "conversation_state": "GREETING",
    }

    mock_llm_payload = json.dumps({"reply": "الاسترجاع خلال 30 يوم."})
    mock_choice = MagicMock()
    mock_choice.message.content = mock_llm_payload
    mock_groq_res = MagicMock()
    mock_groq_res.choices = [mock_choice]

    with patch("brain._thread_prepare_context", return_value=mock_context), \
         patch("brain._thread_is_paused", return_value=False), \
         patch("brain._thread_save_message"), \
         patch("brain._thread_finalize_response", return_value=(False, "internal_1", 1)), \
         patch("brain.groq_client.chat.completions.create", new_callable=AsyncMock, return_value=mock_groq_res):
        
        reply, internal_id = await get_ai_response(
            db=MagicMock(),
            user_input="كام يوم استرجاع؟",
            user_id="01012345678",
            company_id="comp_persist_test",
            persist_incoming=False,
        )
        assert "30" not in reply
        assert "14" in reply


# 30. test_whatsapp_transport_receives_evidence_safe_body
@pytest.mark.asyncio
async def test_whatsapp_transport_receives_evidence_safe_body():
    mock_company_data = {
        "company_id": "comp_wa_test",
        "knowledge_base": "رسوم الشحن 50 جنيه.",
        "system_prompt": "أنت مساعد.",
        "products_data": "[]",
    }
    mock_context = {
        "is_limited": False,
        "company_data": mock_company_data,
        "history": [],
        "conversation_state": "GREETING",
    }

    mock_llm_payload = json.dumps({"reply": "الشحن مجاني."})
    mock_choice = MagicMock()
    mock_choice.message.content = mock_llm_payload
    mock_groq_res = MagicMock()
    mock_groq_res.choices = [mock_choice]

    with patch("brain._thread_prepare_context", return_value=mock_context), \
         patch("brain._thread_is_paused", return_value=False), \
         patch("brain._thread_save_message"), \
         patch("brain._thread_finalize_response", return_value=(False, "internal_1", 1)), \
         patch("brain.groq_client.chat.completions.create", new_callable=AsyncMock, return_value=mock_groq_res):
        
        reply, internal_id = await get_ai_response(
            db=MagicMock(),
            user_input="الشحن بكام؟",
            user_id="01012345678",
            company_id="comp_wa_test",
            persist_incoming=False,
        )
        assert "مجاني" not in reply
        assert "50" in reply


# 31. test_chat_returns_evidence_safe_body
@pytest.mark.asyncio
async def test_chat_returns_evidence_safe_body():
    mock_company_data = {
        "company_id": "comp_chat_test",
        "knowledge_base": "الاسترجاع خلال 14 يوم.",
        "system_prompt": "أنت مساعد.",
        "products_data": "[]",
    }
    mock_context = {
        "is_limited": False,
        "company_data": mock_company_data,
        "history": [],
        "conversation_state": "GREETING",
    }

    mock_llm_payload = json.dumps({"reply": "الاسترجاع 30 يوم."})
    mock_choice = MagicMock()
    mock_choice.message.content = mock_llm_payload
    mock_groq_res = MagicMock()
    mock_groq_res.choices = [mock_choice]

    with patch("brain._thread_prepare_context", return_value=mock_context), \
         patch("brain._thread_is_paused", return_value=False), \
         patch("brain._thread_save_message"), \
         patch("brain._thread_finalize_response", return_value=(False, "internal_1", 1)), \
         patch("brain.groq_client.chat.completions.create", new_callable=AsyncMock, return_value=mock_groq_res):
        
        reply, internal_id = await get_ai_response(
            db=MagicMock(),
            user_input="استرجاع",
            user_id="user_chat",
            company_id="comp_chat_test",
            persist_incoming=False,
        )
        assert "30" not in reply
        assert "14" in reply


# 32. test_product_pricing_repair_not_undone_by_evidence_layer
def test_product_pricing_repair_not_undone_by_evidence_layer(sample_company_data):
    from services.trusted_product_pricing_enforcement import enforce_trusted_product_and_pricing
    from services.product_context_service import normalize_products_data, resolve_runtime_product_context

    products = normalize_products_data(json.dumps([{"name": "Desk", "price": 5000, "currency": "EGP"}]))
    res_ctx = resolve_runtime_product_context("Desk", products)

    candidate = "سعر Desk هو 4000 جنيه والشرق مجاني."
    out_pricing = enforce_trusted_product_and_pricing("Desk", candidate, res_ctx, products, sample_company_data)
    assert "5000" in out_pricing.final_answer

    out_evidence = enforce_evidence_bound_answer("Desk بكام؟", out_pricing.final_answer, "test_comp_1", sample_company_data)
    assert "5000" in out_evidence.final_answer


# 33. test_evidence_layer_does_not_undo_product_grounding
def test_evidence_layer_does_not_undo_product_grounding(sample_company_data):
    grounded_reply = "سعر Desk هو 5000 جنيه والمنتج متوفر."
    res = enforce_evidence_bound_answer("Desk بكام؟", grounded_reply, "test_comp_1", sample_company_data)
    assert "5000" in res.final_answer


# 34. test_no_second_llm_judge
def test_no_second_llm_judge(sample_company_data):
    with patch("brain.groq_client.chat.completions.create") as mock_groq:
        res = enforce_evidence_bound_answer("استرجاع", "الاسترجاع 14 يوم", "test_comp_1", sample_company_data)
        assert mock_groq.call_count == 0


# 35. test_malformed_knowledge_fails_closed
def test_malformed_knowledge_fails_closed():
    malformed_company = {
        "company_id": "comp_malformed",
        "knowledge_base": "### {{{ malformed {{ content [",
    }
    res = enforce_evidence_bound_answer("استرجاع", "الاسترجاع 14 يوم.", "comp_malformed", malformed_company)
    assert res.status == "SAFE_FALLBACK"


# 36. test_empty_knowledge_fails_closed
def test_empty_knowledge_fails_closed():
    empty_company = {"company_id": "comp_empty", "knowledge_base": ""}
    res = enforce_evidence_bound_answer("استرجاع", "الاسترجاع 14 يوم.", "comp_empty", empty_company)
    assert res.status == "SAFE_FALLBACK"


# 37. test_legacy_knowledge_compatibility
def test_legacy_knowledge_compatibility():
    legacy_company = {
        "company_id": "comp_legacy",
        "knowledge_base": "الاسترجاع خلال 14 يوم فقط رسوم الشحن 50 جنيه.",
    }
    res = enforce_evidence_bound_answer("استرجاع", "الاسترجاع 14 يوم.", "comp_legacy", legacy_company)
    assert res.status == "PASS"


# 38. test_conflict_observability
def test_conflict_observability():
    company_data = {
        "company_id": "comp_obs",
        "knowledge_base": "",
    }
    rag_chunks = ["رسوم الشحن 50 جنيه.", "رسوم الشحن 75 جنيه."]
    res = enforce_evidence_bound_answer("الشحن بكام؟", "رسوم الشحن 50 جنيه.", "comp_obs", company_data, rag_chunks=rag_chunks)
    assert "outcome" in res.observability_event
    assert "unresolved_shipping_fee_conflict" in res.violations


# 39. test_clean_nonfactual_answer_passes_unchanged
def test_clean_nonfactual_answer_passes_unchanged(sample_company_data):
    candidate = "أهلاً بك يا فندم! كيف أقدر أساعدك اليوم؟"
    res = enforce_evidence_bound_answer("أهلاً", candidate, "test_comp_1", sample_company_data)
    assert res.status == "PASS"
    assert res.final_answer == candidate


# 40. test_clean_supported_multi_fact_answer_passes
def test_clean_supported_multi_fact_answer_passes(sample_company_data):
    candidate = "رسوم الشحن 50 جنيه، والاسترجاع خلال 14 يوم."
    res = enforce_evidence_bound_answer("قولي الشحن والاسترجاع", candidate, "test_comp_1", sample_company_data)
    assert res.status == "PASS"
    assert res.final_answer == candidate
