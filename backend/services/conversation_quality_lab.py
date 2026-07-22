"""Deterministic semantic evaluation for VELOR conversation responses.

The lab deliberately does not call a model and does not treat model scoring as
acceptance authority.  It evaluates a normalized response trace against a
case contract.  Runtime adapters may create these traces from fallback,
provider, browser, or stored-transcript runs without changing the evaluator.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


CASE_REQUIRED_FIELDS = {
    "id",
    "input",
    "history",
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

CONTACT_PATTERNS = (
    r"\b(?:phone|mobile|whatsapp|contact)\b",
    r"(?:رقم|موبايل|واتساب|تواصل)",
)
UNKNOWN_PATTERNS = (
    r"\b(?:unknown|not documented|not available in (?:the )?(?:catalog|information)|cannot confirm|can't confirm)\b",
    r"(?:غير موثق|غير متاح في المعلومات|مش موثق|لا أستطيع تأكيد|مش قادر أأكد|لا توجد معلومة)",
)
INTERNAL_TERMS = (
    "leadintelligencesnapshot",
    "commercialdecisionlineage",
    "response_engine_version",
    "provider_available",
    "fallback_reason",
    "fact_ids_used",
    "system prompt",
    "prompt_context",
    "internal enum",
    "groq",
    "openai",
)


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    details: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "passed": self.passed, "details": list(self.details)}


@dataclass
class EvaluationResult:
    case_id: str
    checks: list[CheckResult] = field(default_factory=list)
    advisory_model_score: Any = None

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(check.passed for check in self.checks)

    def as_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "passed": self.passed,
            "checks": [check.as_dict() for check in self.checks],
            # This field is recorded for analysis only and never affects passed.
            "advisory_model_score": self.advisory_model_score,
        }


def load_corpus(path: str | Path) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("conversation quality corpus must be a JSON list")
    return payload


def validate_case_contract(case: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    missing = sorted(CASE_REQUIRED_FIELDS.difference(case))
    if missing:
        errors.append(f"missing fields: {', '.join(missing)}")
    if not str(case.get("id") or "").strip():
        errors.append("id must be non-empty")
    if not str(case.get("input") or "").strip():
        errors.append("input must be non-empty")
    for key in ("history", "facts_required", "facts_forbidden", "products_allowed", "products_forbidden"):
        if key in case and not isinstance(case[key], list):
            errors.append(f"{key} must be a list")
    if case.get("contact_gate") not in {"FORBID", "ALLOW_ONCE", "REQUIRE_ONCE"}:
        errors.append("contact_gate must be FORBID, ALLOW_ONCE, or REQUIRE_ONCE")
    if not isinstance(case.get("budget_rule"), Mapping):
        errors.append("budget_rule must be an object")
    if not isinstance(case.get("unknown_handling"), Mapping):
        errors.append("unknown_handling must be an object")
    if not isinstance(case.get("response_length"), Mapping):
        errors.append("response_length must be an object")
    for key in ("max_products", "max_questions"):
        value = case.get(key)
        if not isinstance(value, int) or value < 0:
            errors.append(f"{key} must be a non-negative integer")
    return errors


def validate_corpus(cases: Sequence[Mapping[str, Any]], minimum_cases: int = 100) -> dict[str, Any]:
    case_errors: dict[str, list[str]] = {}
    ids: list[str] = []
    for index, case in enumerate(cases):
        case_id = str(case.get("id") or f"index-{index}")
        ids.append(case_id)
        errors = validate_case_contract(case)
        if errors:
            case_errors[case_id] = errors
    duplicates = sorted(case_id for case_id, count in Counter(ids).items() if count > 1)
    return {
        "case_count": len(cases),
        "minimum_cases": minimum_cases,
        "minimum_met": len(cases) >= minimum_cases,
        "unique_ids": not duplicates,
        "duplicate_ids": duplicates,
        "case_errors": case_errors,
        "passed": len(cases) >= minimum_cases and not duplicates and not case_errors,
    }


def _as_strings(values: Iterable[Any]) -> list[str]:
    return [str(value).strip() for value in values if str(value).strip()]


def _normalized_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def _response_text(response: Mapping[str, Any]) -> str:
    return str(response.get("answer_text") or response.get("reply") or response.get("text") or "").strip()


def _product_rows(response: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = response.get("products") or response.get("product_cards") or []
    normalized: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, str):
            normalized.append({"name": row, "price": None, "recommended": True, "compatible": True})
        elif isinstance(row, Mapping):
            normalized.append(dict(row))
    return normalized


def _count_questions(text: str, response: Mapping[str, Any]) -> int:
    explicit = response.get("question_count")
    if isinstance(explicit, int):
        return explicit
    return text.count("?") + text.count("؟")


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?؟])\s+|\n+", text) if part.strip()]


def _check_source_and_facts(case: Mapping[str, Any], response: Mapping[str, Any]) -> CheckResult:
    required = set(_as_strings(case.get("facts_required", [])))
    forbidden = set(_as_strings(case.get("facts_forbidden", [])))
    used = set(_as_strings(response.get("fact_ids_used", [])))
    missing = sorted(required - used)
    forbidden_used = sorted(forbidden & used)
    facts = response.get("facts", []) or []
    unbound = []
    bound_fact_ids = set()
    for fact in facts:
        if not isinstance(fact, Mapping):
            continue
        fact_id = str(fact.get("fact_id") or "").strip()
        source_id = str(fact.get("source_id") or "").strip()
        if fact_id and source_id:
            bound_fact_ids.add(fact_id)
        elif fact.get("claim"):
            unbound.append(str(fact.get("claim")))
    unbound.extend(sorted(used - bound_fact_ids))
    details = [*(f"missing required fact: {item}" for item in missing), *(f"forbidden fact used: {item}" for item in forbidden_used)]
    details.extend(f"unbound fact: {item}" for item in unbound)
    return CheckResult("source_and_facts", not details, tuple(details))


def _check_latest_relevance(case: Mapping[str, Any], response: Mapping[str, Any]) -> CheckResult:
    expected = str(case.get("required_intent") or "")
    actual = str(response.get("intent") or "")
    answered = response.get("answered_latest")
    details = []
    if expected and actual != expected:
        details.append(f"intent {actual!r} != {expected!r}")
    if answered is not True:
        details.append("latest question was not answered")
    return CheckResult("latest_relevance", not details, tuple(details))


def _check_product_continuity(case: Mapping[str, Any], response: Mapping[str, Any]) -> CheckResult:
    allowed = set(_as_strings(case.get("products_allowed", [])))
    forbidden = set(_as_strings(case.get("products_forbidden", [])))
    names = {str(row.get("name") or "").strip() for row in _product_rows(response) if str(row.get("name") or "").strip()}
    selected = str(response.get("selected_product") or "").strip()
    if selected:
        names.add(selected)
    disallowed = sorted(name for name in names if allowed and name not in allowed)
    forbidden_seen = sorted(names & forbidden)
    continuity = str(case.get("continuity_product") or "").strip()
    details = [*(f"product not allowed: {name}" for name in disallowed), *(f"forbidden product: {name}" for name in forbidden_seen)]
    if continuity and continuity not in names:
        details.append(f"continuity product missing: {continuity}")
    return CheckResult("product_continuity", not details, tuple(details))


def _check_budget(case: Mapping[str, Any], response: Mapping[str, Any]) -> CheckResult:
    rule = case.get("budget_rule") or {}
    maximum = rule.get("max") if isinstance(rule, Mapping) else None
    if maximum is None:
        return CheckResult("budget_compliance", True)
    details = []
    for product in _product_rows(response):
        price = product.get("price")
        presented_as_fit = product.get("recommended", True) or product.get("compatible", True)
        if presented_as_fit and isinstance(price, (int, float)) and float(price) > float(maximum):
            details.append(f"{product.get('name') or 'product'} price {price} exceeds hard budget {maximum}")
    return CheckResult("budget_compliance", not details, tuple(details))


def _contact_count(text: str, response: Mapping[str, Any]) -> int:
    explicit = response.get("contact_request_count")
    if isinstance(explicit, int):
        return explicit
    return 1 if any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in CONTACT_PATTERNS) else 0


def _check_contact(case: Mapping[str, Any], response: Mapping[str, Any], text: str) -> CheckResult:
    gate = case.get("contact_gate")
    count = _contact_count(text, response)
    passed = (gate == "FORBID" and count == 0) or (gate == "ALLOW_ONCE" and count <= 1) or (gate == "REQUIRE_ONCE" and count == 1)
    return CheckResult("contact_gate", passed, () if passed else (f"gate={gate} contact_request_count={count}",))


def _check_repetition(text: str) -> CheckResult:
    sentences = [_normalized_text(sentence).strip(".!?؟") for sentence in _sentences(text)]
    repeats = sorted(sentence for sentence, count in Counter(sentences).items() if sentence and count > 1)
    return CheckResult("repetition", not repeats, tuple(f"repeated sentence: {sentence}" for sentence in repeats))


def _check_catalog_dump(case: Mapping[str, Any], response: Mapping[str, Any]) -> CheckResult:
    count = len(_product_rows(response))
    maximum = int(case.get("max_products", 0))
    return CheckResult("catalog_dump", count <= maximum, () if count <= maximum else (f"{count} products exceeds maximum {maximum}",))


def _check_unsupported_claims(response: Mapping[str, Any]) -> CheckResult:
    claims = _as_strings(response.get("unsupported_claims", []))
    return CheckResult("unsupported_claims", not claims, tuple(f"unsupported claim: {claim}" for claim in claims))


def _check_language(case: Mapping[str, Any], response: Mapping[str, Any]) -> CheckResult:
    expected_language = str(case.get("language") or "")
    expected_register = str(case.get("register") or "")
    actual_language = str(response.get("language") or "")
    actual_register = str(response.get("register") or "")
    details = []
    if actual_language != expected_language:
        details.append(f"language {actual_language!r} != {expected_language!r}")
    if actual_register != expected_register:
        details.append(f"register {actual_register!r} != {expected_register!r}")
    return CheckResult("language_and_register", not details, tuple(details))


def _check_internal_leakage(text: str, response: Mapping[str, Any]) -> CheckResult:
    lowered = text.casefold()
    leaked = [term for term in INTERNAL_TERMS if term in lowered]
    leaked.extend(_as_strings(response.get("internal_terms", [])))
    leaked = sorted(set(leaked))
    return CheckResult("internal_leakage", not leaked, tuple(f"internal term leaked: {term}" for term in leaked))


def _check_unknown(case: Mapping[str, Any], response: Mapping[str, Any], text: str) -> CheckResult:
    rule = case.get("unknown_handling") or {}
    required = bool(rule.get("required")) if isinstance(rule, Mapping) else False
    if not required:
        return CheckResult("unknown_handling", True)
    acknowledged = response.get("unknown_acknowledged") is True or any(
        re.search(pattern, text, flags=re.IGNORECASE) for pattern in UNKNOWN_PATTERNS
    )
    return CheckResult("unknown_handling", acknowledged, () if acknowledged else ("required unknown was not acknowledged",))


def _check_length(case: Mapping[str, Any], response: Mapping[str, Any], text: str) -> CheckResult:
    bounds = case.get("response_length") or {}
    min_chars = int(bounds.get("min_chars", 1))
    max_chars = int(bounds.get("max_chars", 600))
    max_sentences = int(bounds.get("max_sentences", 4))
    questions = _count_questions(text, response)
    max_questions = int(case.get("max_questions", 0))
    sentence_count = len(_sentences(text))
    details = []
    if len(text) < min_chars:
        details.append(f"{len(text)} chars below minimum {min_chars}")
    if len(text) > max_chars:
        details.append(f"{len(text)} chars exceeds maximum {max_chars}")
    if sentence_count > max_sentences:
        details.append(f"{sentence_count} sentences exceeds maximum {max_sentences}")
    if questions > max_questions:
        details.append(f"{questions} questions exceeds maximum {max_questions}")
    return CheckResult("response_length", not details, tuple(details))


def evaluate_response(case: Mapping[str, Any], response: Mapping[str, Any]) -> EvaluationResult:
    contract_errors = validate_case_contract(case)
    if contract_errors:
        return EvaluationResult(
            case_id=str(case.get("id") or "unknown"),
            checks=[CheckResult("case_contract", False, tuple(contract_errors))],
            advisory_model_score=response.get("advisory_model_score"),
        )
    text = _response_text(response)
    checks = [
        _check_source_and_facts(case, response),
        _check_latest_relevance(case, response),
        _check_product_continuity(case, response),
        _check_budget(case, response),
        _check_contact(case, response, text),
        _check_repetition(text),
        _check_catalog_dump(case, response),
        _check_unsupported_claims(response),
        _check_language(case, response),
        _check_internal_leakage(text, response),
        _check_unknown(case, response, text),
        _check_length(case, response, text),
    ]
    return EvaluationResult(
        case_id=str(case["id"]),
        checks=checks,
        advisory_model_score=response.get("advisory_model_score"),
    )


def evaluate_corpus(cases: Sequence[Mapping[str, Any]], responses: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    results: list[EvaluationResult] = []
    missing_response_ids: list[str] = []
    for case in cases:
        case_id = str(case.get("id") or "")
        response = responses.get(case_id)
        if response is None:
            missing_response_ids.append(case_id)
            continue
        results.append(evaluate_response(case, response))
    return {
        "mode": "deterministic_response_evaluation",
        "case_count": len(cases),
        "evaluated_count": len(results),
        "passed_count": sum(result.passed for result in results),
        "failed_count": sum(not result.passed for result in results),
        "missing_response_ids": missing_response_ids,
        "passed": len(results) == len(cases) and all(result.passed for result in results),
        "results": [result.as_dict() for result in results],
        "acceptance_authority": "deterministic",
        "model_scoring": "advisory_only",
    }
