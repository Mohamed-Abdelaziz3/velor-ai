import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

from services.conversation_quality_lab import (
    CASE_REQUIRED_FIELDS,
    evaluate_corpus,
    evaluate_response,
    load_corpus,
    validate_corpus,
)


BACKEND_DIR = Path(__file__).resolve().parents[1]
CORPUS_PATH = BACKEND_DIR / "tests" / "fixtures" / "phase_4_conversation_quality.json"


def _cases():
    return load_corpus(CORPUS_PATH)


def _case(case_id):
    return next(case for case in _cases() if case["id"] == case_id)


def _passing_budget_response():
    return {
        "answer_text": "في حدود 7000 EGP، Arvena Ergo One متاح بسعر 6900 EGP. تحب تعرف مواصفاته؟",
        "intent": "BUDGET_CONSTRAINT",
        "answered_latest": True,
        "language": "ar",
        "register": "EGYPTIAN_COLLOQUIAL",
        "fact_ids_used": ["budget:max:7000", "price:ergo-one:6900"],
        "facts": [
            {"fact_id": "budget:max:7000", "claim": "budget is 7000", "source_id": "message:26"},
            {"fact_id": "price:ergo-one:6900", "claim": "price is 6900", "source_id": "catalog:ergo-one"},
        ],
        "products": [{"name": "Arvena Ergo One", "price": 6900, "recommended": True, "compatible": True}],
        "selected_product": "Arvena Ergo One",
        "contact_request_count": 0,
        "question_count": 1,
        "unsupported_claims": [],
        "internal_terms": [],
        "unknown_acknowledged": False,
        "advisory_model_score": 0,
    }


def _checks(result):
    return {check.name: check for check in result.checks}


def test_phase_4_corpus_has_at_least_110_rich_unique_cases():
    cases = _cases()
    validation = validate_corpus(cases, minimum_cases=110)

    assert validation["passed"], validation
    assert len(cases) >= 110
    assert len({case["id"] for case in cases}) == len(cases)
    assert all(CASE_REQUIRED_FIELDS.issubset(case) for case in cases)
    assert any(len(case["history"]) >= 15 for case in cases)
    assert {case["register"] for case in cases} >= {
        "EGYPTIAN_COLLOQUIAL",
        "MODERN_STANDARD_ARABIC",
        "ENGLISH",
        "MIXED_ARABIC_ENGLISH",
        "ARABIZI",
    }
    assert {case["contact_gate"] for case in cases} == {"FORBID", "ALLOW_ONCE", "REQUIRE_ONCE"}
    assert any(case["unknown_handling"]["required"] for case in cases)
    assert any(case["budget_rule"]["hard"] for case in cases)


def test_representative_response_passes_every_deterministic_check_and_advisory_score_is_ignored():
    result = evaluate_response(_case("budget-hard-7000-26"), _passing_budget_response())

    assert result.passed, result.as_dict()
    assert result.advisory_model_score == 0
    assert len(result.checks) == 12


def test_source_and_fact_evaluator_rejects_missing_forbidden_and_unbound_claims():
    case = _case("price-ergo-one-21")
    response = {
        **_passing_budget_response(),
        "answer_text": "Arvena Ergo One is 7000 EGP.",
        "intent": "PRICE_LOOKUP",
        "language": "mixed",
        "register": "MIXED_ARABIC_ENGLISH",
        "fact_ids_used": ["price:ergo-one:7000"],
        "facts": [{"claim": "price is 7000"}],
        "products": [{"name": "Arvena Ergo One", "price": 7000}],
    }

    result = evaluate_response(case, response)
    check = _checks(result)["source_and_facts"]

    assert check.passed is False
    assert any("missing required fact" in detail for detail in check.details)
    assert any("unbound fact" in detail for detail in check.details)


def test_latest_relevance_and_product_continuity_are_deterministic():
    case = _case("details-pronoun-13")
    response = {
        **_passing_budget_response(),
        "answer_text": "Arvena Ergo Pro costs 10900 EGP.",
        "intent": "PRICE_LOOKUP",
        "answered_latest": False,
        "fact_ids_used": ["product:ergo-one", "spec:ergo-one:mesh-back"],
        "products": [{"name": "Arvena Ergo Pro", "price": 10900}],
        "selected_product": "Arvena Ergo Pro",
    }

    checks = _checks(evaluate_response(case, response))

    assert checks["latest_relevance"].passed is False
    assert checks["product_continuity"].passed is False


def test_hard_budget_rejects_above_budget_recommendation():
    response = deepcopy(_passing_budget_response())
    response["products"] = [
        {"name": "Arvena Ergo Pro", "price": 10900, "recommended": True, "compatible": True}
    ]
    response["selected_product"] = "Arvena Ergo Pro"

    check = _checks(evaluate_response(_case("budget-hard-7000-26"), response))["budget_compliance"]

    assert check.passed is False
    assert "exceeds hard budget" in check.details[0]


def test_contact_repetition_and_catalog_dump_checks_fail_independently():
    case = _case("discovery-ar-chair-01")
    response = {
        **_passing_budget_response(),
        "answer_text": "ابعت رقم موبايلك. ابعت رقم موبايلك.",
        "intent": "CATEGORY_DISCOVERY",
        "fact_ids_used": ["category:office-chair"],
        "products": [
            {"name": "Arvena Ergo One", "price": 6900},
            {"name": "Arvena Ergo Pro", "price": 10900},
            {"name": "FocusDesk 120", "price": 8500},
            {"name": "LiftDesk Electric 120", "price": 19900},
        ],
        "selected_product": "",
        "contact_request_count": 2,
        "question_count": 0,
    }

    checks = _checks(evaluate_response(case, response))

    assert checks["contact_gate"].passed is False
    assert checks["repetition"].passed is False
    assert checks["catalog_dump"].passed is False


def test_unknown_language_internal_leakage_claim_and_length_checks_fail():
    case = _case("unknown-discount-41")
    response = {
        "answer_text": "Groq says provider_available=true. We definitely offer 30% discount today. " * 20,
        "intent": "PRICE_LOOKUP",
        "answered_latest": True,
        "language": "en",
        "register": "ENGLISH",
        "fact_ids_used": [],
        "facts": [],
        "products": [],
        "contact_request_count": 0,
        "question_count": 0,
        "unsupported_claims": ["30% discount"],
        "internal_terms": ["trace_id"],
        "unknown_acknowledged": False,
    }

    checks = _checks(evaluate_response(case, response))

    assert checks["unsupported_claims"].passed is False
    assert checks["language_and_register"].passed is False
    assert checks["internal_leakage"].passed is False
    assert checks["unknown_handling"].passed is False
    assert checks["response_length"].passed is False


def test_evaluate_corpus_requires_one_response_per_case():
    cases = [_case("budget-hard-7000-26"), _case("unknown-discount-41")]

    report = evaluate_corpus(cases, {"budget-hard-7000-26": _passing_budget_response()})

    assert report["passed"] is False
    assert report["evaluated_count"] == 1
    assert report["missing_response_ids"] == ["unknown-discount-41"]
    assert report["acceptance_authority"] == "deterministic"
    assert report["model_scoring"] == "advisory_only"


def test_report_command_emits_valid_corpus_contract_json_without_claiming_runtime_quality():
    result = subprocess.run(
        [sys.executable, "scripts/run_conversation_quality_lab.py", "--minimum-cases", "110"],
        cwd=BACKEND_DIR,
        text=True,
        capture_output=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["passed"] is True
    assert report["case_count"] >= 110
    assert report["mode"] == "corpus_contract_validation"
    assert report["runtime_quality_certified"] is False
