from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from shared.vm_core.canonical_recommendations import propose_canonical_reengagement_reviews
from shared.vm_core.canonical_review_calibration import canonical_review_calibration_report
from shared.vm_core.canonical_review_feedback import (
    record_canonical_review_outcome,
    transition_canonical_review,
)
from shared.vm_core.db import PlatformDB
from shared.vm_core.intelligence_trust import canonical_entity_id


class CanonicalReviewCalibrationTests(unittest.TestCase):
    def _seed_pair(self, db: PlatformDB, chat_id: str, *, confidence: float = 0.9) -> None:
        db.upsert_signal(
            f"cross:relationship_activity:{chat_id}",
            "relationship_activity_opportunity",
            "Legacy opportunity",
            subject_type="chat",
            subject_id=chat_id,
            score=70,
            confidence=0.9,
            evidence={"suppressed": False},
        )
        db.add_event(
            "intelligence.inference.relationship_reengagement_opportunity",
            "vm_core",
            {
                "confidence": confidence,
                "rationale": "Canonical re-engagement evidence",
                "attributes": {
                    "support_signature": f"support-{chat_id}",
                    "opportunity_score": 70,
                    "suppressed": False,
                    "guard_evidence_recent": False,
                    "automatic_execution": False,
                },
            },
            subject_type="chat",
            subject_id=canonical_entity_id("chat", chat_id),
        )

    def _proposals(self, root: Path, *, count: int = 8, confidence: float = 0.9) -> tuple[PlatformDB, list[dict]]:
        db = PlatformDB(root=root)
        db.init()
        for idx in range(count):
            self._seed_pair(db, str(1000 + idx), confidence=confidence)
        result = propose_canonical_reengagement_reviews(root=root)
        self.assertEqual(result["created"], count)
        return db, db.recommendations(limit=50, status="PROPOSED")

    def _complete_with_outcome(
        self,
        root: Path,
        row: dict,
        outcome_type: str,
        *,
        outcome_confidence: float = 1.0,
        value_score: float = 0,
    ) -> None:
        key = row["recommendation_key"]
        transition_canonical_review(key, "ACCEPTED", actor="test-operator", root=root)
        transition_canonical_review(key, "COMPLETED", actor="test-operator", root=root)
        record_canonical_review_outcome(
            key,
            outcome_type,
            confidence=outcome_confidence,
            value_score=value_score,
            actor="test-operator",
            root=root,
        )

    def test_missing_database_is_read_only_and_insufficient(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = canonical_review_calibration_report(root=root)
            self.assertEqual(report.status, "INSUFFICIENT_DATA")
            self.assertEqual(report.outcome_events, 0)
            self.assertEqual(report.known_binary_outcomes, 0)
            self.assertFalse((root / "state").exists())
            self.assertFalse(report.automatic_threshold_change)
            self.assertFalse(report.automatic_rule_change)
            self.assertFalse(report.automatic_execution)

    def test_fewer_than_eight_binary_outcomes_remains_insufficient(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _db, rows = self._proposals(root, count=5)
            for row in rows:
                self._complete_with_outcome(root, row, "POSITIVE")
            report = canonical_review_calibration_report(root=root)
            self.assertEqual(report.known_binary_outcomes, 5)
            self.assertEqual(report.status, "INSUFFICIENT_DATA")

    def test_high_confidence_positive_reviews_are_well_calibrated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _db, rows = self._proposals(root, count=8, confidence=0.9)
            for row in rows:
                self._complete_with_outcome(root, row, "POSITIVE", value_score=40)
            report = canonical_review_calibration_report(root=root)
            self.assertEqual(report.known_binary_outcomes, 8)
            self.assertEqual(report.positive_outcomes, 8)
            self.assertEqual(report.negative_outcomes, 0)
            self.assertEqual(report.status, "WELL_CALIBRATED")
            self.assertAlmostEqual(report.average_recommendation_confidence or 0.0, 0.9, places=4)
            self.assertAlmostEqual(report.brier_score or 0.0, 0.01, places=4)
            self.assertAlmostEqual(report.average_realized_value_score or 0.0, 40.0, places=2)

    def test_high_confidence_negative_reviews_require_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _db, rows = self._proposals(root, count=8, confidence=0.9)
            for row in rows:
                self._complete_with_outcome(root, row, "NEGATIVE", value_score=-20)
            report = canonical_review_calibration_report(root=root)
            self.assertEqual(report.known_binary_outcomes, 8)
            self.assertEqual(report.negative_outcomes, 8)
            self.assertEqual(report.status, "REVIEW_REQUIRED")
            self.assertGreater(report.brier_score or 0.0, 0.25)

    def test_neutral_and_unknown_do_not_enter_binary_denominator(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _db, rows = self._proposals(root, count=8)
            outcomes = ["POSITIVE", "NEGATIVE", "NEUTRAL", "UNKNOWN", "NEUTRAL", "UNKNOWN", "POSITIVE", "NEGATIVE"]
            for row, outcome in zip(rows, outcomes):
                self._complete_with_outcome(root, row, outcome)
            report = canonical_review_calibration_report(root=root)
            self.assertEqual(report.outcome_events, 8)
            self.assertEqual(report.known_binary_outcomes, 4)
            self.assertEqual(report.neutral_outcomes, 2)
            self.assertEqual(report.unknown_outcomes, 2)
            self.assertEqual(report.status, "INSUFFICIENT_DATA")

    def test_uses_original_recommendation_confidence_not_outcome_confidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _db, rows = self._proposals(root, count=8, confidence=0.85)
            for row in rows:
                self._complete_with_outcome(
                    root,
                    row,
                    "POSITIVE",
                    outcome_confidence=0.10,
                )
            report = canonical_review_calibration_report(root=root)
            self.assertAlmostEqual(report.average_recommendation_confidence or 0.0, 0.85, places=4)
            self.assertNotAlmostEqual(report.average_recommendation_confidence or 0.0, 0.10, places=4)
            self.assertFalse(report.automatic_threshold_change)
            self.assertFalse(report.automatic_rule_change)
            self.assertFalse(report.automatic_execution)


if __name__ == "__main__":
    unittest.main()
