from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3
from typing import Any

from .canonical_review_calibration import canonical_review_calibration_summary
from .db import PlatformDB, utcnow
from .paths import project_root


OUTCOME_TYPES = {"POSITIVE", "NEUTRAL", "NEGATIVE", "UNKNOWN"}
_CANONICAL_RECOMMENDATION_TYPE = "canonical_relationship_reengagement_review"
_MIN_BINARY_OUTCOMES = 8


class LearningError(RuntimeError):
    """Raised when VM Brain learning/outcome data is invalid."""


@dataclass(frozen=True)
class RecordedOutcome:
    outcome_id: int
    recommendation_key: str
    outcome_type: str
    value_score: float
    actor: str
    event_id: int


def _ensure_schema(db: PlatformDB) -> None:
    with db.connect() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS intelligence_outcomes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recommendation_id INTEGER NOT NULL UNIQUE,
                recommendation_key TEXT NOT NULL,
                recommendation_type TEXT NOT NULL,
                rule_id TEXT NOT NULL,
                rule_version INTEGER NOT NULL,
                subject_type TEXT,
                subject_id TEXT,
                outcome_type TEXT NOT NULL,
                value_score REAL NOT NULL DEFAULT 0,
                confidence REAL NOT NULL DEFAULT 1,
                actor TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                evidence_json TEXT NOT NULL DEFAULT '{}',
                created_at_utc TEXT NOT NULL,
                FOREIGN KEY(recommendation_id) REFERENCES intelligence_recommendations(id)
            );
            CREATE INDEX IF NOT EXISTS idx_outcomes_rule
                ON intelligence_outcomes(rule_id, rule_version, created_at_utc);
            CREATE INDEX IF NOT EXISTS idx_outcomes_type
                ON intelligence_outcomes(outcome_type, created_at_utc);
            """
        )


def _recommendation(db: PlatformDB, recommendation_key: str) -> dict[str, Any]:
    with db.connect() as con:
        row = con.execute(
            "SELECT * FROM intelligence_recommendations WHERE recommendation_key=?",
            (recommendation_key,),
        ).fetchone()
    if row is None:
        raise LearningError(f"recommendation not found: {recommendation_key}")
    return dict(row)


def record_outcome(
    recommendation_key: str,
    outcome_type: str,
    *,
    value_score: float = 0,
    confidence: float = 1,
    actor: str = "operator",
    note: str | None = None,
    evidence: dict[str, Any] | None = None,
    root: Path | None = None,
) -> RecordedOutcome:
    """Record one verified outcome for a completed recommendation.

    This stores feedback for analysis only. It does not modify recommendation rules,
    scoring thresholds, bot configuration or Telegram state.
    """
    root = root or project_root()
    db = PlatformDB(root=root)
    db.init()
    _ensure_schema(db)

    normalized = outcome_type.upper().strip()
    if normalized not in OUTCOME_TYPES:
        raise LearningError(f"unsupported outcome type: {outcome_type}")
    score = max(-100.0, min(100.0, float(value_score)))
    conf = max(0.0, min(1.0, float(confidence)))
    actor = actor.strip() or "operator"
    row = _recommendation(db, recommendation_key)
    if str(row.get("status") or "").upper() != "COMPLETED":
        raise LearningError("outcomes may only be recorded for COMPLETED recommendations")

    now = utcnow()
    payload = {
        "recommendation_key": recommendation_key,
        "outcome_type": normalized,
        "value_score": score,
        "confidence": conf,
        "actor": actor,
        "note": (note or "")[:1000],
        "automatic_rule_change": False,
        "automatic_execution": False,
    }
    outcome_evidence = dict(evidence or {})
    outcome_evidence.update(
        {
            "recommendation_id": row["id"],
            "rule_id": row["rule_id"],
            "rule_version": row["rule_version"],
        }
    )

    with db.connect() as con:
        existing = con.execute(
            "SELECT id FROM intelligence_outcomes WHERE recommendation_id=?",
            (row["id"],),
        ).fetchone()
        if existing is not None:
            raise LearningError(f"outcome already recorded for: {recommendation_key}")
        cur = con.execute(
            """
            INSERT INTO intelligence_outcomes(
                recommendation_id,recommendation_key,recommendation_type,rule_id,rule_version,
                subject_type,subject_id,outcome_type,value_score,confidence,actor,note,
                evidence_json,created_at_utc
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                row["id"], recommendation_key, row["recommendation_type"], row["rule_id"],
                row["rule_version"], row.get("subject_type"), row.get("subject_id"),
                normalized, score, conf, actor, (note or "")[:1000],
                json.dumps(outcome_evidence, ensure_ascii=False), now,
            ),
        )
        outcome_id = int(cur.lastrowid)
        event_cur = con.execute(
            """
            INSERT INTO events(
                event_type,source,payload_json,created_at_utc,event_version,severity,
                subject_type,subject_id,correlation_id,evidence_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "recommendation.outcome_recorded", "vm_core.learning",
                json.dumps(payload, ensure_ascii=False), now, 1, "INFO",
                row.get("subject_type"), row.get("subject_id"),
                f"recommendation:{row['id']}",
                json.dumps(outcome_evidence, ensure_ascii=False),
            ),
        )
        event_id = int(event_cur.lastrowid)

    return RecordedOutcome(outcome_id, recommendation_key, normalized, score, actor, event_id)


def outcomes(root: Path | None = None, *, limit: int = 100) -> list[dict[str, Any]]:
    root = root or project_root()
    db = PlatformDB(root=root)
    db.init()
    _ensure_schema(db)
    with db.connect() as con:
        rows = con.execute(
            "SELECT * FROM intelligence_outcomes ORDER BY id DESC LIMIT ?",
            (max(1, int(limit)),),
        ).fetchall()
    return [dict(row) for row in rows]


def rule_performance(root: Path | None = None) -> list[dict[str, Any]]:
    """Return descriptive rule performance only; never alter rules automatically."""
    rows = outcomes(root, limit=5000)
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row["rule_id"]), int(row["rule_version"]))].append(row)

    result: list[dict[str, Any]] = []
    for (rule_id, rule_version), items in grouped.items():
        counts = {key: 0 for key in OUTCOME_TYPES}
        weighted_total = 0.0
        confidence_total = 0.0
        for item in items:
            counts[str(item["outcome_type"])] += 1
            conf = float(item["confidence"])
            weighted_total += float(item["value_score"]) * conf
            confidence_total += conf
        weighted_value = weighted_total / confidence_total if confidence_total else 0.0
        known = counts["POSITIVE"] + counts["NEUTRAL"] + counts["NEGATIVE"]
        positive_rate = counts["POSITIVE"] / known if known else None
        result.append(
            {
                "rule_id": rule_id,
                "rule_version": rule_version,
                "outcomes": len(items),
                "counts": counts,
                "positive_rate": positive_rate,
                "confidence_weighted_value": round(weighted_value, 2),
                "learning_ready": known >= 5,
                "automatic_rule_change": False,
            }
        )
    result.sort(key=lambda x: (-x["outcomes"], x["rule_id"], x["rule_version"]))
    return result


def learning_summary(root: Path | None = None) -> dict[str, Any]:
    rows = outcomes(root, limit=5000)
    rules = rule_performance(root)
    counts = {key: 0 for key in OUTCOME_TYPES}
    for row in rows:
        counts[str(row["outcome_type"])] += 1
    return {
        "recorded_outcomes": len(rows),
        "counts": counts,
        "rules_observed": len(rules),
        "rules_learning_ready": sum(1 for rule in rules if rule["learning_ready"]),
        "rule_performance": rules,
        "automatic_rule_change": False,
        "automatic_execution": False,
    }


def _readonly_connect(path: Path) -> sqlite3.Connection | None:
    if not path.exists():
        return None
    try:
        con = sqlite3.connect(
            f"file:{path.resolve().as_posix()}?mode=ro",
            uri=True,
            timeout=5,
        )
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA query_only=ON")
        return con
    except sqlite3.Error:
        try:
            con.close()  # type: ignore[possibly-undefined]
        except (UnboundLocalError, sqlite3.Error):
            pass
        return None


def canonical_learning_feedback_summary(
    *,
    root: Path | None = None,
    limit: int = 5000,
) -> dict[str, Any]:
    """Return passive learning readiness and verified-outcome feedback health.

    This extends the existing learning subsystem. It deliberately refuses to claim
    historical prediction/decision accuracy until immutable prediction snapshots
    exist. Current forecasts are recomputed views and must not be compared against
    old outcomes as though they were the forecasts that existed at decision time.
    """
    root = root or project_root()
    path = PlatformDB(root=root).path
    result: dict[str, Any] = {
        "status": "UNAVAILABLE",
        "canonical_recommendations": 0,
        "completed_recommendations": 0,
        "recorded_outcomes": 0,
        "completed_without_outcome": 0,
        "outcome_coverage_completed": None,
        "outcome_counts": {key: 0 for key in sorted(OUTCOME_TYPES)},
        "known_binary_outcomes": 0,
        "prediction_snapshot_events": 0,
        "prediction_backtest_status": "NOT_READY_NO_IMMUTABLE_PREDICTION_SNAPSHOTS",
        "decision_backtest_status": "NOT_READY_NO_IMMUTABLE_PREDICTION_SNAPSHOTS",
        "learning_review_flags": [],
        "read_only": True,
        "automatic_model_training": False,
        "automatic_trust_change": False,
        "automatic_threshold_change": False,
        "automatic_rule_change": False,
        "automatic_execution": False,
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
                "AND name IN ('intelligence_recommendations','intelligence_outcomes','events')"
            ).fetchall()
        }
        if "intelligence_recommendations" not in tables:
            result["status"] = "RECOMMENDATIONS_TABLE_MISSING"
            return result
        try:
            requested = max(1, min(10000, int(limit)))
        except (TypeError, ValueError):
            requested = 5000

        recommendations = con.execute(
            "SELECT id,status FROM intelligence_recommendations "
            "WHERE recommendation_type=? ORDER BY id DESC LIMIT ?",
            (_CANONICAL_RECOMMENDATION_TYPE, requested),
        ).fetchall()
        recommendation_ids = [int(row["id"]) for row in recommendations]
        completed = {
            int(row["id"])
            for row in recommendations
            if str(row["status"] or "").upper() == "COMPLETED"
        }
        outcome_rows: list[sqlite3.Row] = []
        if recommendation_ids and "intelligence_outcomes" in tables:
            placeholders = ",".join("?" for _ in recommendation_ids)
            outcome_rows = con.execute(
                f"SELECT recommendation_id,outcome_type,value_score,confidence,rule_id,rule_version "
                f"FROM intelligence_outcomes WHERE recommendation_id IN ({placeholders})",
                recommendation_ids,
            ).fetchall()

        outcome_by_id = {int(row["recommendation_id"]): row for row in outcome_rows}
        counts = {key: 0 for key in sorted(OUTCOME_TYPES)}
        for row in outcome_rows:
            outcome_type = str(row["outcome_type"] or "UNKNOWN").upper()
            if outcome_type not in counts:
                outcome_type = "UNKNOWN"
            counts[outcome_type] += 1
        known_binary = counts["POSITIVE"] + counts["NEGATIVE"]
        missing = sum(1 for recommendation_id in completed if recommendation_id not in outcome_by_id)
        coverage = (
            (len(completed) - missing) / len(completed)
            if completed
            else None
        )

        prediction_snapshots = 0
        if "events" in tables:
            prediction_snapshots = int(
                con.execute(
                    "SELECT COUNT(*) FROM events WHERE event_type IN "
                    "('intelligence.prediction.snapshot','decision.prediction_snapshot')"
                ).fetchone()[0]
            )

        result.update(
            {
                "status": "OK",
                "canonical_recommendations": len(recommendations),
                "completed_recommendations": len(completed),
                "recorded_outcomes": len(outcome_rows),
                "completed_without_outcome": missing,
                "outcome_coverage_completed": round(coverage, 4) if coverage is not None else None,
                "outcome_counts": counts,
                "known_binary_outcomes": known_binary,
                "prediction_snapshot_events": prediction_snapshots,
            }
        )
        if prediction_snapshots:
            result["prediction_backtest_status"] = "SNAPSHOTS_PRESENT_BACKTEST_NOT_IMPLEMENTED"
            result["decision_backtest_status"] = "SNAPSHOTS_PRESENT_BACKTEST_NOT_IMPLEMENTED"
    except sqlite3.Error:
        result["status"] = "READ_ERROR"
        return result
    finally:
        con.close()

    calibration = canonical_review_calibration_summary(root=root)
    result["calibration_status"] = calibration.get("status")
    result["calibration_gap"] = calibration.get("calibration_gap")
    result["brier_score"] = calibration.get("brier_score")
    result["positive_rate"] = calibration.get("positive_rate")

    flags: list[str] = []
    if result["completed_without_outcome"]:
        flags.append("COLLECT_MISSING_VERIFIED_OUTCOMES")
    if int(result["known_binary_outcomes"] or 0) < _MIN_BINARY_OUTCOMES:
        flags.append("COLLECT_MORE_BINARY_OUTCOMES")
    if calibration.get("status") == "REVIEW_REQUIRED":
        flags.append("REVIEW_CALIBRATION")
    if int(result["prediction_snapshot_events"] or 0) == 0:
        flags.append("DESIGN_IMMUTABLE_PREDICTION_SNAPSHOTS")
    result["learning_review_flags"] = flags
    return result
