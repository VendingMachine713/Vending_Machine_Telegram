from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.vm_core.calibration import calibration_report, calibration_summary  # noqa: E402


def _json(value: object) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False, default=str))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Show advisory VM Brain calibration analysis without changing rules."
    )
    parser.add_argument("command", choices=["summary", "report"], nargs="?", default="summary")
    args = parser.parse_args(argv)
    if args.command == "report":
        _json(calibration_report(ROOT))
    else:
        _json(calibration_summary(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
