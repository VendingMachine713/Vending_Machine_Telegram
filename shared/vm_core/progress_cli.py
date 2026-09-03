from __future__ import annotations

import argparse
import json
from pathlib import Path

from .autoposter_progress import smart_auto_poster_progress
from .progress import format_progress
from .progress_registry import format_all_progress, platform_progress_summary, provider_names


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vm-progress",
        description="Read-only Universal Progress Engine operator view.",
    )
    parser.add_argument(
        "surface",
        nargs="?",
        default="all",
        choices=["all", *provider_names()],
        help="Progress surface to display.",
    )
    parser.add_argument("--json", action="store_true", dest="as_json", help="Emit structured JSON instead of operator text.")
    parser.add_argument("--root", type=Path, default=None, help="Optional project root override for diagnostics/tests.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.surface == "all":
        if args.as_json:
            print(json.dumps(platform_progress_summary(args.root), indent=2, ensure_ascii=False, default=str))
        else:
            print(format_all_progress(args.root))
        return 0

    snapshot = smart_auto_poster_progress(args.root)
    if args.as_json:
        print(json.dumps(snapshot, indent=2, ensure_ascii=False, default=str))
    else:
        print(format_progress(snapshot))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
