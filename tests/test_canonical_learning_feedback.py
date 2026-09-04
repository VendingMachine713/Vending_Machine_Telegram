from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from shared.vm_core.db import PlatformDB
from shared.vm_core.learning import canonical_learning_feedback_summary


class CanonicalLearningFeedbackTests(unittest.TestCase):
    def _seed_recommendation(self, db: PlatformDB, key: str, status: str = "COMPLETED") -> int:
        with db.connect() as con:
            cur = con.execute(
                """
                INSERT INTO intelligence_recommendations(
                    recommendation_key,recommendation_type,subject_type,subject_id,
                    rule_id,rule_version,priority,action,rationale,evidence_json,status,
                    created_at_utc,updated_at_utc
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    key,
                    "canonical_relationship_reengagement_review",
                    "chat",
                    "telegram:chat:aaaaaaaaaaaaaaaaaaaaaaaa",
                    "canonical.test",
                    1,
                    50,
                    "review",
                    "test",
                    "{}",
                    status,
                    "2026-09-01T00:00:00+00:00",
                    "2026-09-01T00:00:00+00:00",
                ),
            )
            return int(cur.lastrowid)

    def _ensure_outcomes(self, db: PlatformDB) -> None:
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
                    created_at_utc TEXT NOT NULL
                );
                """
            )

    def _record_outcome(self, db: PlatformDB, recommendation_id: int, key: str, outcome: str) -> None:
        self._ensure_outcomes(db)
        with db.connect() as con:
            con.execute(
                """
                INSERT INTO intelligence_outcomes(
                    recommendation_id,recommendation_key,recommendation_type,rule_id,rule_version,
                    subject_type,subject_id,outcome_type,value_score,confidence,actor,note,evidence_json,created_at_utc
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    recommendation_id,
                    key,
                    "canonical_relationship_reengagement_review",
                    "canonical.test",
                    1,
                    "chat",
                    "telegram:chat:aaaaaaaaaaaaaaaaaaaaaaaa",
                    outcome,
                    10,
                    1,
                    "operator",
                    "",
                    "{}",
                    "2026-09-02T00:00:00+00:00",
                ),
            )

    def test_missing_database_is_passive_and_does_not_create_state(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = PlatformDB(root=root).path
            summary = canonical_learning_feedback_summary(root=root)
            self.assertEqual(summary["status"], "UNAVAILABLE")
            self.assertFalse(path.exists())
            self.assertTrue(summary["read_only"])

    def test_completed_without_outcome_is_flagged(self) -> None:
        with TemporaryDirectory() as tmp, patch(
            "shared.vm_core.learning.canonical_review_calibration_summary",
            return_value={"status": "INSUFFICIENT_DATA", "calibration_gap": None, "brier_score": None, "positive_rate": None},
        ):
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            self._seed_recommendation(db, "canonical:test:1")
            summary = canonical_learning_feedback_summary(root=root)
            self.assertEqual(summary["completed_recommendations"], 1)
            self.assertEqual(summary["completed_without_outcome"], 1)
            self.assertIn("COLLECT_MISSING_VERIFIED_OUTCOMES", summary["learning_review_flags"])
            self.assertIn("DESIGN_IMMUTABLE_PREDICTION_SNAPSHOTS", summary["learning_review_flags"])

    def test_verified_outcomes_drive_coverage_without_changing_rules(self) -> None:
        with TemporaryDirectory() as tmp, patch(
            "shared.vm_core.learning.canonical_review_calibration_summary",
            return_value={"status": "ACCEPTABLE", "calibration_gap": 0.03, "brier_score": 0.12, "positive_rate": 0.5},
        ):
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            first = self._seed_recommendation(db, "canonical:test:1")
            second = self._seed_recommendation(db, "canonical:test:2")
            self._record_outcome(db, first, "canonical:test:1", "POSITIVE")
            self._record_outcome(db, second, "canonical:test:2", "NEGATIVE")
            summary = canonical_learning_feedback_summary(root=root)
            self.assertEqual(summary["recorded_outcomes"], 2)
            self.assertEqual(summary["known_binary_outcomes"], 2)
            self.assertEqual(summary["outcome_coverage_completed"], 1.0)
            self.assertEqual(summary["calibration_status"], "ACCEPTABLE")
            self.assertFalse(summary["automatic_rule_change"])
            self.assertFalse(summary["automatic_threshold_change"])
            self.assertFalse(summary["automatic_trust_change"])

    def test_calibration_review_required_is_operator_flag_only(self) -> None:
        with TemporaryDirectory() as tmp, patch(
            "shared.vm_core.learning.canonical_review_calibration_summary",
            return_value={"status": "REVIEW_REQUIRED", "calibration_gap": 0.4, "brier_score": 0.5, "positive_rate": 0.2},
        ):
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            summary = canonical_learning_feedback_summary(root=root)
            self.assertIn("REVIEW_CALIBRATION", summary["learning_review_flags"])
            self.assertFalse(summary["automatic_model_training"])
            self.assertFalse(summary["automatic_rule_change"])

    def test_snapshot_presence_is_reported_but_not_backtested_without_implementation(self) -> None:
        with TemporaryDirectory() as tmp, patch(
            "shared.vm_core.learning.canonical_review_calibration_summary",
            return_value={"status": "INSUFFICIENT_DATA", "calibration_gap": None, "brier_score": None, "positive_rate": None},
        ):
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            db.add_event("intelligence.prediction.snapshot", "vm_core", {})
            summary = canonical_learning_feedback_summary(root=root)
            self.assertEqual(summary["prediction_snapshot_events"], 1)
            self.assertEqual(
                summary["prediction_backtest_status"],
                "SNAPSHOTS_PRESENT_BACKTEST_NOT_IMPLEMENTED",
            )
            self.assertNotIn("DESIGN_IMMUTABLE_PREDICTION_SNAPSHOTS", summary["learning_review_flags"])

    def test_no_automatic_authority(self) -> None:
        with TemporaryDirectory() as tmp:
            summary = canonical_learning_feedback_summary(root=Path(tmp))
            self.assertFalse(summary["automatic_model_training"])
            self.assertFalse(summary["automatic_trust_change"])
            self.assertFalse(summary["automatic_threshold_change"])
            self.assertFalse(summary["automatic_rule_change"])
            self.assertFalse(summary["automatic_execution"])
            self.assertFalse(summary["external_action_authority"])


if __name__ == "__main__":
    unittest.main()
