from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from shared.vm_core.db import PlatformDB
from shared.vm_core.learning import LearningError, learning_summary, record_outcome, rule_performance


class VMIntelligenceLearningTests(unittest.TestCase):
    def _root(self, tmp: str) -> Path:
        root = Path(tmp)
        (root / "state").mkdir(parents=True, exist_ok=True)
        return root

    def _recommendation(self, root: Path, *, key: str = "recommendation:test:123", status: str = "COMPLETED", rule_id: str = "test_rule") -> PlatformDB:
        db = PlatformDB(root=root)
        db.init()
        db.upsert_recommendation(
            key,
            "relationship_review",
            "Review evidence.",
            "Test recommendation.",
            rule_id=rule_id,
            rule_version=1,
            subject_type="chat",
            subject_id="123",
            priority=80,
            confidence=.9,
            status=status,
            evidence={"automatic_execution": False},
        )
        return db

    def test_completed_recommendation_accepts_one_outcome_and_writes_audit_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            db = self._recommendation(root)
            result = record_outcome(
                "recommendation:test:123",
                "positive",
                value_score=75,
                confidence=.8,
                actor="admin",
                note="Recommendation produced a useful result.",
                root=root,
            )
            self.assertEqual(result.outcome_type, "POSITIVE")
            self.assertEqual(result.value_score, 75)
            events = db.events(10, "recommendation.outcome_recorded")
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["correlation_id"], "recommendation:1")

    def test_non_completed_recommendation_rejects_outcome(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            self._recommendation(root, status="ACCEPTED")
            with self.assertRaises(LearningError):
                record_outcome("recommendation:test:123", "POSITIVE", root=root)

    def test_duplicate_outcome_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            self._recommendation(root)
            record_outcome("recommendation:test:123", "NEUTRAL", root=root)
            with self.assertRaises(LearningError):
                record_outcome("recommendation:test:123", "POSITIVE", root=root)

    def test_score_and_confidence_are_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            self._recommendation(root)
            result = record_outcome(
                "recommendation:test:123",
                "NEGATIVE",
                value_score=-999,
                confidence=7,
                root=root,
            )
            self.assertEqual(result.value_score, -100)
            summary = learning_summary(root)
            perf = summary["rule_performance"][0]
            self.assertEqual(perf["confidence_weighted_value"], -100)

    def test_rule_performance_is_descriptive_and_requires_sample_before_learning_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            for idx in range(5):
                key = f"recommendation:test:{idx}"
                self._recommendation(root, key=key, rule_id="repeat_rule")
                record_outcome(
                    key,
                    "POSITIVE" if idx < 4 else "NEGATIVE",
                    value_score=50 if idx < 4 else -50,
                    root=root,
                )
            rows = rule_performance(root)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["outcomes"], 5)
            self.assertAlmostEqual(rows[0]["positive_rate"], .8)
            self.assertTrue(rows[0]["learning_ready"])
            self.assertFalse(rows[0]["automatic_rule_change"])


if __name__ == "__main__":
    unittest.main()
