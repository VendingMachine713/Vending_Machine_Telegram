from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.vm_core.rule_registry import (  # noqa: E402
    RuleRegistryError,
    activate_proposal,
    decide_proposal,
    proposals,
    registry_summary,
    rollback_proposal,
    sync_calibration_proposals,
)


def _json(value: object) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False, default=str))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Govern VM Brain calibration proposals and reversible rule-registry versions."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("summary")
    sub.add_parser("sync")
    listing = sub.add_parser("list")
    listing.add_argument("--status", default=None)

    for name in ("approve", "reject"):
        item = sub.add_parser(name)
        item.add_argument("proposal_id", type=int)
        item.add_argument("--actor", default="operator")
        item.add_argument("--note", default=None)

    activate = sub.add_parser("activate")
    activate.add_argument("proposal_id", type=int)
    activate.add_argument("--actor", default="operator")
    activate.add_argument("--rollout", type=int, default=10)

    rollback = sub.add_parser("rollback")
    rollback.add_argument("proposal_id", type=int)
    rollback.add_argument("--actor", default="operator")
    rollback.add_argument("--note", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "summary":
            _json(registry_summary(ROOT))
        elif args.command == "sync":
            _json(sync_calibration_proposals(ROOT))
        elif args.command == "list":
            _json(proposals(ROOT, status=args.status))
        elif args.command == "approve":
            _json(decide_proposal(args.proposal_id, "APPROVED", actor=args.actor, note=args.note, root=ROOT).__dict__)
        elif args.command == "reject":
            _json(decide_proposal(args.proposal_id, "REJECTED", actor=args.actor, note=args.note, root=ROOT).__dict__)
        elif args.command == "activate":
            _json(activate_proposal(args.proposal_id, actor=args.actor, rollout_percent=args.rollout, root=ROOT).__dict__)
        elif args.command == "rollback":
            _json(rollback_proposal(args.proposal_id, actor=args.actor, note=args.note, root=ROOT).__dict__)
        return 0
    except RuleRegistryError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
