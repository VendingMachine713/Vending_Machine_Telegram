"""Inspect staged paths before a Windows-to-GitHub reconciliation push.

This helper never stages files. With --unstage-generated it only removes generated/runtime
paths from the index while preserving their local working-tree contents.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.vm_core.source_of_truth import classify_path


def git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=ROOT, text=True, capture_output=True)


def staged_paths() -> list[str]:
    proc = git("diff", "--cached", "--name-only", "-z", "--diff-filter=ACMRDT")
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "unable to list staged paths")
    return [item for item in proc.stdout.split("\x00") if item]


def unstage(path: str) -> None:
    proc = git("reset", "-q", "HEAD", "--", path)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"unable to unstage {path}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--unstage-generated", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    classified = [{"path": path, "class": classify_path(path)} for path in staged_paths()]
    sensitive = [item for item in classified if item["class"] == "sensitive"]
    generated = [item for item in classified if item["class"] == "generated"]

    unstaged: list[str] = []
    if args.unstage_generated:
        for item in generated:
            unstage(item["path"])
            unstaged.append(item["path"])

    report = {
        "ok": not sensitive,
        "staged_total": len(classified),
        "sensitive": sensitive,
        "generated": generated,
        "generated_unstaged": unstaged,
        "remaining_source_or_review": [
            item for item in classified if item["class"] in {"source", "review"}
        ],
    }

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Staged paths        : {report['staged_total']}")
        print(f"Sensitive           : {len(sensitive)}")
        print(f"Generated/runtime   : {len(generated)}")
        print(f"Generated unstaged  : {len(unstaged)}")
        print(f"Source/review       : {len(report['remaining_source_or_review'])}")
        if sensitive:
            print("[BLOCKED] Sensitive staged filenames detected. Values are not displayed.")
            for item in sensitive:
                print(f" - {item['path']}")

    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
