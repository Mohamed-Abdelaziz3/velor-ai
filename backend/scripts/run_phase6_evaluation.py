"""Run the offline Phase 6 Egyptian Commerce AI Evaluation Suite."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from evaluation.phase6_commerce_suite import evaluate_dataset, load_dataset, load_responses


DEFAULT_DATASET = BACKEND_DIR / "evals" / "phase6" / "egyptian_commerce_v1.json"
DEFAULT_RESPONSES = BACKEND_DIR / "evals" / "phase6" / "reference_responses_v1.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic Phase 6 commerce evaluation")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--responses", type=Path, default=DEFAULT_RESPONSES)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    report = evaluate_dataset(load_dataset(args.dataset), load_responses(args.responses))
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
