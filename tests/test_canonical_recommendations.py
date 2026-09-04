from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from shared.vm_core.canonical_recommendations import (
    canonical_recommendation_summary,
    propose_canonical_reengagement_reviews,
)
from shared.vm_core.db import PlatformDB
from shared.vm_core.intelligence_trust import canonical_entity_id
from shared.vm_core.mission_control import mission_control


class CanonicalRecommendationTests(unittest.TestCase):
    def _seed_pair(
        self,
        db: PlatformDB,
        chat_id: str,
        *,
        score: float = 70.0,
        suppressed: bool = False,
        confidence: float = 0.8,
    ) -> int:
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
        return db.add_event(
            "intelligence.inference.relationship_reengagement_opportunity",
            "vm_core",
            {
                "confidence": confidence,
                "rationale": "Canonical re-engagement evidence",
                "attributes": {
                    "support_signature": f"support-{chat_id}",
                    "opportunity_score": score,
                    "suppressed": suppressed,
                    "guard_evidence_recent": suppressed,
                    "guard_risk_score": 80 if suppressed else 0,
                    "recommendation_created": False,
                    "automatic_execution": False,
                },
            },
            subject_type="chat",
            subject_id=canonical_id,
        )

    def test_not_ready_does_not_create_recommendations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            self._seed_pair(db, "100")
            result = propose_canonical_reengagement_reviews(root=root)
            self.assertEqual(result["created"], 0)
            self.assertEqual(result["skipped_not_ready"], 1)
            self.assertEqual(db.recommendations(), [])
            self.assertFalse(result["automatic_execution"])
            self.assertFalse(result["external_action_authority"])

    def test_ready_canonical_inferences_create_review_only_proposals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            for idx in range(5):
                self._seed_pair(db, str(200 + idx))
            result = propose_canonical_reengagement_reviews(root=root)
            self.assertEqual(result["created"], 5)
            rows = db.recommendations(limit=20)
            self.assertEqual(len(rows), 5)
            for row in rows:
                self.assertEqual(row["status"], "PROPOSED")
                self.assertEqual(row["recommendation_type"], "canonical_relationship_reengagement_review")
                self.assertTrue(str(row["action"]).startswith("Review "))
                self.assertNotIn("send", str(row["action"]).lower())
            summary = canonical_recommendation_summary(root=root)
            self.assertEqual(summary["counts"]["PROPOSED"], 5)
            self.assertFalse(summary["automatic_acceptance"])
            self.assertFalse(summary["automatic_execution"])
            self.assertFalse(summary["external_action_authority"])
            control = mission_control(root)
            self.assertEqual(control["headline"]["canonical_review_recommendations"], 5)
            self.assertEqual(len(control["attention"]["canonical_review_recommendations"]), 5)
            self.assertFalse(control["automatic_acceptance"])
            self.assertFalse(control["automatic_execution"])
            self.assertFalse(control["external_action_authority"])

    def test_suppressed_inference_is_never_proposed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            for idx in range(5):
                self._seed_pair(db, str(300 + idx), suppressed=idx == 0)
            result = propose_canonical_reengagement_reviews(root=root)
            self.assertEqual(result["skipped_suppressed"], 1)
            self.assertEqual(result["created"], 4)
            self.assertEqual(len(db.recommendations(limit=20)), 4)

    def test_below_threshold_inference_is_not_proposed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            for idx in range(5):
                self._seed_pair(db, str(400 + idx), score=50 if idx == 0 else 70)
            result = propose_canonical_reengagement_reviews(root=root, minimum_opportunity_score=60)
            self.assertEqual(result["skipped_low_score"], 1)
            self.assertEqual(result["created"], 4)

    def test_same_supporting_evidence_refreshes_without_duplicate_proposal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            for idx in range(5):
                self._seed_pair(db, str(500 + idx))
            first = propose_canonical_reengagement_reviews(root=root)
            second = propose_canonical_reengagement_reviews(root=root)
            self.assertEqual(first["created"], 5)
            self.assertEqual(second["created"], 0)
            self.assertEqual(second["refreshed"], 5)
            self.assertEqual(len(db.recommendations(limit=20)), 5)
            proposal_events = db.events(limit=50, event_type="recommendation.proposed")
            self.assertEqual(len(proposal_events), 5)


if __name__ == "__main__":
    unittest.main()
