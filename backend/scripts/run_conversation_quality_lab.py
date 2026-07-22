"""Run the Phase 4 Conversation Quality Lab and emit a JSON report.

Examples:
  python scripts/run_conversation_quality_lab.py
  python scripts/run_conversation_quality_lab.py --responses path/to/responses.json
  python scripts/run_conversation_quality_lab.py --responses responses.json --output report.json

Without ``--responses`` the command validates the durable corpus contract.  It
does not pretend that structural validation proves runtime response quality.
With responses, the file may be either a mapping keyed by case id or a list of
objects containing ``case_id`` plus the normalized response trace fields.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from services.conversation_quality_lab import evaluate_corpus, load_corpus, validate_corpus


DEFAULT_CORPUS = BACKEND_DIR / "tests" / "fixtures" / "phase_4_conversation_quality.json"


def _load_responses(path: Path) -> dict[str, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        return {str(case_id): dict(response) for case_id, response in payload.items()}
    if isinstance(payload, list):
        responses: dict[str, dict[str, Any]] = {}
        for row in payload:
            if not isinstance(row, dict) or not row.get("case_id"):
                raise ValueError("response list rows require case_id")
            case_id = str(row["case_id"])
            responses[case_id] = {key: value for key, value in row.items() if key != "case_id"}
        return responses
    raise ValueError("responses must be a JSON object or list")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic VELOR conversation quality checks")
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--responses", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--minimum-cases", type=int, default=100)
    args = parser.parse_args()

    cases = load_corpus(args.corpus)
    contract = validate_corpus(cases, minimum_cases=args.minimum_cases)
    if args.responses:
        report = evaluate_corpus(cases, _load_responses(args.responses))
        report["corpus_contract"] = contract
        report["passed"] = bool(contract["passed"] and report["passed"])
    else:
        report = {
            "mode": "corpus_contract_validation",
            "corpus": str(args.corpus),
            **contract,
            "acceptance_authority": "deterministic",
            "model_scoring": "advisory_only",
            "runtime_quality_certified": False,
            "note": "Pass proves corpus structure only; provide --responses for semantic response evaluation.",
        }

    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
