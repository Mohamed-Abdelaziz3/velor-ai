import pytest
import json
from sqlalchemy.orm import Session
from database import Company, CompanyKnowledge, Lead, LeadMemory
from services.dialogue_continuity import (
    resolve_dialogue_continuity,
    DialogueAct,
    ExpectedAnswerType,
    derive_pending_question,
    normalize_arabic_text
)
from services.velor_chat_v2 import get_v2_ai_response
from tests.test_velor_chat_mvp import _seed_company, _seed_lead, _seed_message

TEST_PRODUCTS = """[
  {"name": "LiftDesk Electric 120", "category": "مكاتب كهربائية", "price": 19900, "currency": "EGP", "sku": "LD-120", "description": "مكتب كهربائي متحرك ذكي"},
  {"name": "Arvena Ergo One", "category": "كراسي مكتبية", "price": 6900, "currency": "EGP", "sku": "AE-ONE", "description": "كرسي طبي مريح للظهر"}
]"""

@pytest.fixture
def seed_data(db):
    company = _seed_company(db, products_data=TEST_PRODUCTS)
    company.is_web_chat_enabled = True
    # Configure custom assistant prompt
    kb = db.query(CompanyKnowledge).filter(CompanyKnowledge.company_id == company.company_id).first()
    if kb:
        kb.system_prompt = "You are a sales agent. Always capture phone numbers early!"
        kb.knowledge_base = "سياسة الاسترجاع المعتمدة هي خلال 14 يوماً من الاستلام. التوصيل مجاني لجميع الكراسي."
        db.commit()
    lead = _seed_lead(db, company.company_id, phone="wc_v_testuser123")
    return company, lead

# ────────────────────────────────────────────────────────
# 1. Parameterized Dialogue Act Classifications (80 Cases)
# ────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "input_text,expected_act,expected_budget",
    [
        # Greetings (10 Cases)
        ("أهلاً", DialogueAct.GREETING, None),
        ("اهلاً", DialogueAct.GREETING, None),
        ("السلام عليكم", DialogueAct.GREETING, None),
        ("مساء الخير", DialogueAct.GREETING, None),
        ("صباح النور", DialogueAct.GREETING, None),
        ("مرحبا", DialogueAct.GREETING, None),
        ("هاي", DialogueAct.GREETING, None),
        ("يا هلا", DialogueAct.GREETING, None),
        ("سلام عليكم", DialogueAct.GREETING, None),
        ("صباح الخير", DialogueAct.GREETING, None),
        
        # Acknowledgements (10 Cases)
        ("تمام", DialogueAct.ACKNOWLEDGEMENT, None),
        ("ماشي", DialogueAct.ACKNOWLEDGEMENT, None),
        ("حاضر", DialogueAct.ACKNOWLEDGEMENT, None),
        ("أوكي", DialogueAct.ACKNOWLEDGEMENT, None),
        ("شكرا", DialogueAct.ACKNOWLEDGEMENT, None),
        ("شكراً", DialogueAct.ACKNOWLEDGEMENT, None),
        ("تسلم", DialogueAct.ACKNOWLEDGEMENT, None),
        ("اوكي", DialogueAct.ACKNOWLEDGEMENT, None),
        ("مفهوم", DialogueAct.ACKNOWLEDGEMENT, None),
        ("علم", DialogueAct.ACKNOWLEDGEMENT, None),
        
        # Negatives (10 Cases)
        ("لا", DialogueAct.NO, None),
        ("لأ", DialogueAct.NO, None),
        ("مش عايز", DialogueAct.NO, None),
        ("لا شكرا", DialogueAct.NO, None),
        ("ابدا", DialogueAct.NO, None),
        ("أبداً", DialogueAct.NO, None),
        ("مرفوض", DialogueAct.NO, None),
        ("لأ شكرا", DialogueAct.NO, None),
        ("لا مش حابب", DialogueAct.NO, None),
        ("بلاش", DialogueAct.NO, None),
        
        # Continuations (10 Cases)
        ("كمل", DialogueAct.CONTINUE, None),
        ("قولي تاني", DialogueAct.CONTINUE, None),
        ("إيه كمان", DialogueAct.CONTINUE, None),
        ("ايه كمان", DialogueAct.CONTINUE, None),
        ("استمر", DialogueAct.CONTINUE, None),
        ("وبعدين", DialogueAct.CONTINUE, None),
        ("توضيح اكتر", DialogueAct.CONTINUE, None),
        ("كمل شرح", DialogueAct.CONTINUE, None),
        ("قولي المزيد", DialogueAct.CONTINUE, None),
        ("تابع", DialogueAct.CONTINUE, None),
        
        # Ordinal References (10 Cases)
        ("الأول", DialogueAct.PRODUCT_SELECTION, None),
        ("التاني", DialogueAct.PRODUCT_SELECTION, None),
        ("الأولى", DialogueAct.PRODUCT_SELECTION, None),
        ("التانية", DialogueAct.PRODUCT_SELECTION, None),
        ("الثاني", DialogueAct.PRODUCT_SELECTION, None),
        ("الخيار الأول", DialogueAct.PRODUCT_SELECTION, None),
        ("الخيار التاني", DialogueAct.PRODUCT_SELECTION, None),
        ("الاختيار الاول", DialogueAct.PRODUCT_SELECTION, None),
        ("الاختيار التاني", DialogueAct.PRODUCT_SELECTION, None),
        ("التانى", DialogueAct.PRODUCT_SELECTION, None),
        
        # Price References (10 Cases)
        ("اللي بـ6900", DialogueAct.PRODUCT_REFERENCE, None),
        ("اللي بـ 19900", DialogueAct.PRODUCT_REFERENCE, None),
        ("عايز ابو 6900", DialogueAct.PRODUCT_REFERENCE, None),
        ("مواصفات اللي بـ6900 جنيه", DialogueAct.PRODUCT_REFERENCE, None),
        ("ابو 19900 جنيه", DialogueAct.PRODUCT_REFERENCE, None),
        ("اللي بـ 7000", DialogueAct.PRODUCT_REFERENCE, None),
        ("ابو 7000", DialogueAct.PRODUCT_REFERENCE, None),
        ("عايز اللي بـ6900", DialogueAct.PRODUCT_REFERENCE, None),
        ("قولي مواصفات ابو 6900", DialogueAct.PRODUCT_REFERENCE, None),
        ("اللي بـ19900", DialogueAct.PRODUCT_REFERENCE, None),
        
        # Budget Values (10 Cases)
        ("معايا 7000", DialogueAct.BUDGET, 7000.0),
        ("ميزانيتي 5000 جنيه", DialogueAct.BUDGET, 5000.0),
        ("اخري 6000", DialogueAct.BUDGET, 6000.0),
        ("الحد الأقصى 8000 جنيه", DialogueAct.BUDGET, 8000.0),
        ("ميزانيتي لحد 7000 EGP", DialogueAct.BUDGET, 7000.0),
        ("معايا 6000 جنيه", DialogueAct.BUDGET, 6000.0),
        ("سقف الميزانية 5000", DialogueAct.BUDGET, 5000.0),
        ("مش هقدر ادفع اكتر من 6000", DialogueAct.BUDGET, 6000.0),
        ("ميزانيتي 7000", DialogueAct.BUDGET, 7000.0),
        ("اخري 5000 جنيه", DialogueAct.BUDGET, 5000.0),
        
        # Ambiguous Disjunctive option answers (10 Cases)
        ("اه", DialogueAct.UNRESOLVED_DIALOGUE, None),
        ("ايوه", DialogueAct.UNRESOLVED_DIALOGUE, None),
        ("أيوه", DialogueAct.UNRESOLVED_DIALOGUE, None),
        ("نعم", DialogueAct.UNRESOLVED_DIALOGUE, None),
        ("أكيد", DialogueAct.UNRESOLVED_DIALOGUE, None),
        ("اكيد", DialogueAct.UNRESOLVED_DIALOGUE, None),
        ("بالظبط", DialogueAct.UNRESOLVED_DIALOGUE, None),
        ("فعلا", DialogueAct.UNRESOLVED_DIALOGUE, None),
        ("طبعا", DialogueAct.UNRESOLVED_DIALOGUE, None),
        ("يب", DialogueAct.UNRESOLVED_DIALOGUE, None)
    ]
)
def test_dialogue_act_classification_scenarios(db: Session, seed_data, input_text, expected_act, expected_budget):
    company, lead = seed_data
    
    # Clear any previous pending questions
    lead.pending_question = None
    db.commit()
    db.refresh(lead)
    
    # Seed a pending question if testing yes/no/ambiguous disjunctive options
    if expected_act in (DialogueAct.UNRESOLVED_DIALOGUE, DialogueAct.YES, DialogueAct.NO):
        pq = {
            "question_id": "q-test-disj",
            "question_type": "GREETING",
            "expected_answer_type": ExpectedAnswerType.ONE_OF_OPTIONS if expected_act == DialogueAct.UNRESOLVED_DIALOGUE else ExpectedAnswerType.YES_NO,
            "options": ["تعرف عن منتج معين", "أساعدك تختار"] if expected_act == DialogueAct.UNRESOLVED_DIALOGUE else None,
            "resolved": False
        }
        lead.pending_question = json.dumps(pq)
        db.commit()
        db.refresh(lead)
        
    res = resolve_dialogue_continuity(db, lead, input_text)
    
    if expected_act == DialogueAct.UNRESOLVED_DIALOGUE:
        assert res["clarification_needed"] is True
    else:
        assert res["dialogue_act"] == expected_act
        
    if expected_budget is not None:
        assert res["resolved_budget"] == expected_budget

# ────────────────────────────────────────────────────────
# 2. Bounded Lead/Tenant Isolation Verification Cases (3 Cases)
# ────────────────────────────────────────────────────────

def test_tenant_isolation_pending_question(db: Session, seed_data):
    """Verify that pending question updates of one tenant/lead do not leak to another."""
    company_a, lead_a = seed_data
    
    # Create another company and lead using seed helper to avoid manual keyword errors
    company_b = _seed_company(db, company_id="tenant_b_test")
    lead_b = _seed_lead(db, company_b.company_id, name="Lead B", phone="wc_v_testuser_b")
    
    # Set pending question on lead_a
    pq_a = {
        "question_id": "q-lead-a",
        "question_type": "GREETING",
        "expected_answer_type": ExpectedAnswerType.ONE_OF_OPTIONS,
        "options": ["Option A", "Option B"],
        "resolved": False
    }
    lead_a.pending_question = json.dumps(pq_a)
    lead_b.pending_question = None
    db.commit()
    
    # Resolve dialogue continuity on lead_b with "اه"
    res_b = resolve_dialogue_continuity(db, lead_b, "اه")
    assert res_b["clarification_needed"] is False  # No pending question for lead_b
    
    # Resolve dialogue continuity on lead_a with "اه"
    res_a = resolve_dialogue_continuity(db, lead_a, "اه")
    assert res_a["clarification_needed"] is True  # Triggers clarification for lead_a
    
    # Clean up lead_b
    db.delete(lead_b)
    db.delete(company_b)
    db.commit()


def test_tenant_isolation_budget_update(db: Session, seed_data):
    """Verify that budget updates for one lead do not affect other leads or companies."""
    company_a, lead_a = seed_data
    
    # Create lead_b
    lead_b = Lead(company_id=company_a.company_id, name="Lead B")
    db.add(lead_b)
    db.commit()
    
    # Send budget message for lead_a
    res_a = resolve_dialogue_continuity(db, lead_a, "ميزانيتي لحد 5000 جنيه")
    assert res_a["resolved_budget"] == 5000.0
    
    # Validate lead_b budget memory remains unchanged
    mem_b = db.query(LeadMemory).filter(LeadMemory.lead_id == lead_b.id).first()
    assert mem_b is None
    
    # Clean up
    db.delete(lead_b)
    db.commit()


def test_arabic_normalization_robustness():
    """Verify normalize_arabic_text handles colloquial text correctly."""
    assert normalize_arabic_text("أهلاً بك") == "اندا بك" or normalize_arabic_text("أهلاً بك") == "اهلا بك"
    assert normalize_arabic_text("لأ مش عايز") == "لا مش عايز"
    assert normalize_arabic_text("آيوه") == "ايوه"


@pytest.mark.asyncio
async def test_dialogue_continuity_disjunctive_defect(db: Session, seed_data):
    """Verify that replying 'اه' to a disjunctive greeting option triggers clarification."""
    company, lead = seed_data
    
    # 1. Seed a pending disjunctive greeting option question from the assistant
    pq = {
        "question_id": "q-greeting-disj",
        "question_type": "GREETING",
        "expected_answer_type": ExpectedAnswerType.ONE_OF_OPTIONS,
        "options": ["تعرف عن منتج معين", "أساعدك تختار الأنسب"],
        "resolved": False
    }
    lead.pending_question = json.dumps(pq)
    db.commit()
    db.refresh(lead)
    
    # 2. Simulate customer message "اه"
    msg = _seed_message(db, company.company_id, lead, "اه", sender="user")
    
    # 3. Call get_v2_ai_response and assert response
    res = await get_v2_ai_response(db, msg, company, lead)
    
    assert res["response_path"] == "DIALOGUE_CONTINUITY"
    assert "تمام، تحب" in res["answer_text"]
    assert "تعرف عن منتج معين ولا أساعدك تختار الأنسب" in res["answer_text"]
    
    # Verify the question remains unresolved (since clarification is pending)
    db.refresh(lead)
    pq_after = json.loads(lead.pending_question)
    assert pq_after["resolved"] is False

