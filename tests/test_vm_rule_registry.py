from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from shared.vm_core.db import PlatformDB
from shared.vm_core.learning import record_outcome
from shared.vm_core.rule_registry import (
    RuleRegistryError,
    activate_proposal,
    active_rule_versions,
    decide_proposal,
    effective_score_delta,
    proposals,
    registry_summary,
    rollback_proposal,
    sync_calibration_proposals,
)


class VMRuleRegistryTests(unittest.TestCase):
    def _root(self, tmp: str) -> Path:
        root = Path(tmp)
        (root / "state").mkdir(parents=True, exist_ok=True)
        return root

    def _completed_outcome(self, root: Path, index: int, outcome: str = "NEGATIVE") -> None:
        db = PlatformDB(root=root)
        db.init()
        key = f"recommendation:rule-test:{index}"
        db.upsert_recommendation(
            key,
            "relationship_review",
            "Review evidence.",
            "Synthetic governed-registry test recommendation.",
            rule_id="test_rule",
            rule_version=1,
            subject_type="chat",
            subject_id=str(index),
            priority=80,
            confidence=0.9,
            status="COMPLETED",
            evidence={"automatic_execution": False},
        )
        record_outcome(
            key,
            outcome,
            value_score=-50 if outcome == "NEGATIVE" else 50,
            confidence=1.0,
            actor="test",
            root=root,
        )

    def test_weak_calibration_becomes_governed_proposal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            for index in range(8):
                self._completed_outcome(root, index)

            result = sync_calibration_proposals(root)
            self.assertEqual(result["created"], 1)
            rows = proposals(root)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["calibration_status"], "WEAK")
            self.assertEqual(rows[0]["status"], "PROPOSED")
            self.assertLess(float(rows[0]["proposed_score_delta"]), 0)

    def test_approval_activation_and_rollback_are_separate_governed_steps(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            for index in range(8):
                self._completed_outcome(root, index)
            sync_calibration_proposals(root)
            proposal = proposals(root)[0]
            proposal_id = int(proposal["id"])

            decision = decide_proposal(proposal_id, "APPROVED", actor="admin", root=root)
            self.assertEqual(decision.proposal_status, "APPROVED")
            self.assertEqual(proposals(root)[0]["status"], "APPROVED")
            self.assertEqual(effective_score_delta("test_rule", 1, "123", root), 0.0)

            activated = activate_proposal(
                proposal_id,
                actor="admin",
                rollout_percent=100,
                root=root,
            )
            self.assertEqual(activated.proposal_status, "ACTIVATED")
            active = active_rule_versions(root)
            self.assertEqual(len(active), 1)
            self.assertEqual(active[0]["rollout_percent"], 100)
            self.assertEqual(effective_score_delta("test_rule", 1, "123", root), -7.5)

            rolled = rollback_proposal(proposal_id, actor="admin", root=root)
            self.assertEqual(rolled.proposal_status, "ROLLED_BACK")
            self.assertEqual(active_rule_versions(root), [])
            self.assertEqual(effective_score_delta("test_rule", 1, "123", root), 0.0)

            db = PlatformDB(root=root)
            event_types = [row["event_type"] for row in db.events(20)]
            self.assertIn("rule_change.approved", event_types)
            self.assertIn("rule_change.activated", event_types)
            self.assertIn("rule_change.rolled_back", event_types)

    def test_rejected_proposal_cannot_activate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            for index in range(8):
                self._completed_outcome(root, index)
            sync_calibration_proposals(root)
            proposal_id = int(proposals(root)[0]["id"])
            decide_proposal(proposal_id, "REJECTED", actor="admin", root=root)
            with self.assertRaises(RuleRegistryError):
                activate_proposal(proposal_id, actor="admin", root=root)

    def test_registry_summary_never_claims_automatic_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            summary = registry_summary(root)
            self.assertFalse(summary["automatic_approval"])
            self.assertFalse(summary["automatic_activation"])
            self.assertFalse(summary["automatic_execution"])


if __name__ == "__main__":
    unittest.main()
