from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.vm_core.db import PlatformDB  # noqa: E402
from shared.vm_core.governance import (  # noqa: E402
    RecommendationGovernanceError,
    governance_summary,
    recommendation_history,
    transition_recommendation,
)


def _json(value: object) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False, default=str))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Review and govern VM Brain recommendations without executing Telegram actions."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="List current recommendations.")
    sub.add_parser("summary", help="Show passive governance counts and actionable recommendations.")

    for command in ("accept", "dismiss", "complete"):
        item = sub.add_parser(command, help=f"Mark a recommendation {command}ed.")
        item.add_argument("recommendation_key")
        item.add_argument("--actor", default="operator")
        item.add_argument("--note", default=None)

    history = sub.add_parser("history", help="Show the audit history for one recommendation.")
    history.add_argument("recommendation_key")
    history.add_argument("--limit", type=int, default=50)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    db = PlatformDB(root=ROOT)
    db.init()

    if args.command == "list":
        _json(db.recommendations(100))
        return 0
    if args.command == "summary":
        _json(governance_summary(ROOT))
        return 0
    if args.command == "history":
        try:
            _json(recommendation_history(args.recommendation_key, root=ROOT, limit=args.limit))
            return 0
        except RecommendationGovernanceError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2

    target = {
        "accept": "ACCEPTED",
        "dismiss": "DISMISSED",
        "complete": "COMPLETED",
    }[args.command]
    try:
        result = transition_recommendation(
            args.recommendation_key,
            target,
            actor=args.actor,
            note=args.note,
            root=ROOT,
        )
    except RecommendationGovernanceError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    _json(result.__dict__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
