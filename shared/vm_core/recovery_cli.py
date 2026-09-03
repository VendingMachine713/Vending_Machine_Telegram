from __future__ import annotations

import argparse
import json
from pathlib import Path

from .recovery import format_recovery_plan, recovery_plan


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vm-recovery", description="Read-only VM Recovery Intelligence planner.")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--root", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    plan = recovery_plan(args.root)
    if args.as_json:
        print(json.dumps(plan, indent=2, ensure_ascii=False, default=str))
    else:
        print(format_recovery_plan(plan))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
