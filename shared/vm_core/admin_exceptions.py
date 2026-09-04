from __future__ import annotations

from pathlib import Path
from typing import Any

from .db import PlatformDB
from .incident_runtime import sync_recovery_incidents
from .paths import project_root
from .recovery_classifier import recovery_plan


def admin_exceptions(root: Path | None = None, limit: int = 20) -> dict[str, Any]:
    root = root or project_root()
    sync_recovery_incidents(root)
    db = PlatformDB(root=root)
    db.init()
    plan = recovery_plan(root)
    exceptions = [
        row for row in plan.get("decisions", [])
        if row.get("classification") in {"BLOCKED", "REVIEW_REQUIRED", "AUTO_RECOVER"}
    ]
    open_incidents = db.incidents(limit, "OPEN")
    return {
        "exception_count": len(exceptions),
        "incident_count": len(open_incidents),
        "exceptions": exceptions[:limit],
        "open_incidents": open_incidents,
        "quiet": not exceptions and not open_incidents,
    }


def format_admin_exceptions(report: dict[str, Any]) -> str:
    if report.get("quiet"):
        return "VM ADMIN BY EXCEPTION\nNo material recovery exceptions."
    lines = [
        "VM ADMIN BY EXCEPTION",
        f"Exceptions: {report['exception_count']} | Open incidents: {report['incident_count']}",
        "",
    ]
    for row in report["exceptions"]:
        lines.append(
            f"{row.get('classification'):<16} {row.get('service')} | {row.get('failure_class')} -> {row.get('action')}"
        )
        lines.append(f"  {row.get('reason')}")
    return "\n".join(lines)
