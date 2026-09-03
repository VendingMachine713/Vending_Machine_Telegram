from __future__ import annotations

import argparse
import json
from pathlib import Path

from .recovery import execute_recovery_plan, format_recovery_plan, recovery_plan


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vm-recovery", description="VM Recovery Intelligence planner and guarded safe-recovery executor.")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument(
        "--apply-safe",
        action="store_true",
        help="Apply only SAFE_RECOVERY actions after policy/config/cooldown checks. Default is read-only planning.",
    )
    parser.add_argument("--max-actions", type=int, default=1, help="Maximum safe recovery actions in this pass (default: 1).")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    plan = recovery_plan(args.root)
    execution = None
    if args.apply_safe:
        execution = execute_recovery_plan(plan, args.root, apply=True, max_actions=max(0, args.max_actions))

    if args.as_json:
        payload = {"plan": plan, "execution": execution} if execution is not None else plan
        print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    else:
        print(format_recovery_plan(plan))
        if execution is not None:
            print("\nGUARDED RECOVERY EXECUTION")
            print(f"Mode: {execution.get('mode')}")
            print(f"Actions: {len(execution.get('actions') or [])} | Skipped: {len(execution.get('skipped') or [])}")
            for row in execution.get("actions") or []:
                verification = row.get("verification") or {}
                print(f"{row.get('service')} -> {row.get('action')} | verified={verification.get('verified')}")
            for row in execution.get("skipped") or []:
                print(f"{row.get('service')} -> SKIPPED ({row.get('reason')})")
            if execution.get("operator_escalation_required"):
                print("Operator attention required: a recovery verification failed or restart limit was reached.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
