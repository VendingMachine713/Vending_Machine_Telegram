from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from shared.vm_core.mission_control import mission_control


class CanonicalMissionControlTests(unittest.TestCase):
    def test_mission_control_surfaces_canonical_readiness_without_authority(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            summary = mission_control(root)

            self.assertIn("canonical", summary)
            self.assertIn("canonical_readiness", summary["headline"])
            self.assertIn("canonical_shadow_samples", summary["headline"])
            self.assertIn("canonical_parity", summary["headline"])
            self.assertIn("canonical_readiness_reasons", summary["attention"])

            readiness = summary["canonical"]["canonical_readiness"]
            self.assertEqual(summary["headline"]["canonical_readiness"], readiness["status"])
            self.assertEqual(summary["headline"]["canonical_shadow_samples"], readiness["canonical_inference_count"])
            self.assertEqual(summary["headline"]["canonical_parity"], readiness["parity_status"])
            self.assertEqual(summary["attention"]["canonical_readiness_reasons"], list(readiness["reasons"]))

            self.assertFalse(summary["automatic_acceptance"])
            self.assertFalse(summary["automatic_execution"])
            self.assertFalse(summary["external_action_authority"])
            self.assertFalse(summary["canonical"]["recommendation_execution_enabled"])
            self.assertFalse(summary["canonical"]["automatic_execution"])

    def test_empty_shadow_state_is_visible_as_not_ready(self) -> None:
        with TemporaryDirectory() as td:
            summary = mission_control(Path(td))
            self.assertEqual(summary["headline"]["canonical_readiness"], "SHADOW_EVIDENCE_REQUIRED")
            self.assertEqual(summary["headline"]["canonical_shadow_samples"], 0)
            self.assertIn("insufficient_shadow_samples", summary["attention"]["canonical_readiness_reasons"])


if __name__ == "__main__":
    unittest.main()
