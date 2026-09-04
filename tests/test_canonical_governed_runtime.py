from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from shared.vm_core.canonical_runtime import (
    run_canonical_brain_pass,
    run_governed_canonical_brain_pass,
)
from shared.vm_core.db import PlatformDB


class CanonicalGovernedRuntimeTests(unittest.TestCase):
    def _seed_legacy_pair(self, db: PlatformDB, chat_id: str) -> None:
        relationship_score = 75.0
        activity_score = 85.0
        expected_opportunity_score = (activity_score * 0.55) + (relationship_score * 0.45)
        db.upsert_signal(
            f"relationship:presence:{chat_id}",
            "relationship_dormant_presence",
            "Dormant relationship present",
            subject_type="chat",
            subject_id=chat_id,
            score=relationship_score,
            confidence=0.95,
            evidence={
                "lifecycle_stage": "dormant",
                "relationship_score": 25,
            },
        )
        db.upsert_signal(
            f"search:activity_spike:{chat_id}",
            "search_activity_spike",
            "Activity above baseline",
            subject_type="chat",
            subject_id=chat_id,
            score=activity_score,
            confidence=0.90,
            evidence={"ratio": 4.2, "window_hours": 24, "baseline_days": 7},
        )
        # The shadow gate intentionally compares canonical inference with the
        # established legacy opportunity projection. Seed that baseline explicitly
        # so this runtime test exercises orchestration rather than bypassing parity.
        db.upsert_signal(
            f"cross:relationship_activity:{chat_id}",
            "relationship_activity_opportunity",
            "Legacy relationship/activity opportunity",
            subject_type="chat",
            subject_id=chat_id,
            score=expected_opportunity_score,
            confidence=0.90,
            evidence={"suppressed": False},
        )

    def test_shadow_pass_preserves_no_recommendation_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            for idx in range(5):
                self._seed_legacy_pair(db, str(100 + idx))
            result = run_canonical_brain_pass(root=root)
            self.assertEqual(result["mode"], "shadow")
            self.assertEqual(result["recommendations_created"], 0)
            self.assertEqual(db.recommendations(20), [])
            self.assertFalse(result["automatic_acceptance"])
            self.assertFalse(result["automatic_execution"])
            self.assertFalse(result["external_action_authority"])

    def test_governed_pass_creates_review_metadata_only_when_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            for idx in range(5):
                self._seed_legacy_pair(db, str(200 + idx))
            result = run_governed_canonical_brain_pass(root=root)
            self.assertEqual(result["mode"], "governed_review")
            self.assertEqual(result["recommendations_created"], 5)
            self.assertEqual(len(db.recommendations(20, status="PROPOSED")), 5)
            self.assertFalse(result["automatic_acceptance"])
            self.assertFalse(result["automatic_execution"])
            self.assertFalse(result["external_action_authority"])

    def test_governed_pass_is_idempotent_for_unchanged_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            for idx in range(5):
                self._seed_legacy_pair(db, str(300 + idx))
            first = run_governed_canonical_brain_pass(root=root)
            second = run_governed_canonical_brain_pass(root=root)
            self.assertEqual(first["recommendations_created"], 5)
            self.assertEqual(second["recommendations_created"], 0)
            self.assertEqual(second["recommendations_refreshed"], 5)
            self.assertEqual(second["recommendations_expired"], 0)
            self.assertEqual(len(db.recommendations(20)), 5)

    def test_not_ready_governed_pass_remains_review_silent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            self._seed_legacy_pair(db, "400")
            result = run_governed_canonical_brain_pass(root=root)
            self.assertEqual(result["recommendations_created"], 0)
            self.assertEqual(result["proposals"]["skipped_not_ready"], 1)
            self.assertEqual(db.recommendations(20), [])


if __name__ == "__main__":
    unittest.main()
