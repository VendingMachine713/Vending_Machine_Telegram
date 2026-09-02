from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from shared.vm_core.calibration import calibration_report, calibration_summary
from shared.vm_core.db import PlatformDB
from shared.vm_core.learning import record_outcome


class VMIntelligenceCalibrationTests(unittest.TestCase):
    def _root(self, tmp: str) -> Path:
        root = Path(tmp)
        (root / "state").mkdir(parents=True, exist_ok=True)
        return root

    def _completed(self, root: Path, key: str, rule_id: str = "rule_a") -> None:
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
            subject_id=key,
            priority=80,
            confidence=0.9,
            status="COMPLETED",
            evidence={"automatic_execution": False},
        )

    def test_insufficient_data_never_proposes_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            for i in range(3):
                key = f"recommendation:test:{i}"
                self._completed(root, key)
                record_outcome(key, "POSITIVE", value_score=50, confidence=0.9, root=root)
            row = calibration_report(root)[0]
            self.assertEqual(row["status"], "INSUFFICIENT_DATA")
            self.assertEqual(row["proposed_score_delta"], 0.0)
            self.assertFalse(row["automatic_application"])

    def test_strong_rule_gets_bounded_positive_proposal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            for i in range(20):
                key = f"recommendation:strong:{i}"
                self._completed(root, key, "strong_rule")
                record_outcome(key, "POSITIVE", value_score=60, confidence=0.9, root=root)
            row = calibration_report(root)[0]
            self.assertEqual(row["status"], "STRONG")
            self.assertGreater(row["proposed_score_delta"], 0)
            self.assertLessEqual(abs(row["proposed_score_delta"]), 10)

    def test_weak_rule_gets_bounded_negative_proposal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            for i in range(10):
                key = f"recommendation:weak:{i}"
                self._completed(root, key, "weak_rule")
                record_outcome(key, "NEGATIVE", value_score=-50, confidence=0.9, root=root)
            row = calibration_report(root)[0]
            self.assertEqual(row["status"], "WEAK")
            self.assertLess(row["proposed_score_delta"], 0)
            self.assertLessEqual(abs(row["proposed_score_delta"]), 10)

    def test_summary_is_advisory_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            summary = calibration_summary(root)
            self.assertFalse(summary["automatic_application"])
            self.assertFalse(summary["automatic_execution"])


if __name__ == "__main__":
    unittest.main()
