from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import sqlite3
from typing import Any

from .canonical_review_calibration import canonical_review_calibration_report
from .db import PlatformDB
from .paths import project_root


_RECOMMENDATION_TYPE = "canonical_relationship_reengagement_review"
_INFERENCE_TYPE = "intelligence.inference.relationship_reengagement_opportunity"
_EVENT_TYPES = {
    "recommendation.proposed",
    "recommendation.supersedes",
    "recommendation.accepted",
    "recommendation.dismissed",
    "recommendation.completed",
    "recommendation.expired",
    "recommendation.outcome_recorded",
}
_STAGE_BY_EVENT = {
    _INFERENCE_TYPE: "INFERENCE",
    "recommendation.proposed": "PROPOSAL",
    "recommendation.supersedes": "SUPERSESSION",
    "recommendation.accepted": "DECISION",
    "recommendation.dismissed": "DECISION",
    "recommendation.completed": "COMPLETION",
    "recommendation.expired": "EXPIRY",
    "recommendation.outcome_recorded": "OUTCOME",
}
_STATUS_BY_EVENT = {
    "recommendation.proposed": "PROPOSED",
    "recommendation.accepted": "ACCEPTED",
    "recommendation.dismissed": "DISMISSED",
    "recommendation.completed": "COMPLETED",
    "recommendation.expired": "EXPIRED",
}


def _json_dict(value: Any) -> tuple[dict[str, Any], bool]:
    if isinstance(value, dict):
        return value, True
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}, False
    return (parsed, True) if isinstance(parsed, dict) else ({}, False)


def _canonical_subject(value: Any) -> str | None:
    subject = str(value or "").strip()
    parts = subject.split(":")
    if len(parts) != 3 or parts[0] != "telegram" or parts[1] not in {"chat", "user"}:
        return None
    digest = parts[2]
    if len(digest) != 24 or any(ch not in "0123456789abcdef" for ch in digest.lower()):
        return None
    return subject


def _readonly_connect(path: Path) -> sqlite3.Connection | None:
    if not path.exists():
        return None
    try:
        con = sqlite3.connect(
            f"file:{path.resolve().as_posix()}?mode=ro", uri=True, timeout=5
        )
    except sqlite3.Error:
        return None
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA query_only=ON")
    except sqlite3.Error:
        con.close()
        return None
    return con


def _safe_int(value: Any) -> int | None:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _event_item(row: dict[str, Any], recommendation_key: str) -> tuple[dict[str, Any] | None, bool]:
    event_type = str(row.get("event_type") or "")
    if event_type not in _EVENT_TYPES and event_type != _INFERENCE_TYPE:
        return None, True
    payload, payload_valid = _json_dict(row.get("payload_json"))
    evidence, evidence_valid = _json_dict(row.get("evidence_json"))
    valid = payload_valid and evidence_valid
    timestamp = str(row.get("created_at_utc") or "").strip()
    event_id = _safe_int(row.get("id"))
    if not timestamp or event_id is None:
        valid = False

    item: dict[str, Any] = {
        "stage": _STAGE_BY_EVENT[event_type],
        "event_type": event_type,
        "event_id": event_id,
        "timestamp_utc": timestamp or None,
        "source": str(row.get("source") or "unknown"),
        "recommendation_key": recommendation_key,
    }
    status = _STATUS_BY_EVENT.get(event_type)
    if status:
        item["status"] = status
    if event_type == _INFERENCE_TYPE:
        attributes = payload.get("attributes") if isinstance(payload.get("attributes"), dict) else {}
        item.update(
            {
                "confidence": payload.get("confidence"),
                "opportunity_score": attributes.get("opportunity_score"),
                "support_signature": attributes.get("support_signature"),
                "summary": "Canonical inference supporting operator review",
            }
        )
    elif event_type == "recommendation.proposed":
        item["summary"] = "Canonical recommendation proposed for operator review"
    elif event_type == "recommendation.supersedes":
        item.update(
            {
                "predecessor_recommendation_key": payload.get("predecessor_recommendation_key"),
                "replacement_recommendation_key": payload.get("replacement_recommendation_key"),
                "reason": payload.get("reason"),
                "summary": "New canonical evidence superseded an expired recommendation",
            }
        )
    elif event_type in {"recommendation.accepted", "recommendation.dismissed", "recommendation.completed", "recommendation.expired"}:
        item.update(
            {
                "actor": payload.get("actor"),
                "note": payload.get("note"),
                "summary": f"Recommendation {status.lower() if status else 'updated'}",
            }
        )
    elif event_type == "recommendation.outcome_recorded":
        item.update(
            {
                "outcome_type": payload.get("outcome_type"),
                "value_score": payload.get("value_score"),
                "confidence": payload.get("confidence"),
                "actor": payload.get("actor"),
                "note": payload.get("note"),
                "summary": "Verified operator outcome recorded",
            }
        )

    # Never expose arbitrary payload/evidence fields: they may contain native IDs.
    item["data_valid"] = valid
    return item, valid


def canonical_review_audit_timeline(
    *, root: Path | None = None, limit: int = 20
) -> dict[str, Any]:
    """Return a passive canonical review history from inference through calibration.

    This is a read-only projection over the existing recommendation, event, governance
    and learning records. It does not initialise schema, mutate state, accept or execute
    recommendations, or alter calibration/rules.
    """
    root = root or project_root()
    path = PlatformDB(root=root).path
    result: dict[str, Any] = {
        "status": "UNAVAILABLE",
        "count": 0,
        "timelines": [],
        "malformed_rows": 0,
        "duplicate_events_ignored": 0,
        "read_only": True,
        "operator_review_required": True,
        "automatic_acceptance": False,
        "automatic_execution": False,
        "automatic_threshold_change": False,
        "automatic_rule_change": False,
        "external_action_authority": False,
    }
    con = _readonly_connect(path)
    if con is None:
        return result
    try:
        tables = {
            str(row[0])
            for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name IN ('intelligence_recommendations','events')"
            ).fetchall()
        }
        if tables != {"intelligence_recommendations", "events"}:
            return result
        try:
            rec_rows = con.execute(
                "SELECT * FROM intelligence_recommendations "
                "WHERE recommendation_type=? ORDER BY id DESC LIMIT ?",
                (_RECOMMENDATION_TYPE, max(1, min(500, int(limit)))),
            ).fetchall()
        except (sqlite3.Error, TypeError, ValueError):
            return result

        recommendations = [dict(row) for row in rec_rows]
        replacement_by_predecessor: dict[str, str] = {}
        parsed_evidence: dict[str, dict[str, Any]] = {}
        for recommendation in recommendations:
            key = str(recommendation.get("recommendation_key") or "").strip()
            evidence, valid = _json_dict(recommendation.get("evidence_json"))
            if not valid:
                result["malformed_rows"] += 1
            parsed_evidence[key] = evidence
            predecessor = str(evidence.get("supersedes_recommendation_key") or "").strip()
            if predecessor and key:
                replacement_by_predecessor[predecessor] = key

        calibration = asdict(canonical_review_calibration_report(root=root))
        timelines: list[dict[str, Any]] = []
        for recommendation in recommendations:
            key = str(recommendation.get("recommendation_key") or "").strip()
            subject = _canonical_subject(recommendation.get("subject_id"))
            if not key or not key.startswith("canonical:") or subject is None:
                result["malformed_rows"] += 1
                continue
            evidence = parsed_evidence.get(key, {})
            recommendation_id = _safe_int(recommendation.get("id"))
            if recommendation_id is None:
                result["malformed_rows"] += 1
                continue

            rows: list[dict[str, Any]] = []
            inference_id = _safe_int(evidence.get("canonical_inference_event_id"))
            if inference_id is not None:
                inference = con.execute(
                    "SELECT * FROM events WHERE id=? AND event_type=?",
                    (inference_id, _INFERENCE_TYPE),
                ).fetchone()
                if inference is not None:
                    rows.append(dict(inference))
            correlated = con.execute(
                "SELECT * FROM events WHERE correlation_id=? ORDER BY id ASC",
                (f"recommendation:{recommendation_id}",),
            ).fetchall()
            rows.extend(dict(row) for row in correlated)

            events: list[dict[str, Any]] = []
            seen: set[tuple[Any, ...]] = set()
            has_outcome = False
            for row in rows:
                item, valid = _event_item(row, key)
                if item is None:
                    continue
                if not valid:
                    result["malformed_rows"] += 1
                fingerprint = (
                    item.get("event_type"), item.get("status"), item.get("outcome_type"),
                    item.get("predecessor_recommendation_key"),
                    item.get("replacement_recommendation_key"), item.get("actor"), item.get("note"),
                    item.get("support_signature"),
                )
                if fingerprint in seen:
                    result["duplicate_events_ignored"] += 1
                    continue
                seen.add(fingerprint)
                events.append(item)
                has_outcome = has_outcome or item.get("stage") == "OUTCOME"

            if has_outcome:
                events.append(
                    {
                        "stage": "CALIBRATION",
                        "event_type": "canonical_review.calibration_snapshot",
                        "event_id": None,
                        "timestamp_utc": None,
                        "source": "vm_core.canonical_review_calibration",
                        "recommendation_key": key,
                        "status": calibration.get("status"),
                        "known_binary_outcomes": calibration.get("known_binary_outcomes"),
                        "positive_rate": calibration.get("positive_rate"),
                        "brier_score": calibration.get("brier_score"),
                        "summary": "Read-only canonical review calibration snapshot",
                        "data_valid": True,
                    }
                )

            predecessor = str(evidence.get("supersedes_recommendation_key") or "").strip() or None
            timelines.append(
                {
                    "recommendation_key": key,
                    "canonical_subject_id": subject,
                    "current_status": str(recommendation.get("status") or "UNKNOWN").upper(),
                    "lineage": {
                        "supersedes": predecessor,
                        "superseded_by": replacement_by_predecessor.get(key),
                    },
                    "events": events,
                }
            )

        result["timelines"] = timelines
        result["count"] = len(timelines)
        result["status"] = "PARTIAL" if result["malformed_rows"] else "OK"
        return result
    except sqlite3.Error:
        return result
    finally:
        con.close()


def canonical_review_audit_summary(
    *, root: Path | None = None, limit: int = 20
) -> dict[str, Any]:
    """Concise Mission Control surface for the unified canonical audit history."""
    result = canonical_review_audit_timeline(root=root, limit=limit)
    stage_counts: dict[str, int] = {}
    recent: list[dict[str, Any]] = []
    for timeline in result["timelines"]:
        for event in timeline["events"]:
            stage = str(event.get("stage") or "UNKNOWN")
            stage_counts[stage] = stage_counts.get(stage, 0) + 1
            recent.append(event)
    recent.sort(
        key=lambda event: (str(event.get("timestamp_utc") or ""), int(event.get("event_id") or 0)),
        reverse=True,
    )
    result["stage_counts"] = dict(sorted(stage_counts.items()))
    result["recent_history"] = recent[: max(1, min(100, int(limit)))]
    return result
