from __future__ import annotations

import argparse
import json
from pathlib import Path

from .autopilot import autopilot_loop, autopilot_once


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vm-recovery-autopilot")
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--once", action="store_true", help="Run one cycle and exit.")
    parser.add_argument("--observe", action="store_true", help="Force observe-only even if central policy enables apply-safe.")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.once:
        result = autopilot_once(args.root, force_observe=args.observe)
        if args.as_json:
            print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        else:
            summary = result["plan"]["summary"]
            print("VM RECOVERY AUTOPILOT")
            print(f"Mode: {result['mode']}")
            print(
                f"Healthy: {summary.get('healthy', 0)} | Safe candidates: {summary.get('automatic_candidates', 0)} | "
                f"Needs operator: {summary.get('operator_attention', 0)} | Blocked: {summary.get('blocked', 0)}"
            )
            print(f"Actions this pass: {len(result['execution'].get('actions') or [])}")
        return 0
    autopilot_loop(args.root, force_observe=args.observe)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
