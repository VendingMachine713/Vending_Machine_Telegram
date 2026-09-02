from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.vm_core.decision_engine import decision_summary
from shared.vm_core.rule_health import health_summary


def main() -> int:
    parser = argparse.ArgumentParser(description="VM Brain Phase 1 passive trust/decision view")
    parser.add_argument("view", choices=("health", "decisions", "summary"), nargs="?", default="summary")
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()

    if args.view == "health":
        payload = health_summary(ROOT)
    elif args.view == "decisions":
        payload = decision_summary(ROOT, limit=args.limit)
    else:
        payload = {
            "phase": "1 - Make Brain trustworthy",
            "rule_health": health_summary(ROOT),
            "decision_engine": decision_summary(ROOT, limit=args.limit),
            "automatic_rollback": False,
            "automatic_acceptance": False,
            "automatic_execution": False,
            "external_action_authority": False,
        }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
