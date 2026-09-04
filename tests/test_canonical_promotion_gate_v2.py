from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from shared.vm_core.canonical_outcomes import record_canonical_inference_outcome
from shared.vm_core.canonical_readiness import canonical_recommendation_readiness
from shared.vm_core.db import PlatformDB
from shared.vm_core.intelligence_trust import canonical_entity_id


class CanonicalPromotionGateV2Tests(unittest.TestCase):
    def _seed_pair(self, db: PlatformDB, chat_id: str, *, confidence: float = 0.8) -> int:
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

    def test_fresh_parity_evidence_can_remain_development_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            for idx in range(5):
                self._seed_pair(db, str(100 + idx))
            result = canonical_recommendation_readiness(root=root)
            self.assertTrue(result.ready_for_recommendation_development)
            self.assertEqual(result.evidence_health_status, "ACTIVE_SHADOW")
            self.assertEqual(result.calibration_status, "INSUFFICIENT_DATA")
            self.assertFalse(result.recommendation_execution_enabled)
            self.assertFalse(result.automatic_execution)

    def test_stale_evidence_holds_promotion_even_when_sample_and_parity_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            ids = [self._seed_pair(db, str(200 + idx)) for idx in range(5)]
            stale_time = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
            with db.connect() as con:
                con.executemany(
                    "UPDATE events SET created_at_utc=? WHERE id=?",
                    [(stale_time, event_id) for event_id in ids],
                )
            result = canonical_recommendation_readiness(root=root)
            self.assertFalse(result.ready_for_recommendation_development)
            self.assertIn("canonical_evidence_stale", result.reasons)
            self.assertEqual(result.evidence_health_status, "STALE")

    def test_sufficient_bad_calibration_holds_promotion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            inference_ids = [self._seed_pair(db, str(300 + idx), confidence=0.95) for idx in range(8)]
            for inference_id in inference_ids:
                record_canonical_inference_outcome(
                    inference_id,
                    "NEGATIVE",
                    confidence=1.0,
                    actor="test-operator",
                    root=root,
                )
            result = canonical_recommendation_readiness(root=root)
            self.assertFalse(result.ready_for_recommendation_development)
            self.assertEqual(result.calibration_known_outcomes, 8)
            self.assertEqual(result.calibration_status, "REVIEW_REQUIRED")
            self.assertIn("canonical_calibration_review_required", result.reasons)
            self.assertFalse(result.recommendation_execution_enabled)
            self.assertFalse(result.automatic_execution)


if __name__ == "__main__":
    unittest.main()
