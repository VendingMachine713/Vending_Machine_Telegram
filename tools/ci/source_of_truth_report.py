"""Generate a read-only source-of-truth and Relationship Manager reconciliation report."""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.vm_core.reconciliation import compare_nested_bot
from shared.vm_core.source_of_truth import format_source_check, source_check


def main() -> int:
    source = source_check(ROOT)
    relationship = compare_nested_bot(ROOT, "VM_Relationship_Manager")
    report = {
        "schema_version": 1,
        "source_of_truth": source,
        "relationship_manager_reconciliation": relationship,
        "read_only": True,
        "destructive_action_performed": False,
    }

    output = ROOT / "diagnostics" / "source_of_truth_report.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(format_source_check(source))
    print("\nRELATIONSHIP MANAGER RECONCILIATION")
    print(f"Nested copy         : {'YES' if relationship.get('nested_exists') else 'NO'}")
    print(f"Exact duplicates    : {len(relationship.get('exact_duplicates', []))}")
    print(f"Different files     : {len(relationship.get('different', []))}")
    print(f"Nested-only files   : {len(relationship.get('nested_only', []))}")
    print(f"Outer-only files    : {len(relationship.get('outer_only', []))}")
    print(f"Report              : {output}")
    print("Mode                : READ ONLY")

    # This diagnostic command reports state; it does not fail merely because cleanup
    # work remains. CI policy can choose stricter gating later once reconciliation is complete.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
