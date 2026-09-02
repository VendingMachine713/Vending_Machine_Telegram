from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.vm_core.security import format_group_safe_report, group_safe_preflight


def main() -> int:
    report = group_safe_preflight(ROOT)
    print(format_group_safe_report(report))
    return 0 if report["group_safe"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
