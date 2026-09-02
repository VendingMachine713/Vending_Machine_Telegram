from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from shared.vm_core.db import PlatformDB
from shared.vm_core.governance import (
    RecommendationGovernanceError,
    governance_summary,
    recommendation_history,
    transition_recommendation,
)


class VMIntelligenceGovernanceTests(unittest.TestCase):
    def _root(self, tmp: str) -> Path:
        root = Path(tmp)
        (root / "state").mkdir(parents=True, exist_ok=True)
        return root

    def _recommendation(
        self,
        root: Path,
        *,
        key: str = "recommendation:test:123",
        status: str = "PROPOSED",
    ) -> PlatformDB:
        db = PlatformDB(root=root)
        db.init()
        db.upsert_recommendation(
            key,
            "relationship_review",
            "Review evidence and prepare a human-approved plan.",
            "Test recommendation.",
            rule_id="test_rule",
            rule_version=1,
            subject_type="chat",
            subject_id="123",
            priority=80,
            confidence=0.9,
            status=status,
            evidence={"automatic_execution": False},
        )
        return db

    def test_accept_then_complete_creates_audit_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            db = self._recommendation(root)

            accepted = transition_recommendation(
                "recommendation:test:123",
                "ACCEPTED",
                actor="admin",
                note="Evidence reviewed.",
                root=root,
            )
            self.assertEqual(accepted.previous_status, "PROPOSED")
            self.assertEqual(accepted.status, "ACCEPTED")

            completed = transition_recommendation(
                "recommendation:test:123",
                "COMPLETED",
                actor="admin",
                root=root,
            )
            self.assertEqual(completed.previous_status, "ACCEPTED")
            self.assertEqual(completed.status, "COMPLETED")

            row = db.recommendations(1)[0]
            self.assertEqual(row["status"], "COMPLETED")

            history = recommendation_history("recommendation:test:123", root=root)
            self.assertEqual([event["event_type"] for event in history], [
                "recommendation.completed",
                "recommendation.accepted",
            ])
            accepted_payload = json.loads(history[1]["payload_json"])
            self.assertEqual(accepted_payload["actor"], "admin")
            self.assertFalse(accepted_payload["automatic_execution"])

    def test_blocked_recommendation_cannot_be_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            db = self._recommendation(root, status="BLOCKED")

            with self.assertRaises(RecommendationGovernanceError):
                transition_recommendation(
                    "recommendation:test:123",
                    "ACCEPTED",
                    actor="admin",
                    root=root,
                )

            self.assertEqual(db.recommendations(1)[0]["status"], "BLOCKED")
            self.assertEqual(recommendation_history("recommendation:test:123", root=root), [])

    def test_terminal_recommendations_cannot_be_reopened(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            self._recommendation(root, status="DISMISSED")

            with self.assertRaises(RecommendationGovernanceError):
                transition_recommendation(
                    "recommendation:test:123",
                    "ACCEPTED",
                    actor="admin",
                    root=root,
                )

    def test_governance_summary_is_passive_and_reports_actionable_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            db = self._recommendation(root)
            db.upsert_recommendation(
                "recommendation:blocked:456",
                "guard_review",
                "Review guard evidence.",
                "Elevated risk.",
                rule_id="guard_test",
                subject_type="chat",
                subject_id="456",
                priority=95,
                confidence=0.95,
                status="BLOCKED",
                evidence={"automatic_execution": False},
            )

            summary = governance_summary(root)
            self.assertEqual(summary["counts"]["PROPOSED"], 1)
            self.assertEqual(summary["counts"]["BLOCKED"], 1)
            self.assertEqual(len(summary["actionable"]), 1)
            self.assertFalse(summary["automatic_execution"])


if __name__ == "__main__":
    unittest.main()
