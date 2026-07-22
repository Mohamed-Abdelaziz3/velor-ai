import json
from pathlib import Path

from services.velor_chat_v2 import infer_language_profile


def test_phase_3d_quality_corpus_is_complete_and_structured():
    corpus_path = Path(__file__).parent / "fixtures" / "phase_3d_conversation_quality.json"
    cases = json.loads(corpus_path.read_text(encoding="utf-8"))

    assert len(cases) >= 40
    assert len({case["id"] for case in cases}) == len(cases)
    assert all(case.get("input") and case.get("expect") for case in cases)


def test_phase_3d_coverage_is_superseded_by_the_rich_phase_4_quality_contract():
    corpus_path = Path(__file__).parent / "fixtures" / "phase_4_conversation_quality.json"
    cases = json.loads(corpus_path.read_text(encoding="utf-8"))

    semantic_fields = {
        "facts_required",
        "facts_forbidden",
        "products_allowed",
        "products_forbidden",
        "budget_rule",
        "contact_gate",
        "required_intent",
        "language",
        "register",
        "max_products",
        "max_questions",
        "unknown_handling",
        "response_length",
    }
    assert len(cases) >= 110
    assert all(semantic_fields.issubset(case) for case in cases)


def test_response_language_profiles_cover_required_registers():
    assert infer_language_profile("عايز كرسي للشغل")[1] == "EGYPTIAN_COLLOQUIAL"
    assert infer_language_profile("هل تتوفر كراسي مكتبية؟")[1] == "MODERN_STANDARD_ARABIC"
    assert infer_language_profile("Do you have office chairs?")[1] == "ENGLISH"
    assert infer_language_profile("عايز chair تحت 7000")[1] == "MIXED_ARABIC_ENGLISH"
    assert infer_language_profile("ana 3ayez korsi")[1] == "ARABIZI"
