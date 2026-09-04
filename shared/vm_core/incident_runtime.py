from __future__ import annotations

from pathlib import Path
from typing import Any

from .db import PlatformDB
from .paths import project_root
from .recovery_classifier import recovery_plan


def sync_recovery_incidents(root: Path | None = None) -> dict[str, Any]:
    root = root or project_root()
    db = PlatformDB(root=root)
    db.init()
    plan = recovery_plan(root)
    active_keys: set[str] = set()
    opened = 0
    resolved = 0

    for row in plan.get("decisions", []):
        service = str(row.get("service") or "unknown")
        classification = str(row.get("classification") or "UNKNOWN")
        if classification in {"HEALTHY", "WAIT_AND_RETRY"}:
            continue
        key = f"recovery:{service}"
        active_keys.add(key)
        severity = "ERROR" if classification in {"BLOCKED", "REVIEW_REQUIRED"} else "WARNING"
        db.upsert_incident(
            key,
            "recovery",
            "vm_core",
            severity,
            f"{classification}: {row.get('failure_class')} -> {row.get('action')}",
            subject_type="service",
            subject_id=service,
            evidence={
                "classification": classification,
                "failure_class": row.get("failure_class"),
                "action": row.get("action"),
                "reason": row.get("reason"),
            },
        )
        opened += 1

    for existing in db.incidents(200, "OPEN"):
        key = str(existing.get("incident_key") or "")
        if key.startswith("recovery:") and key not in active_keys:
            if db.resolve_incident(key):
                resolved += 1

    return {
        "open_or_refreshed": opened,
        "resolved": resolved,
        "open_incidents": db.incidents(100, "OPEN"),
    }


def incident_timeline(root: Path | None = None, limit: int = 50) -> list[dict[str, Any]]:
    root = root or project_root()
    db = PlatformDB(root=root)
    db.init()
    return db.incidents(limit, None)
