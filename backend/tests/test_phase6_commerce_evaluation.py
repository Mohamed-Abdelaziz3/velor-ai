import copy
from pathlib import Path

from evaluation.phase6_commerce_suite import (
    evaluate_case,
    evaluate_dataset,
    load_dataset,
    load_responses,
    validate_dataset,
)


BASE = Path(__file__).resolve().parents[1]
DATASET = BASE / "evals" / "phase6" / "egyptian_commerce_v1.json"
RESPONSES = BASE / "evals" / "phase6" / "reference_responses_v1.json"


def _fixtures():
    return load_dataset(DATASET), load_responses(RESPONSES)


def test_phase6_dataset_is_versioned_and_covers_required_commerce_edges():
    dataset, _ = _fixtures()
    contract = validate_dataset(dataset)
    assert contract["passed"], contract
    assert dataset["dataset_version"] == "1.0.0"
    categories = {case["category"] for case in dataset["cases"]}
    assert {
        "price", "discount", "stock", "size", "color", "delivery_fee", "return_policy",
        "stale_evidence", "missing_evidence", "conflict", "ambiguous", "egyptian_arabic",
        "arabic_english_mix", "spelling_mistake", "angry_customer", "unsupported_claim",
        "human_escalation", "provider_failure",
    }.issubset(categories)


def test_reference_run_is_repeatable_and_does_not_claim_runtime_quality():
    dataset, responses = _fixtures()
    first = evaluate_dataset(dataset, responses)
    second = evaluate_dataset(dataset, responses)
    assert first == second
    assert first["passed"] is True
    assert first["runtime_quality_certified"] is False
    assert first["evaluated_count"] == 24
    assert first["decision_class_counts"] == {"answer": 12, "escalation": 8, "refusal": 3, "unsupported_claim": 1}
    assert first["metrics"]["human_acceptance_rate"] is None
    assert first["metrics"]["latency_ms_average"] is None
    assert first["metrics"]["cost_usd_total"] is None


def test_price_and_stock_hallucinations_are_measured_and_rejected():
    dataset, responses = _fixtures()
    price_case = next(case for case in dataset["cases"] if case["id"] == "price-001")
    price_response = copy.deepcopy(responses["price-001"])
    price_response["fact_ids_used"] = ["price:ergo-one:9999"]
    price_response["evidence_used"] = []
    price_response["claims"] = [{"fact_id": "price:ergo-one:9999", "claim_type": "price", "supported": True}]
    result = evaluate_case(dataset, price_case, price_response)
    assert result["passed"] is False
    assert result["metrics"]["price_hallucination"] == 1

    stock_case = next(case for case in dataset["cases"] if case["id"] == "stock-003")
    stock_response = copy.deepcopy(responses["stock-003"])
    stock_response["claims"] = [{"fact_id": "stock:ergo-one:invented", "claim_type": "stock", "supported": True}]
    result = evaluate_case(dataset, stock_case, stock_response)
    assert result["passed"] is False
    assert result["metrics"]["stock_hallucination"] == 1


def test_version_and_evidence_refs_are_required_per_decision():
    dataset, responses = _fixtures()
    case = next(case for case in dataset["cases"] if case["id"] == "price-001")
    response = copy.deepcopy(responses["price-001"])
    response["versions"] = {"prompt_version": "", "model_version": "", "provider_version": ""}
    response["evidence_used"] = ["not-in-case"]
    result = evaluate_case(dataset, case, response)
    assert result["passed"] is False
    assert result["checks"]["versions"] is False
    assert result["checks"]["evidence_refs"] is False


def test_stale_conflict_and_provider_failure_have_explicit_paths():
    dataset, responses = _fixtures()
    for case_id in ("stale-price-008", "conflict-010", "return-conflict-022"):
        case = next(case for case in dataset["cases"] if case["id"] == case_id)
        result = evaluate_case(dataset, case, responses[case_id])
        assert result["checks"]["escalation"] is True
        assert result["checks"]["claim_grounding"] is True

    fallback_case = next(case for case in dataset["cases"] if case["id"] == "fallback-018")
    fallback_result = evaluate_case(dataset, fallback_case, responses["fallback-018"])
    assert fallback_result["checks"]["provider_fallback"] is True


def test_missing_response_is_reported_without_fabricating_a_score():
    dataset, responses = _fixtures()
    responses.pop("price-001")
    report = evaluate_dataset(dataset, responses)
    missing = next(row for row in report["results"] if row["case_id"] == "price-001")
    assert missing["passed"] is False
    assert missing["checks"]["response_present"] is False
    assert report["passed"] is False
