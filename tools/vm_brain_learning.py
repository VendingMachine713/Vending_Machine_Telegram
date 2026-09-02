from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.vm_core.learning import LearningError, learning_summary, outcomes, record_outcome, rule_performance  # noqa: E402


def _json(value: object) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False, default=str))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Record verified VM Brain outcomes and inspect descriptive learning metrics.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("summary")
    sub.add_parser("rules")
    sub.add_parser("outcomes")
    record = sub.add_parser("record")
    record.add_argument("recommendation_key")
    record.add_argument("outcome_type", choices=["positive", "neutral", "negative", "unknown"])
    record.add_argument("--value", type=float, default=0)
    record.add_argument("--confidence", type=float, default=1)
    record.add_argument("--actor", default="operator")
    record.add_argument("--note", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "summary":
            _json(learning_summary(ROOT))
        elif args.command == "rules":
            _json(rule_performance(ROOT))
        elif args.command == "outcomes":
            _json(outcomes(ROOT))
        elif args.command == "record":
            _json(record_outcome(
                args.recommendation_key,
                args.outcome_type,
                value_score=args.value,
                confidence=args.confidence,
                actor=args.actor,
                note=args.note,
                root=ROOT,
            ).__dict__)
        return 0
    except LearningError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
