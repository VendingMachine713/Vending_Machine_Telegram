from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from .db import PlatformDB
from .paths import project_root

AGGREGATION_CONTRACT_VERSION = 1


def _counts(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    values = Counter(str(row.get(field) or "UNKNOWN").upper() for row in rows)
    return dict(sorted(values.items()))


def incident_intelligence_snapshot(
    root: Path | None = None,
    *,
    limit: int = 20,
) -> dict[str, Any]:
    """Return one passive aggregation of operator incidents and Brain intelligence."""
    root = root or project_root()
    db = PlatformDB(root=root)
    db.init()

    open_incidents = db.incidents(limit=limit, status="OPEN")
    active_signals = db.signals(limit=limit, status="ACTIVE")
    recommendations = db.recommendations(limit=limit, status=None)
    actionable_recommendations = [
        row for row in recommendations
        if str(row.get("status") or "").upper() in {"PROPOSED", "BLOCKED"}
    ]

    incident_subjects = {
        (str(row.get("subject_type") or "unknown"), str(row.get("subject_id") or "unknown"))
        for row in open_incidents
        if row.get("subject_type") or row.get("subject_id")
    }
    intelligence_subjects = {
        (str(row.get("subject_type") or "unknown"), str(row.get("subject_id") or "unknown"))
        for row in [*active_signals, *actionable_recommendations]
        if row.get("subject_type") or row.get("subject_id")
    }
    correlated_subjects = sorted(incident_subjects & intelligence_subjects)

    return {
        "contract_version": AGGREGATION_CONTRACT_VERSION,
        "open_incident_count": len(open_incidents),
        "active_signal_count": len(active_signals),
        "actionable_recommendation_count": len(actionable_recommendations),
        "incident_severity_counts": _counts(open_incidents, "severity"),
        "incident_type_counts": _counts(open_incidents, "incident_type"),
        "signal_type_counts": _counts(active_signals, "signal_type"),
        "recommendation_status_counts": _counts(recommendations, "status"),
        "correlated_subject_count": len(correlated_subjects),
        "correlated_subjects": [
            {"subject_type": subject_type, "subject_id": subject_id}
            for subject_type, subject_id in correlated_subjects
        ],
        "open_incidents": open_incidents,
        "active_signals": active_signals,
        "actionable_recommendations": actionable_recommendations,
        "automatic_execution": False,
        "external_action_authority": False,
    }
