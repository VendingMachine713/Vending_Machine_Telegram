from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from shared.vm_core.db import PlatformDB
from shared.vm_core.mission_control import mission_control


class CanonicalReviewCalibrationMissionControlTests(unittest.TestCase):
    def test_empty_review_calibration_is_visible_and_advisory_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            PlatformDB(root=root).init()
            control = mission_control(root)
            self.assertEqual(
                control["headline"]["canonical_review_calibration"],
                "INSUFFICIENT_DATA",
            )
            self.assertFalse(
                control["attention"]["canonical_review_calibration_review_required"]
            )
            calibration = control["canonical_review_calibration"]
            self.assertFalse(calibration["automatic_threshold_change"])
            self.assertFalse(calibration["automatic_rule_change"])
            self.assertFalse(calibration["automatic_execution"])
            self.assertFalse(control["automatic_acceptance"])
            self.assertFalse(control["automatic_execution"])
            self.assertFalse(control["external_action_authority"])


if __name__ == "__main__":
    unittest.main()
