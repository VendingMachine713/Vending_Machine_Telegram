from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from shared.vm_core.canonical_calibration import canonical_calibration_report
from shared.vm_core.canonical_outcomes import CanonicalOutcomeError, record_canonical_inference_outcome
from shared.vm_core.db import PlatformDB
from shared.vm_core.intelligence_trust import canonical_entity_id
from shared.vm_core.mission_control import mission_control


class CanonicalInferenceCalibrationTests(unittest.TestCase):
    def _seed_inference(self, db: PlatformDB, chat_id: str, confidence: float) -> int:
        return db.add_event(
            "intelligence.inference.relationship_reengagement_opportunity",
            "vm_core",
            {
                "confidence": confidence,
                "attributes": {
                    "opportunity_score": 70,
                    "suppressed": False,
                    "recommendation_created": False,
                    "automatic_execution": False,
                },
            },
            subject_type="chat",
            subject_id=canonical_entity_id("chat", chat_id),
        )

    def test_calibration_missing_database_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = canonical_calibration_report(root=root)
            self.assertEqual(report.status, "INSUFFICIENT_DATA")
            self.assertEqual(report.known_binary_outcomes, 0)
            self.assertFalse(report.automatic_rule_change)
            self.assertFalse(report.automatic_execution)
            self.assertFalse((root / "state").exists())

    def test_verified_outcome_is_provenance_linked_and_unique(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            inference_id = self._seed_inference(db, "100", 0.8)
            outcome_id = record_canonical_inference_outcome(
                inference_id,
                "positive",
                value_score=50,
                confidence=1.0,
                actor="test-operator",
                root=root,
            )
            self.assertGreater(outcome_id, inference_id)
            with self.assertRaises(CanonicalOutcomeError):
                record_canonical_inference_outcome(inference_id, "positive", root=root)

    def test_known_outcomes_produce_calibration_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            for idx in range(8):
                positive = idx < 6
                inference_id = self._seed_inference(db, str(200 + idx), 0.75)
                record_canonical_inference_outcome(
                    inference_id,
                    "POSITIVE" if positive else "NEGATIVE",
                    confidence=1.0,
                    actor="test-operator",
                    root=root,
                )
            report = canonical_calibration_report(root=root)
            self.assertEqual(report.known_binary_outcomes, 8)
            self.assertEqual(report.positive_outcomes, 6)
            self.assertEqual(report.negative_outcomes, 2)
            self.assertAlmostEqual(report.positive_rate or 0.0, 0.75)
            self.assertAlmostEqual(report.average_predicted_confidence or 0.0, 0.75)
            self.assertAlmostEqual(report.calibration_gap or 0.0, 0.0)
            self.assertEqual(report.status, "ACCEPTABLE")
            self.assertFalse(report.automatic_rule_change)
            self.assertFalse(report.automatic_execution)

    def test_badly_miscalibrated_outcomes_require_review_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            for idx in range(8):
                inference_id = self._seed_inference(db, str(300 + idx), 0.95)
                record_canonical_inference_outcome(
                    inference_id,
                    "NEGATIVE",
                    confidence=1.0,
                    actor="test-operator",
                    root=root,
                )
            report = canonical_calibration_report(root=root)
            self.assertEqual(report.status, "REVIEW_REQUIRED")
            self.assertGreater(report.brier_score or 0.0, 0.25)
            summary = mission_control(root)
            self.assertEqual(summary["headline"]["canonical_calibration"], "REVIEW_REQUIRED")
            self.assertTrue(summary["attention"]["canonical_calibration_review_required"])
            self.assertFalse(summary["automatic_execution"])
            self.assertFalse(summary["external_action_authority"])


if __name__ == "__main__":
    unittest.main()
