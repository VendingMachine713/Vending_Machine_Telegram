from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from shared.vm_core.canonical_recommendations import propose_canonical_reengagement_reviews
from shared.vm_core.canonical_review_feedback import (
    CanonicalReviewFeedbackError,
    canonical_review_feedback_summary,
    record_canonical_review_outcome,
    transition_canonical_review,
)
from shared.vm_core.db import PlatformDB
from shared.vm_core.intelligence_trust import canonical_entity_id
from shared.vm_core.mission_control import mission_control


class CanonicalReviewFeedbackTests(unittest.TestCase):
    def _seed_pair(self, db: PlatformDB, chat_id: str) -> None:
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
        db.add_event(
            "intelligence.inference.relationship_reengagement_opportunity",
            "vm_core",
            {
                "confidence": 0.8,
                "rationale": "Canonical re-engagement evidence",
                "attributes": {
                    "support_signature": f"support-{chat_id}",
                    "opportunity_score": 70,
                    "suppressed": False,
                    "guard_evidence_recent": False,
                    "automatic_execution": False,
                },
            },
            subject_type="chat",
            subject_id=canonical_entity_id("chat", chat_id),
        )

    def _canonical_proposal(self, root: Path) -> tuple[PlatformDB, dict]:
        db = PlatformDB(root=root)
        db.init()
        for idx in range(5):
            self._seed_pair(db, str(100 + idx))
        result = propose_canonical_reengagement_reviews(root=root)
        self.assertEqual(result["created"], 5)
        return db, db.recommendations(limit=20, status="PROPOSED")[0]

    def test_canonical_operator_review_can_complete_and_record_one_outcome(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db, row = self._canonical_proposal(root)
            accepted = transition_canonical_review(
                row["recommendation_key"],
                "ACCEPTED",
                actor="test-operator",
                root=root,
            )
            self.assertEqual(accepted.status, "ACCEPTED")
            completed = transition_canonical_review(
                row["recommendation_key"],
                "COMPLETED",
                actor="test-operator",
                note="Operator completed review",
                root=root,
            )
            self.assertEqual(completed.status, "COMPLETED")
            outcome = record_canonical_review_outcome(
                row["recommendation_key"],
                "POSITIVE",
                value_score=40,
                confidence=0.9,
                actor="test-operator",
                note="Re-engagement proved useful",
                root=root,
            )
            self.assertGreater(outcome.outcome_id, 0)
            self.assertEqual(outcome.outcome_type, "POSITIVE")
            with db.connect() as con:
                stored = con.execute(
                    "SELECT * FROM intelligence_outcomes WHERE id=?",
                    (outcome.outcome_id,),
                ).fetchone()
            evidence = json.loads(stored["evidence_json"])
            self.assertTrue(evidence["canonical_review"])
            self.assertIsNotNone(evidence["canonical_inference_event_id"])
            self.assertTrue(evidence["support_signature"])
            summary = canonical_review_feedback_summary(root=root)
            self.assertEqual(summary["recorded_outcomes"], 1)
            self.assertEqual(summary["outcome_counts"]["POSITIVE"], 1)
            self.assertEqual(summary["completed_without_outcome"], 0)
            self.assertFalse(summary["automatic_completion"])
            self.assertFalse(summary["automatic_outcome_recording"])
            self.assertFalse(summary["automatic_rule_change"])
            self.assertFalse(summary["automatic_execution"])
            control = mission_control(root)
            self.assertEqual(control["headline"]["canonical_review_outcomes"], 1)
            self.assertEqual(control["headline"]["canonical_reviews_awaiting_outcome"], 0)
            self.assertFalse(control["automatic_acceptance"])
            self.assertFalse(control["automatic_execution"])
            self.assertFalse(control["external_action_authority"])

    def test_outcome_before_completion_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _db, row = self._canonical_proposal(root)
            with self.assertRaises(CanonicalReviewFeedbackError):
                record_canonical_review_outcome(
                    row["recommendation_key"],
                    "POSITIVE",
                    root=root,
                )

    def test_duplicate_canonical_outcome_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _db, row = self._canonical_proposal(root)
            transition_canonical_review(row["recommendation_key"], "ACCEPTED", root=root)
            transition_canonical_review(row["recommendation_key"], "COMPLETED", root=root)
            record_canonical_review_outcome(row["recommendation_key"], "NEUTRAL", root=root)
            with self.assertRaises(CanonicalReviewFeedbackError):
                record_canonical_review_outcome(row["recommendation_key"], "POSITIVE", root=root)

    def test_noncanonical_recommendation_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            db.upsert_recommendation(
                "legacy:test",
                "legacy_review",
                "Review legacy item",
                "Not a canonical review",
                rule_id="legacy.rule",
                rule_version=1,
                subject_type="chat",
                subject_id="legacy",
                status="PROPOSED",
            )
            with self.assertRaises(CanonicalReviewFeedbackError):
                transition_canonical_review("legacy:test", "ACCEPTED", root=root)

    def test_automatic_or_expiry_targets_are_not_exposed_as_operator_feedback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _db, row = self._canonical_proposal(root)
            with self.assertRaises(CanonicalReviewFeedbackError):
                transition_canonical_review(row["recommendation_key"], "EXPIRED", root=root)
            with self.assertRaises(CanonicalReviewFeedbackError):
                transition_canonical_review(row["recommendation_key"], "PROPOSED", root=root)


if __name__ == "__main__":
    unittest.main()
