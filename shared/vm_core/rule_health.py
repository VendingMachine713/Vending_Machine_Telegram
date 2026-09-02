from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any

from .db import PlatformDB
from .learning import _ensure_schema as _ensure_learning_schema
from .paths import project_root
from .rule_registry import active_rule_versions

MIN_HEALTH_SAMPLE = 5
DEGRADATION_MARGIN = 10.0
IMPROVEMENT_MARGIN = 10.0


def _weighted_value(rows: list[dict[str, Any]]) -> float | None:
    total = 0.0
    weight = 0.0
    for row in rows:
        if str(row.get("outcome_type") or "").upper() == "UNKNOWN":
            continue
        confidence = max(0.0, min(1.0, float(row.get("confidence") or 0)))
        total += float(row.get("value_score") or 0) * confidence
        weight += confidence
    if weight <= 0:
        return None
    return round(total / weight, 2)


def _rollout_bucket(rule_id: str, subject_id: str | None) -> int:
    """Mirror the v1.7 deterministic rollout bucket for health attribution."""
    stable_subject = str(subject_id or "unknown")
    digest = sha256(f"{rule_id}:{stable_subject}".encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") % 100


def _in_rollout(rule_id: str, subject_id: str | None, rollout_percent: int) -> bool:
    rollout = max(0, min(100, int(rollout_percent)))
    if rollout <= 0:
        return False
    if rollout >= 100:
        return True
    return _rollout_bucket(rule_id, subject_id) < rollout


def rule_health(root: Path | None = None, *, minimum_sample: int = MIN_HEALTH_SAMPLE) -> list[dict[str, Any]]:
    """Evaluate active governed rule versions without changing or rolling them back.

    At partial rollout, only outcomes belonging to the deterministic rollout cohort are
    attributed to the active registry version. This avoids contaminating treatment health
    with subjects that never received the governed score adjustment.
    """
    root = root or project_root()
    db = PlatformDB(root=root)
    db.init()
    _ensure_learning_schema(db)
    versions = active_rule_versions(root)
    minimum_sample = max(1, int(minimum_sample))
    result: list[dict[str, Any]] = []

    with db.connect() as con:
        for version in versions:
            rule_id = str(version["rule_id"])
            source_version = int(version["source_rule_version"])
            rollout_percent = max(0, min(100, int(version["rollout_percent"])))
            activated_at = str(version.get("activated_at_utc") or version.get("created_at_utc") or "")
            raw_current = [dict(row) for row in con.execute(
                """
                SELECT * FROM intelligence_outcomes
                WHERE rule_id=? AND rule_version=? AND created_at_utc>=?
                ORDER BY id
                """,
                (rule_id, source_version, activated_at),
            )]
            raw_baseline = [dict(row) for row in con.execute(
                """
                SELECT * FROM intelligence_outcomes
                WHERE rule_id=? AND rule_version=? AND created_at_utc<?
                ORDER BY id DESC LIMIT 200
                """,
                (rule_id, source_version, activated_at),
            )]

            current = [row for row in raw_current if _in_rollout(rule_id, row.get("subject_id"), rollout_percent)]
            baseline = [row for row in raw_baseline if _in_rollout(rule_id, row.get("subject_id"), rollout_percent)][:50]
            known_current = [row for row in current if str(row.get("outcome_type") or "").upper() != "UNKNOWN"]
            current_value = _weighted_value(current)
            baseline_value = _weighted_value(baseline)
            delta = None if current_value is None or baseline_value is None else round(current_value - baseline_value, 2)

            if len(known_current) < minimum_sample:
                status = "INSUFFICIENT_DATA"
            elif delta is not None and delta <= -DEGRADATION_MARGIN:
                status = "DEGRADED"
            elif delta is not None and delta >= IMPROVEMENT_MARGIN:
                status = "IMPROVING"
            elif current_value is not None and current_value <= -DEGRADATION_MARGIN:
                status = "DEGRADED"
            else:
                status = "STABLE"

            result.append({
                "rule_id": rule_id,
                "registry_version": int(version["registry_version"]),
                "source_rule_version": source_version,
                "rollout_percent": rollout_percent,
                "sample_size": len(known_current),
                "minimum_sample": minimum_sample,
                "current_weighted_value": current_value,
                "baseline_weighted_value": baseline_value,
                "value_delta": delta,
                "post_activation_outcomes_seen": len(raw_current),
                "post_activation_outcomes_in_cohort": len(current),
                "post_activation_outcomes_excluded": len(raw_current) - len(current),
                "baseline_outcomes_in_cohort": len(baseline),
                "cohort_attribution": "DETERMINISTIC_SUBJECT_BUCKET",
                "status": status,
                "rollback_recommended": status == "DEGRADED",
                "automatic_rollback": False,
            })

    result.sort(key=lambda item: (item["status"] != "DEGRADED", item["rule_id"]))
    return result


def health_summary(root: Path | None = None) -> dict[str, Any]:
    rows = rule_health(root)
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    return {
        "active_rules": len(rows),
        "status_counts": counts,
        "rollback_recommendations": [row for row in rows if row["rollback_recommended"]],
        "rules": rows,
        "cohort_aware": True,
        "automatic_rollback": False,
        "automatic_execution": False,
    }
