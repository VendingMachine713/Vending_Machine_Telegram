from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from shared.vm_core.prediction_intelligence import prediction_summary


class PredictionIntelligenceTests(unittest.TestCase):
    def _opportunity(self, subject: str, *, score: float = 70, confidence: float = 0.8) -> dict:
        return {
            "canonical_subject_id": subject,
            "opportunity_type": "REENGAGEMENT_ACTIVITY_REVIEW",
            "opportunity_score": 80.0,
            "risk_adjusted_score": score,
            "risk_score": 20.0,
            "risk_level": "LOW",
            "confidence": confidence,
            "risk_review_required": False,
        }

    def test_uses_transparent_heuristic_when_outcomes_are_insufficient(self) -> None:
        subject = "telegram:chat:aaaaaaaaaaaaaaaaaaaaaaaa"
        with TemporaryDirectory() as tmp, patch(
            "shared.vm_core.prediction_intelligence.risk_adjusted_canonical_opportunities",
            return_value=[self._opportunity(subject)],
        ), patch(
            "shared.vm_core.prediction_intelligence.canonical_review_calibration_summary",
            return_value={"status": "INSUFFICIENT_DATA", "known_binary_outcomes": 2, "positive_rate": 1.0},
        ):
            summary = prediction_summary(root=Path(tmp))

        self.assertEqual(summary["status"], "OK")
        row = summary["predictions"][0]
        self.assertEqual(row["canonical_subject_id"], subject)
        self.assertEqual(row["method"], "HEURISTIC_BASELINE")
        self.assertFalse(row["empirical_base_rate_used"])
        self.assertFalse(row["trained_model"])
        self.assertLessEqual(row["lower_bound"], row["probability"])
        self.assertGreaterEqual(row["upper_bound"], row["probability"])

    def test_verified_outcome_base_rate_is_used_only_after_minimum_sample(self) -> None:
        subject = "telegram:chat:bbbbbbbbbbbbbbbbbbbbbbbb"
        with TemporaryDirectory() as tmp, patch(
            "shared.vm_core.prediction_intelligence.risk_adjusted_canonical_opportunities",
            return_value=[self._opportunity(subject, score=60, confidence=0.9)],
        ), patch(
            "shared.vm_core.prediction_intelligence.canonical_review_calibration_summary",
            return_value={"status": "ACCEPTABLE", "known_binary_outcomes": 8, "positive_rate": 0.75},
        ):
            summary = prediction_summary(root=Path(tmp))

        row = summary["predictions"][0]
        self.assertTrue(summary["empirical_base_rate_used"])
        self.assertTrue(row["empirical_base_rate_used"])
        self.assertEqual(row["method"], "HEURISTIC_PLUS_VERIFIED_OUTCOME_BASE_RATE")
        self.assertEqual(row["verified_outcome_count"], 8)

    def test_lower_confidence_produces_wider_interval(self) -> None:
        rows = [
            self._opportunity("telegram:chat:cccccccccccccccccccccccc", confidence=0.95),
            self._opportunity("telegram:chat:dddddddddddddddddddddddd", confidence=0.2),
        ]
        with TemporaryDirectory() as tmp, patch(
            "shared.vm_core.prediction_intelligence.risk_adjusted_canonical_opportunities",
            return_value=rows,
        ), patch(
            "shared.vm_core.prediction_intelligence.canonical_review_calibration_summary",
            return_value={"status": "INSUFFICIENT_DATA", "known_binary_outcomes": 0, "positive_rate": None},
        ):
            predictions = prediction_summary(root=Path(tmp))["predictions"]

        by_subject = {row["canonical_subject_id"]: row for row in predictions}
        high = by_subject["telegram:chat:cccccccccccccccccccccccc"]
        low = by_subject["telegram:chat:dddddddddddddddddddddddd"]
        self.assertLess(
            high["upper_bound"] - high["lower_bound"],
            low["upper_bound"] - low["lower_bound"],
        )

    def test_risk_adjusted_score_drives_forecast_not_raw_opportunity_score(self) -> None:
        high = self._opportunity("telegram:chat:eeeeeeeeeeeeeeeeeeeeeeee", score=80)
        low = self._opportunity("telegram:chat:ffffffffffffffffffffffff", score=20)
        high["opportunity_score"] = 50
        low["opportunity_score"] = 100
        with TemporaryDirectory() as tmp, patch(
            "shared.vm_core.prediction_intelligence.risk_adjusted_canonical_opportunities",
            return_value=[low, high],
        ), patch(
            "shared.vm_core.prediction_intelligence.canonical_review_calibration_summary",
            return_value={"status": "INSUFFICIENT_DATA", "known_binary_outcomes": 0, "positive_rate": None},
        ):
            predictions = prediction_summary(root=Path(tmp))["predictions"]

        self.assertEqual(predictions[0]["canonical_subject_id"], high["canonical_subject_id"])
        self.assertGreater(predictions[0]["probability"], predictions[1]["probability"])

    def test_no_evidence_and_no_authority_fail_safely(self) -> None:
        with TemporaryDirectory() as tmp, patch(
            "shared.vm_core.prediction_intelligence.risk_adjusted_canonical_opportunities",
            return_value=[],
        ), patch(
            "shared.vm_core.prediction_intelligence.canonical_review_calibration_summary",
            return_value={"status": "INSUFFICIENT_DATA", "known_binary_outcomes": 0, "positive_rate": None},
        ):
            summary = prediction_summary(root=Path(tmp))

        self.assertEqual(summary["status"], "NO_EVIDENCE")
        self.assertEqual(summary["predictions"], [])
        self.assertTrue(summary["read_only"])
        self.assertFalse(summary["trained_model"])
        self.assertFalse(summary["automatic_acceptance"])
        self.assertFalse(summary["automatic_execution"])
        self.assertFalse(summary["automatic_threshold_change"])
        self.assertFalse(summary["automatic_rule_change"])
        self.assertFalse(summary["external_action_authority"])


if __name__ == "__main__":
    unittest.main()
