from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from shared.vm_core.canonical_readiness import (
    ReadinessPolicy,
    canonical_operator_summary,
    canonical_recommendation_readiness,
)
from shared.vm_core.db import PlatformDB
from shared.vm_core.intelligence_trust import canonical_entity_id


class CanonicalReadinessTests(unittest.TestCase):
    def _seed_pair(self, db: PlatformDB, chat_id: str, *, score: float = 70, suppressed: bool = False) -> None:
        db.upsert_signal(
            f"cross:relationship_activity:{chat_id}",
            "relationship_activity_opportunity",
            "Legacy opportunity",
            subject_type="chat",
            subject_id=chat_id,
            score=score,
            confidence=0.9,
            evidence={"suppressed": suppressed},
        )
        canonical_id = canonical_entity_id("chat", chat_id)
        db.add_event(
            "intelligence.inference.relationship_reengagement_opportunity",
            "vm_core",
            {
                "confidence": 0.8,
                "attributes": {
                    "opportunity_score": score,
                    "suppressed": suppressed,
                    "automatic_execution": False,
                    "recommendation_created": False,
                },
            },
            subject_type="chat",
            subject_id=canonical_id,
        )

    def test_missing_database_fails_closed_without_creating_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = canonical_recommendation_readiness(root=root)
            self.assertFalse(result.ready_for_recommendation_development)
            self.assertEqual(result.status, "SHADOW_EVIDENCE_REQUIRED")
            self.assertIn("insufficient_shadow_samples", result.reasons)
            self.assertIn("legacy_canonical_parity_not_passed", result.reasons)
            self.assertFalse(result.recommendation_execution_enabled)
            self.assertFalse(result.automatic_execution)
            self.assertFalse((root / "state").exists())

    def test_matching_small_sample_still_requires_more_shadow_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            for idx in range(3):
                self._seed_pair(db, str(100 + idx))
            result = canonical_recommendation_readiness(root=root)
            self.assertFalse(result.ready_for_recommendation_development)
            self.assertEqual(result.parity_status, "PASS")
            self.assertEqual(result.canonical_inference_count, 3)
            self.assertEqual(result.reasons, ("insufficient_shadow_samples",))

    def test_matching_minimum_sample_can_unlock_development_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            for idx in range(5):
                self._seed_pair(db, str(200 + idx), suppressed=idx == 0)
            result = canonical_recommendation_readiness(root=root)
            self.assertTrue(result.ready_for_recommendation_development)
            self.assertEqual(result.status, "READY_FOR_GOVERNED_DEVELOPMENT")
            self.assertEqual(result.canonical_inference_count, 5)
            self.assertEqual(result.suppressed_inference_count, 1)
            self.assertFalse(result.recommendation_execution_enabled)
            self.assertFalse(result.automatic_execution)

    def test_suppressed_ratio_policy_can_hold_development_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            for idx in range(5):
                self._seed_pair(db, str(300 + idx), suppressed=idx < 3)
            result = canonical_recommendation_readiness(
                root=root,
                policy=ReadinessPolicy(minimum_canonical_inferences=5, maximum_suppressed_ratio=0.40),
            )
            self.assertFalse(result.ready_for_recommendation_development)
            self.assertIn("suppressed_ratio_exceeded", result.reasons)

    def test_operator_summary_never_claims_execution_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            for idx in range(5):
                self._seed_pair(db, str(400 + idx))
            summary = canonical_operator_summary(root=root)
            self.assertIn("canonical_readiness", summary)
            self.assertFalse(summary["recommendation_execution_enabled"])
            self.assertFalse(summary["automatic_execution"])
            encoded = json.dumps(summary)
            self.assertNotIn('"recommendation_execution_enabled": true', encoded)
            self.assertNotIn('"automatic_execution": true', encoded)


if __name__ == "__main__":
    unittest.main()
