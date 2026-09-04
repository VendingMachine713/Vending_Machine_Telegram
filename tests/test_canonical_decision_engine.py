from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from shared.vm_core.decision_engine import canonical_decisions, decision_summary


class CanonicalDecisionEngineTests(unittest.TestCase):
    def _prediction(
        self,
        subject: str,
        *,
        probability: float = 0.8,
        lower: float = 0.6,
        confidence: float = 0.9,
        risk: float = 10,
        risk_review: bool = False,
    ) -> dict:
        return {
            "canonical_subject_id": subject,
            "probability": probability,
            "lower_bound": lower,
            "upper_bound": min(1.0, probability + 0.1),
            "source_confidence": confidence,
            "risk_score": risk,
            "risk_level": "HIGH" if risk >= 75 else "LOW",
            "risk_review_required": risk_review,
            "method": "HEURISTIC_BASELINE",
            "source_opportunity_type": "REENGAGEMENT_ACTIVITY_REVIEW",
            "source_opportunity_score": 80,
            "risk_adjusted_score": 70,
            "empirical_base_rate_used": False,
        }

    def test_high_probability_candidate_is_prioritised_for_operator_review(self) -> None:
        subject = "telegram:chat:aaaaaaaaaaaaaaaaaaaaaaaa"
        with TemporaryDirectory() as tmp, patch(
            "shared.vm_core.decision_engine.prediction_summary",
            return_value={"predictions": [self._prediction(subject)]},
        ):
            row = canonical_decisions(Path(tmp))[0]
        self.assertEqual(row["disposition"], "PRIORITISE_OPERATOR_REVIEW")
        self.assertEqual(row["canonical_subject_id"], subject)
        self.assertTrue(row["requires_human_review"])
        self.assertTrue(row["decision_is_advisory"])
        self.assertFalse(row["recommendation_created"])

    def test_risk_review_is_explicit_and_candidate_remains_visible(self) -> None:
        subject = "telegram:chat:bbbbbbbbbbbbbbbbbbbbbbbb"
        prediction = self._prediction(subject, risk=90, risk_review=True)
        with TemporaryDirectory() as tmp, patch(
            "shared.vm_core.decision_engine.prediction_summary",
            return_value={"predictions": [prediction]},
        ):
            row = canonical_decisions(Path(tmp))[0]
        self.assertEqual(row["disposition"], "RISK_REVIEW_FIRST")
        self.assertIn("risk_review_required", row["reasons"])
        self.assertFalse(row["automatic_execution"])
        self.assertFalse(row["automatic_acceptance"])

    def test_medium_probability_is_review_when_available(self) -> None:
        subject = "telegram:chat:cccccccccccccccccccccccc"
        prediction = self._prediction(subject, probability=0.6, lower=0.4)
        with TemporaryDirectory() as tmp, patch(
            "shared.vm_core.decision_engine.prediction_summary",
            return_value={"predictions": [prediction]},
        ):
            row = canonical_decisions(Path(tmp))[0]
        self.assertEqual(row["disposition"], "REVIEW_WHEN_AVAILABLE")

    def test_low_expected_value_is_deferred_not_deleted(self) -> None:
        subject = "telegram:chat:dddddddddddddddddddddddd"
        prediction = self._prediction(subject, probability=0.4, lower=0.2)
        with TemporaryDirectory() as tmp, patch(
            "shared.vm_core.decision_engine.prediction_summary",
            return_value={"predictions": [prediction]},
        ):
            row = canonical_decisions(Path(tmp))[0]
        self.assertEqual(row["disposition"], "DEFER_LOW_EXPECTED_VALUE")
        self.assertEqual(row["canonical_subject_id"], subject)
        self.assertTrue(row["requires_human_review"])

    def test_risk_review_items_surface_before_normal_priority(self) -> None:
        risky = self._prediction(
            "telegram:chat:eeeeeeeeeeeeeeeeeeeeeeee",
            probability=0.9,
            lower=0.8,
            risk=90,
            risk_review=True,
        )
        normal = self._prediction(
            "telegram:chat:ffffffffffffffffffffffff",
            probability=0.95,
            lower=0.85,
            risk=0,
        )
        with TemporaryDirectory() as tmp, patch(
            "shared.vm_core.decision_engine.prediction_summary",
            return_value={"predictions": [normal, risky]},
        ):
            rows = canonical_decisions(Path(tmp))
        self.assertEqual(rows[0]["disposition"], "RISK_REVIEW_FIRST")

    def test_summary_preserves_legacy_fields_and_adds_canonical_surface(self) -> None:
        prediction = self._prediction("telegram:chat:111111111111111111111111")
        with TemporaryDirectory() as tmp, patch(
            "shared.vm_core.decision_engine.ranked_decisions",
            return_value=[],
        ), patch(
            "shared.vm_core.decision_engine.prediction_summary",
            return_value={"predictions": [prediction]},
        ):
            summary = decision_summary(Path(tmp))
        self.assertEqual(summary["decision_count"], 0)
        self.assertEqual(summary["top_decisions"], [])
        self.assertEqual(summary["canonical_decision_count"], 1)
        self.assertEqual(
            summary["canonical_disposition_counts"]["PRIORITISE_OPERATOR_REVIEW"], 1
        )
        self.assertFalse(summary["automatic_conflict_resolution"])
        self.assertFalse(summary["automatic_threshold_change"])
        self.assertFalse(summary["automatic_rule_change"])
        self.assertFalse(summary["external_action_authority"])

    def test_bad_limit_and_malformed_prediction_fail_safely(self) -> None:
        with TemporaryDirectory() as tmp, patch(
            "shared.vm_core.decision_engine.prediction_summary",
            return_value={"predictions": [{"canonical_subject_id": "telegram:chat:222222222222222222222222", "probability": "bad"}]},
        ):
            rows = canonical_decisions(Path(tmp), limit="bad")  # type: ignore[arg-type]
        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
