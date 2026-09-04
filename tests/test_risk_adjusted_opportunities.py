from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from shared.vm_core.risk_fusion import risk_adjusted_canonical_opportunities


class RiskAdjustedOpportunityTests(unittest.TestCase):
    def test_high_risk_candidate_remains_visible_but_ranks_lower(self) -> None:
        opportunities = [
            {
                "canonical_subject_id": "telegram:chat:aaaaaaaaaaaaaaaaaaaaaaaa",
                "opportunity_score": 80.0,
                "confidence": 0.9,
                "diagnostic_candidate_only": True,
            },
            {
                "canonical_subject_id": "telegram:chat:bbbbbbbbbbbbbbbbbbbbbbbb",
                "opportunity_score": 70.0,
                "confidence": 0.8,
                "diagnostic_candidate_only": True,
            },
        ]
        risk = {
            "subjects": [
                {
                    "canonical_subject_id": "telegram:chat:aaaaaaaaaaaaaaaaaaaaaaaa",
                    "risk_score": 90.0,
                    "risk_level": "HIGH",
                    "risk_reasons": ["guard_risk"],
                    "review_required": True,
                }
            ]
        }
        with TemporaryDirectory() as tmp, patch(
            "shared.vm_core.opportunity_intelligence.canonical_opportunities",
            return_value=opportunities,
        ), patch(
            "shared.vm_core.risk_fusion.canonical_risk_fusion_summary",
            return_value=risk,
        ):
            rows = risk_adjusted_canonical_opportunities(root=Path(tmp))

        by_subject = {row["canonical_subject_id"]: row for row in rows}
        high = by_subject["telegram:chat:aaaaaaaaaaaaaaaaaaaaaaaa"]
        low = by_subject["telegram:chat:bbbbbbbbbbbbbbbbbbbbbbbb"]
        self.assertEqual(high["opportunity_score"], 80.0)
        self.assertLess(high["risk_adjusted_score"], low["risk_adjusted_score"])
        self.assertTrue(high["risk_review_required"])
        self.assertTrue(high["candidate_visible"])
        self.assertFalse(high["automatic_suppression"])
        self.assertEqual(low["risk_level"], "NONE")

    def test_risk_adjustment_never_creates_execution_authority(self) -> None:
        opportunity = {
            "canonical_subject_id": "telegram:chat:cccccccccccccccccccccccc",
            "opportunity_score": 50.0,
            "confidence": 0.5,
            "automatic_execution": False,
            "external_action_authority": False,
        }
        with TemporaryDirectory() as tmp, patch(
            "shared.vm_core.opportunity_intelligence.canonical_opportunities",
            return_value=[opportunity],
        ), patch(
            "shared.vm_core.risk_fusion.canonical_risk_fusion_summary",
            return_value={"subjects": []},
        ):
            row = risk_adjusted_canonical_opportunities(root=Path(tmp))[0]

        self.assertFalse(row["automatic_execution"])
        self.assertFalse(row["external_action_authority"])
        self.assertFalse(row["automatic_suppression"])
        self.assertTrue(row["candidate_visible"])


if __name__ == "__main__":
    unittest.main()
