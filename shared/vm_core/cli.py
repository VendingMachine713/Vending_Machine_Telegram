from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

from . import __version__
from .doctor import run_doctor, write_diagnostics
from .inspect import write_structure_report
from .manifests import (
    build_inventory,
    create_missing_bot_manifests,
    discover_bots,
    write_inventory,
)
from .paths import ensure_platform_dirs, project_root


def _status(root: Path) -> int:
    bots = discover_bots(root)
    print("=" * 68)
    print(f" VENDING MACHINE TELEGRAM PLATFORM | vm_core v{__version__}")
    print("=" * 68)
    print(f"Root: {root}")
    print(f"Bots discovered: {len(bots)}")
    print()

    if not bots:
        print("No bots discovered.")
        return 1

    for bot in bots:
        version = bot.version or "unknown"
        entry = bot.entrypoint or "not detected"
        manifest = "yes" if bot.manifest_present else "no"
        print(f"- {bot.folder}")
        print(f"    version:    {version}")
        print(f"    entrypoint: {entry}")
        print(f"    confidence: {bot.entrypoint_confidence}")
        print(f"    manifest:   {manifest}")
        if bot.launchers:
            print(f"    launchers:  {', '.join(bot.launchers)}")
        if bot.nested_duplicate_folder:
            print("    WARNING: nested duplicate folder detected")
    return 0


def _doctor(root: Path) -> int:
    report = run_doctor(root)
    json_path, txt_path = write_diagnostics(report, root)
    print(txt_path.read_text(encoding="utf-8"))
    print(f"JSON: {json_path}")
    print(f"TEXT: {txt_path}")
    return 2 if report["summary"]["FAIL"] else 0


def _inventory(root: Path) -> int:
    output = write_inventory(root)
    inventory = build_inventory(root)
    print(f"Inventory written: {output}")
    print(f"Bots discovered: {inventory['bot_count']}")
    return 0


def _inspect(root: Path) -> int:
    json_path, txt_path = write_structure_report(root)
    print("=" * 68)
    print(" VM SAFE PROJECT INSPECTION")
    print("=" * 68)
    print(f"TEXT: {txt_path}")
    print(f"JSON: {json_path}")
    print("Sensitive filenames such as .env are not read; large runtime/cache folders are skipped.")
    return 0


def _manifests(root: Path, write: bool) -> int:
    changes = create_missing_bot_manifests(root, write=write)
    if not changes:
        print("No bot folders found.")
        return 1
    for item in changes:
        manifest = item.get("manifest", {})
        entry = manifest.get("entrypoint") if manifest else None
        conf = manifest.get("entrypoint_confidence") if manifest else None
        extra = f" | entrypoint={entry or 'unknown'} | confidence={conf or 'n/a'}" if manifest else ""
        print(f"{item['action'].upper():<12} {item['bot']}: {item['path']}{extra}")
    if not write:
        print("\nPreview only. Re-run with --write to create missing manifests.")
    return 0


def _tests(root: Path) -> int:
    cmd = [sys.executable, "-m", "unittest", "discover", "-s", str(root / "tests"), "-p", "test_*.py", "-v"]
    return subprocess.call(cmd, cwd=root)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vm", description="Vending Machine Telegram platform control CLI")
    parser.add_argument("--version", action="version", version=f"vm_core {__version__}")

    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="Show discovered bots and platform state.")
    sub.add_parser("doctor", help="Run safe local diagnostics.")
    sub.add_parser("inventory", help="Refresh machine-readable bot inventory.")
    sub.add_parser("inspect", help="Write a safe bot structure report without reading credentials.")

    manifests = sub.add_parser("manifests", help="Preview or create missing BOT_MANIFEST.json files.")
    manifests.add_argument("--write", action="store_true", help="Create missing manifests; existing manifests are preserved.")

    sub.add_parser("test", help="Run VM platform self-tests.")
    sub.add_parser("init", help="Create missing standard platform directories.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = project_root()
    ensure_platform_dirs(root)

    if args.command == "status":
        return _status(root)
    if args.command == "doctor":
        return _doctor(root)
    if args.command == "inventory":
        return _inventory(root)
    if args.command == "inspect":
        return _inspect(root)
    if args.command == "manifests":
        return _manifests(root, args.write)
    if args.command == "test":
        return _tests(root)
    if args.command == "init":
        print(f"Platform directories ready under: {root}")
        return 0
    return 1
