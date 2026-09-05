from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.vm_core.autoposter_intelligence import sync_autoposter_intelligence
from shared.vm_core.entity_graph import entity_graph
from shared.vm_core.mission_control import mission_control
from shared.vm_core.group_member_audit import group_member_audit_summary
from shared.vm_core.group_member_audit_view import render_group_member_audit
from shared.vm_core.operator_home import operator_home
from shared.vm_core.opportunity_intelligence import opportunity_summary


def main() -> int:
    parser = argparse.ArgumentParser(description="VM Brain Phase 2 passive Mission Control")
    parser.add_argument(
        "view",
        choices=("home", "mission", "group-audit", "graph", "opportunities", "sap-sync"),
        nargs="?",
        default="mission",
    )
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()

    if args.view == "group-audit":
        payload = group_member_audit_summary(root=ROOT, group_limit=args.limit, member_limit=max(50, args.limit * 5))
    elif args.view == "graph":
        payload = entity_graph(ROOT, limit=max(100, args.limit * 10))
    elif args.view == "opportunities":
        payload = opportunity_summary(ROOT, limit=args.limit)
    elif args.view == "sap-sync":
        payload = sync_autoposter_intelligence(ROOT, limit=args.limit)
    else:
        payload = mission_control(ROOT, limit=args.limit)

    if args.view == "home":
        print(operator_home(payload))
    elif args.view == "group-audit":
        print(render_group_member_audit(payload))
    else:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
