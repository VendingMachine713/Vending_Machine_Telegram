#!/usr/bin/env python3
"""Safe first-run bootstrap for VM Platform Foundation v0.1.0."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.vm_core.manifests import write_inventory
from shared.vm_core.paths import ensure_platform_dirs
from shared.vm_core.doctor import run_doctor, write_diagnostics


def main() -> int:
    ensure_platform_dirs(ROOT)
    inventory = write_inventory(ROOT)
    report = run_doctor(ROOT)
    _, text_report = write_diagnostics(report, ROOT)

    print("=" * 72)
    print(" VM PLATFORM FOUNDATION v0.1.0")
    print("=" * 72)
    print(f"Root:       {ROOT}")
    print(f"Inventory:  {inventory}")
    print(f"Diagnostic: {text_report}")
    print()
    print("No existing bot files were changed.")
    print("No credentials or Telegram session contents were read.")
    print()
    print("Next commands:")
    print("  py vm.py status")
    print("  py vm.py doctor")
    print("  py vm.py manifests")
    print("  py vm.py test")
    return 2 if report["summary"]["FAIL"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
