from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from shared.vm_core.canonical_recommendation_lifecycle import expire_canonical_review_proposals
from shared.vm_core.canonical_recommendations import propose_canonical_reengagement_reviews
from shared.vm_core.db import PlatformDB
from shared.vm_core.governance import RecommendationGovernanceError, transition_recommendation
from shared.vm_core.intelligence_trust import canonical_entity_id


class CanonicalRecommendationLifecycleTests(unittest.TestCase):
    def _seed_pair(self, db: PlatformDB, chat_id: str, *, score: float = 70.0) -> int:
        db.upsert_signal(
            f"cross:relationship_activity:{chat_id}",
            "relationship_activity_opportunity",
            "Legacy opportunity",
            subject_type="chat",
            subject_id=chat_id,
            score=score,
            confidence=0.9,
            evidence={"suppressed": False},
        )
        return db.add_event(
            "intelligence.inference.relationship_reengagement_opportunity",
            "vm_core",
            {
                "confidence": 0.8,
                "rationale": "Canonical re-engagement evidence",
                "attributes": {
                    "support_signature": f"support-{chat_id}",
                    "opportunity_score": score,
                    "suppressed": False,
                    "guard_evidence_recent": False,
                    "guard_risk_score": 0,
                    "recommendation_created": False,
                    "automatic_execution": False,
                },
            },
            subject_type="chat",
            subject_id=canonical_entity_id("chat", chat_id),
        )

    def _ready_root(self, root: Path) -> PlatformDB:
        db = PlatformDB(root=root)
        db.init()
        for idx in range(5):
            self._seed_pair(db, str(100 + idx))
        result = propose_canonical_reengagement_reviews(root=root)
        self.assertEqual(result["created"], 5)
        return db

    def test_stale_proposals_expire_with_audit_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = self._ready_root(root)
            stale_time = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
            with db.connect() as con:
                con.execute(
                    "UPDATE events SET created_at_utc=? WHERE event_type=?",
                    (stale_time, "intelligence.inference.relationship_reengagement_opportunity"),
                )
            result = expire_canonical_review_proposals(root=root, stale_after_hours=72)
            self.assertEqual(result["expired"], 5)
            self.assertEqual(result["reasons"]["stale_canonical_inference"], 5)
            self.assertEqual(len(db.recommendations(limit=20, status="EXPIRED")), 5)
            self.assertEqual(len(db.events(limit=20, event_type="recommendation.expired")), 5)
            self.assertFalse(result["automatic_execution"])

    def test_newer_support_signature_supersedes_old_proposal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = self._ready_root(root)
            subject = canonical_entity_id("chat", "100")
            db.add_event(
                "intelligence.inference.relationship_reengagement_opportunity",
                "vm_core",
                {
                    "confidence": 0.85,
                    "rationale": "Updated canonical evidence",
                    "attributes": {
                        "support_signature": "support-100-v2",
                        "opportunity_score": 80,
                        "suppressed": False,
                        "guard_evidence_recent": False,
                        "automatic_execution": False,
                    },
                },
                subject_type="chat",
                subject_id=subject,
            )
            result = expire_canonical_review_proposals(root=root)
            self.assertEqual(result["expired"], 1)
            self.assertEqual(result["kept"], 4)
            self.assertEqual(result["reasons"]["superseded_canonical_inference"], 1)

    def test_latest_suppressed_inference_expires_previous_proposal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = self._ready_root(root)
            subject = canonical_entity_id("chat", "100")
            db.add_event(
                "intelligence.inference.relationship_reengagement_opportunity",
                "vm_core",
                {
                    "confidence": 0.8,
                    "rationale": "Risk changed",
                    "attributes": {
                        "support_signature": "support-100",
                        "opportunity_score": 40,
                        "suppressed": True,
                        "guard_evidence_recent": True,
                        "guard_risk_score": 80,
                        "automatic_execution": False,
                    },
                },
                subject_type="chat",
                subject_id=subject,
            )
            result = expire_canonical_review_proposals(root=root)
            self.assertEqual(result["expired"], 1)
            self.assertEqual(result["reasons"]["latest_inference_suppressed"], 1)

    def test_accepted_recommendation_is_never_auto_expired(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = self._ready_root(root)
            accepted = db.recommendations(limit=20, status="PROPOSED")[0]
            transition_recommendation(
                accepted["recommendation_key"],
                "ACCEPTED",
                actor="test-operator",
                root=root,
            )
            stale_time = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
            with db.connect() as con:
                con.execute(
                    "UPDATE events SET created_at_utc=? WHERE event_type=?",
                    (stale_time, "intelligence.inference.relationship_reengagement_opportunity"),
                )
            result = expire_canonical_review_proposals(root=root)
            self.assertEqual(result["expired"], 4)
            row = next(
                item
                for item in db.recommendations(limit=20)
                if item["recommendation_key"] == accepted["recommendation_key"]
            )
            self.assertEqual(row["status"], "ACCEPTED")
            self.assertEqual(result["accepted_touched"], 0)

    def test_accepted_to_expired_remains_forbidden_by_governance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = self._ready_root(root)
            row = db.recommendations(limit=20, status="PROPOSED")[0]
            transition_recommendation(row["recommendation_key"], "ACCEPTED", root=root)
            with self.assertRaises(RecommendationGovernanceError):
                transition_recommendation(row["recommendation_key"], "EXPIRED", root=root)


if __name__ == "__main__":
    unittest.main()
