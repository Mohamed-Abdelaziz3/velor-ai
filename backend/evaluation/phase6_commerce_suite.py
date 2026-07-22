"""Reproducible, model-agnostic evaluation for V2 commerce traces.

The suite consumes normalized response traces rather than calling a provider.
This keeps acceptance deterministic and makes provider/model/prompt versions
explicit without changing the production conversation path.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence


REPORT_SCHEMA_VERSION = "phase6.report.v1"
DATASET_SCHEMA_VERSION = "phase6.dataset.v1"
DECISION_CLASSES = {"answer", "escalation", "refusal", "unsupported_claim"}
SENSITIVE_CLAIM_TYPES = {"price", "discount", "stock", "size", "color", "delivery_fee", "return_policy"}


def load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_dataset(path: str | Path) -> dict[str, Any]:
    payload = load_json(path)
    if not isinstance(payload, dict):
        raise ValueError("dataset must be an object with a manifest and cases")
    return payload


def load_responses(path: str | Path) -> dict[str, dict[str, Any]]:
    payload = load_json(path)
    rows = payload.get("responses") if isinstance(payload, dict) else payload
    defaults = payload.get("versions") if isinstance(payload, dict) and isinstance(payload.get("versions"), Mapping) else {}
    if not isinstance(rows, list):
        raise ValueError("responses must contain a list")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or not row.get("case_id"):
            raise ValueError("each response requires case_id")
        case_id = str(row["case_id"])
        if case_id in result:
            raise ValueError(f"duplicate response case_id: {case_id}")
        merged = dict(row)
        merged["versions"] = {**defaults, **(row.get("versions") if isinstance(row.get("versions"), Mapping) else {})}
        result[case_id] = merged
    return result


def validate_dataset(dataset: Mapping[str, Any], minimum_cases: int = 20) -> dict[str, Any]:
    required_manifest = {
        "schema_version",
        "dataset_id",
        "dataset_version",
        "prompt_version",
        "cases",
    }
    errors: list[str] = []
    missing_manifest = sorted(required_manifest - set(dataset))
    if missing_manifest:
        errors.append(f"missing manifest fields: {', '.join(missing_manifest)}")
    if dataset.get("schema_version") != DATASET_SCHEMA_VERSION:
        errors.append("unsupported dataset schema_version")
    cases = dataset.get("cases")
    if not isinstance(cases, list):
        errors.append("cases must be a list")
        cases = []
    ids: list[str] = []
    case_errors: dict[str, list[str]] = {}
    for index, case in enumerate(cases):
        case_id = str(case.get("id") if isinstance(case, Mapping) else f"index-{index}")
        ids.append(case_id)
        current: list[str] = []
        if not isinstance(case, Mapping):
            current.append("case must be an object")
        else:
            for field in ("id", "input", "category", "evidence", "expected"):
                if field not in case:
                    current.append(f"missing {field}")
            if not isinstance(case.get("evidence"), list):
                current.append("evidence must be a list")
            if not isinstance(case.get("expected"), Mapping):
                current.append("expected must be an object")
            elif case["expected"].get("decision_class") not in DECISION_CLASSES:
                current.append("expected.decision_class is invalid")
            evidence_ids = [str(row.get("evidence_id")) for row in case.get("evidence", []) if isinstance(row, Mapping)]
            if len(evidence_ids) != len(set(evidence_ids)):
                current.append("evidence IDs must be unique")
        if current:
            case_errors[case_id] = current
    duplicate_ids = sorted(case_id for case_id, count in Counter(ids).items() if count > 1)
    return {
        "schema_version": dataset.get("schema_version"),
        "dataset_id": dataset.get("dataset_id"),
        "dataset_version": dataset.get("dataset_version"),
        "case_count": len(cases),
        "minimum_cases": minimum_cases,
        "minimum_met": len(cases) >= minimum_cases,
        "duplicate_case_ids": duplicate_ids,
        "case_errors": case_errors,
        "passed": not errors and len(cases) >= minimum_cases and not duplicate_ids and not case_errors,
        "errors": errors,
    }


def _versions(dataset: Mapping[str, Any], response: Mapping[str, Any]) -> dict[str, str | None]:
    raw = response.get("versions") if isinstance(response.get("versions"), Mapping) else {}
    return {
        "prompt_version": str(raw.get("prompt_version") or dataset.get("prompt_version") or "") or None,
        "model_version": str(raw.get("model_version") or "") or None,
        "provider_version": str(raw.get("provider_version") or "") or None,
    }


def _evidence_map(case: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(row.get("evidence_id")): row
        for row in case.get("evidence", [])
        if isinstance(row, Mapping) and row.get("evidence_id")
    }


def _claim_rows(response: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [row for row in response.get("claims", []) if isinstance(row, Mapping)]


def evaluate_case(dataset: Mapping[str, Any], case: Mapping[str, Any], response: Mapping[str, Any] | None) -> dict[str, Any]:
    expected = case.get("expected") if isinstance(case.get("expected"), Mapping) else {}
    evidence = _evidence_map(case)
    if response is None:
        return {
            "case_id": str(case.get("id")),
            "passed": False,
            "decision_class": None,
            "checks": {"response_present": False},
            "errors": ["missing response"],
            "versions": {"prompt_version": None, "model_version": None, "provider_version": None},
            "metrics": {"claim_count": 0, "unsupported_claim_count": 0, "price_hallucination": 0, "stock_hallucination": 0, "claims_by_type": {}, "latency_ms": None, "cost_usd": None},
        }

    versions = _versions(dataset, response)
    fact_ids = {str(value) for value in response.get("fact_ids_used", [])}
    evidence_used = {str(value) for value in response.get("evidence_used", [])}
    required_facts = {str(value) for value in expected.get("required_fact_ids", [])}
    forbidden_facts = {str(value) for value in expected.get("forbidden_fact_ids", [])}
    claims = _claim_rows(response)
    unsupported_claims = [str(value) for value in response.get("unsupported_claims", []) if str(value).strip()]
    claim_errors: list[str] = []
    sensitive_unsupported: Counter[str] = Counter()
    supported_claim_count = 0
    for claim in claims:
        fact_id = str(claim.get("fact_id") or claim.get("evidence_id") or "")
        claim_type = str(claim.get("claim_type") or "other")
        supported = fact_id in evidence and fact_id in fact_ids and bool(claim.get("supported", True))
        if supported:
            supported_claim_count += 1
        else:
            if claim_type in SENSITIVE_CLAIM_TYPES:
                sensitive_unsupported[claim_type] += 1
            claim_errors.append(f"unsupported claim: {claim.get('text') or fact_id or 'unidentified'}")

    decision_class = str(response.get("decision_class") or "")
    errors: list[str] = []
    checks: dict[str, bool] = {}
    checks["response_present"] = bool(str(response.get("answer_text") or "").strip())
    checks["decision_class"] = decision_class == str(expected.get("decision_class") or "") and decision_class in DECISION_CLASSES
    checks["action"] = str(response.get("action") or "") == str(expected.get("action") or "")
    checks["escalation"] = bool(response.get("escalation_required")) == bool(expected.get("escalation_required"))
    checks["required_facts"] = required_facts.issubset(fact_ids)
    checks["forbidden_facts"] = not bool(forbidden_facts & fact_ids)
    checks["evidence_refs"] = evidence_used.issubset(set(evidence))
    checks["claim_grounding"] = not claim_errors or decision_class == "unsupported_claim"
    checks["versions"] = all(versions.values())
    checks["provider_fallback"] = True
    if expected.get("provider_behavior") == "fallback_required":
        checks["provider_fallback"] = (
            response.get("response_path") == "FALLBACK"
            and response.get("provider_available") is False
            and bool(response.get("fallback_reason"))
        )
    elif expected.get("provider_behavior") == "provider_required":
        checks["provider_fallback"] = response.get("response_path") == "MODEL" and response.get("provider_available") is True
    if decision_class == "unsupported_claim":
        checks["unsupported_claim_detection"] = bool(unsupported_claims)
    else:
        checks["unsupported_claim_detection"] = not unsupported_claims
    errors.extend(name for name, passed in checks.items() if not passed)
    return {
        "case_id": str(case.get("id")),
        "passed": not errors,
        "decision_class": decision_class,
        "checks": checks,
        "errors": errors,
        "versions": versions,
        "metrics": {
            "claim_count": len(claims),
            "supported_claim_count": supported_claim_count,
            "unsupported_claim_count": max(len(claim_errors), len(unsupported_claims)),
            "price_hallucination": sensitive_unsupported["price"],
            "stock_hallucination": sensitive_unsupported["stock"],
            "claims_by_type": dict(Counter(str(claim.get("claim_type") or "other") for claim in claims)),
            "latency_ms": response.get("latency_ms") if isinstance(response.get("latency_ms"), (int, float)) else None,
            "cost_usd": response.get("cost_usd") if isinstance(response.get("cost_usd"), (int, float)) else None,
        },
    }


def _average(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 3) if values else None


def evaluate_dataset(dataset: Mapping[str, Any], responses: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    cases = dataset.get("cases") if isinstance(dataset.get("cases"), list) else []
    contract = validate_dataset(dataset)
    rows = [evaluate_case(dataset, case, responses.get(str(case.get("id")))) for case in cases]
    expected_escalations = [case for case in cases if bool(case.get("expected", {}).get("escalation_required"))]
    correct_escalations = sum(
        1
        for case, row in zip(cases, rows)
        if bool(case.get("expected", {}).get("escalation_required")) and row["checks"].get("escalation")
    )
    answerable = [row for case, row in zip(cases, rows) if case.get("expected", {}).get("decision_class") == "answer"]
    grounded_answers = sum(
        1 for row in answerable if row["checks"].get("claim_grounding") and row["checks"].get("required_facts") and row["checks"].get("forbidden_facts")
    )
    claim_count = sum(row["metrics"]["claim_count"] for row in rows)
    unsupported_count = sum(row["metrics"]["unsupported_claim_count"] for row in rows)
    price_claims = sum(row["metrics"]["claims_by_type"].get("price", 0) for row in rows)
    stock_claims = sum(row["metrics"]["claims_by_type"].get("stock", 0) for row in rows)
    price_bad = sum(row["metrics"]["price_hallucination"] for row in rows)
    stock_bad = sum(row["metrics"]["stock_hallucination"] for row in rows)
    expected_actions = [str(case.get("expected", {}).get("action") or "") for case in cases]
    action_correct = sum(1 for case, row in zip(cases, rows) if row["checks"].get("action"))
    latency = [float(row["metrics"]["latency_ms"]) for row in rows if row["metrics"]["latency_ms"] is not None]
    costs = [float(row["metrics"]["cost_usd"]) for row in rows if row["metrics"]["cost_usd"] is not None]
    human_labels = [row for row in responses.values() if row.get("human_label") in {"accepted", "edited"}]
    return {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "mode": "reference_trace_evaluation",
        "acceptance_authority": "deterministic_harness",
        "runtime_quality_certified": False,
        "dataset": {
            "dataset_id": dataset.get("dataset_id"),
            "dataset_version": dataset.get("dataset_version"),
            "schema_version": dataset.get("schema_version"),
            "case_count": len(cases),
            "categories": sorted({str(case.get("category")) for case in cases}),
        },
        "versions": {
            "prompt_version": dataset.get("prompt_version"),
            "model_versions": sorted({row["versions"]["model_version"] for row in rows if row["versions"]["model_version"]}),
            "provider_versions": sorted({row["versions"]["provider_version"] for row in rows if row["versions"]["provider_version"]}),
        },
        "contract": contract,
        "evaluated_count": len(rows),
        "passed_count": sum(1 for row in rows if row["passed"]),
        "failed_count": sum(1 for row in rows if not row["passed"]),
        "decision_class_counts": dict(Counter(row["decision_class"] or "missing" for row in rows)),
        "metrics": {
            "grounded_factual_accuracy": (grounded_answers / len(answerable)) if answerable else None,
            "unsupported_claim_rate": (unsupported_count / claim_count) if claim_count else None,
            "price_hallucination_rate": (price_bad / price_claims) if price_claims else None,
            "stock_hallucination_rate": (stock_bad / stock_claims) if stock_claims else None,
            "correct_escalation_rate": (correct_escalations / len(expected_escalations)) if expected_escalations else None,
            "action_classification_accuracy": (action_correct / len(expected_actions)) if expected_actions else None,
            "human_acceptance_rate": (sum(row.get("human_label") == "accepted" for row in human_labels) / len(human_labels)) if human_labels else None,
            "human_edit_rate": (sum(row.get("human_label") == "edited" for row in human_labels) / len(human_labels)) if human_labels else None,
            "latency_ms_average": _average(latency),
            "cost_usd_total": round(sum(costs), 6) if costs else None,
            "measured_latency_samples": len(latency),
            "measured_cost_samples": len(costs),
        },
        "limitations": [
            "Reference traces are synthetic harness fixtures, not production outcomes.",
            "No human acceptance/edit labels, latency, or provider cost were supplied; those metrics remain null.",
            "A passing deterministic contract does not certify model groundedness on unseen conversations.",
        ],
        "results": rows,
        "passed": bool(contract["passed"] and rows and all(row["passed"] for row in rows)),
    }
