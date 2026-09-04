from __future__ import annotations

from pathlib import Path
import sqlite3
import tempfile
import unittest

from shared.vm_core.canonical_recommendation_lifecycle import expire_canonical_review_proposals
from shared.vm_core.canonical_recommendations import propose_canonical_reengagement_reviews
from shared.vm_core.canonical_review_audit import canonical_review_audit_timeline
from shared.vm_core.canonical_review_feedback import (
    record_canonical_review_outcome,
    transition_canonical_review,
)
from shared.vm_core.db import PlatformDB
from shared.vm_core.intelligence_trust import canonical_entity_id
from shared.vm_core.mission_control import mission_control


class CanonicalReviewAuditTests(unittest.TestCase):
    def _seed(self, db: PlatformDB, native_id: str, *, signature: str | None = None) -> int:
        canonical = canonical_entity_id("chat", native_id)
        return db.add_event(
            "intelligence.inference.relationship_reengagement_opportunity",
            "vm_core",
            {
                "confidence": 0.8,
                "rationale": "Canonical evidence",
                "attributes": {
                    "support_signature": signature or f"support-{native_id}",
                    "opportunity_score": 75,
                    "suppressed": False,
                    "guard_evidence_recent": False,
                    "automatic_execution": False,
                },
            },
            subject_type="chat",
            subject_id=canonical,
        )

    def _ready(self, root: Path) -> tuple[PlatformDB, dict]:
        db = PlatformDB(root=root)
        db.init()
        for idx in range(5):
            self._seed(db, str(100 + idx))
        result = propose_canonical_reengagement_reviews(root=root)
        self.assertEqual(result["created"], 5)
        return db, db.recommendations(limit=20, status="PROPOSED")[0]

    def _timeline_for(self, root: Path, key: str) -> dict:
        result = canonical_review_audit_timeline(root=root, limit=50)
        return next(row for row in result["timelines"] if row["recommendation_key"] == key)

    def test_full_happy_path_inference_to_verified_outcome_and_calibration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _db, recommendation = self._ready(root)
            key = recommendation["recommendation_key"]
            transition_canonical_review(key, "ACCEPTED", actor="operator-a", root=root)
            transition_canonical_review(key, "COMPLETED", actor="operator-a", root=root)
            record_canonical_review_outcome(
                key, "POSITIVE", value_score=35, confidence=0.9, actor="operator-a", root=root
            )

            audit = canonical_review_audit_timeline(root=root, limit=50)
            timeline = self._timeline_for(root, key)
            stages = [event["stage"] for event in timeline["events"]]
            self.assertEqual(audit["status"], "OK")
            for expected in {"INFERENCE", "PROPOSAL", "DECISION", "COMPLETION", "OUTCOME", "CALIBRATION"}:
                self.assertIn(expected, stages)
            self.assertEqual(timeline["current_status"], "COMPLETED")
            self.assertTrue(timeline["canonical_subject_id"].startswith("telegram:chat:"))
            self.assertNotIn("100", timeline["canonical_subject_id"])
            self.assertTrue(audit["read_only"])
            self.assertFalse(audit["automatic_acceptance"])
            self.assertFalse(audit["automatic_execution"])
            self.assertFalse(audit["automatic_threshold_change"])
            self.assertFalse(audit["automatic_rule_change"])
            self.assertFalse(audit["external_action_authority"])

            control = mission_control(root=root, limit=20)
            self.assertEqual(control["headline"]["canonical_review_audit_status"], "OK")
            self.assertGreater(control["headline"]["canonical_review_audit_events"], 0)
            self.assertTrue(control["canonical_review_audit"]["recent_history"])

    def test_supersession_lineage_is_preserved_across_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db, _row = self._ready(root)
            subject = canonical_entity_id("chat", "100")
            original = next(
                row for row in db.recommendations(limit=20)
                if row["subject_id"] == subject
            )
            self._seed(db, "100", signature="support-100-v2")
            expired = expire_canonical_review_proposals(root=root)
            self.assertEqual(expired["expired"], 1)
            proposed = propose_canonical_reengagement_reviews(root=root)
            self.assertEqual(proposed["supersession_links"], 1)

            audit = canonical_review_audit_timeline(root=root, limit=50)
            replacement = next(
                row for row in audit["timelines"]
                if row["lineage"]["supersedes"] == original["recommendation_key"]
            )
            predecessor = next(
                row for row in audit["timelines"]
                if row["recommendation_key"] == original["recommendation_key"]
            )
            self.assertEqual(predecessor["lineage"]["superseded_by"], replacement["recommendation_key"])
            self.assertIn("SUPERSESSION", [event["stage"] for event in replacement["events"]])
            self.assertIn("EXPIRY", [event["stage"] for event in predecessor["events"]])

    def test_dismissed_and_expired_branches_are_visible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db, dismissed = self._ready(root)
            transition_canonical_review(dismissed["recommendation_key"], "DISMISSED", root=root)
            with db.connect() as con:
                other = con.execute(
                    "SELECT recommendation_key FROM intelligence_recommendations "
                    "WHERE status='PROPOSED' LIMIT 1"
                ).fetchone()[0]
            from shared.vm_core.governance import transition_recommendation
            transition_recommendation(other, "EXPIRED", actor="vm_core.canonical_lifecycle", root=root)
            audit = canonical_review_audit_timeline(root=root, limit=50)
            statuses = {row["current_status"] for row in audit["timelines"]}
            self.assertIn("DISMISSED", statuses)
            self.assertIn("EXPIRED", statuses)

    def test_missing_database_and_missing_tables_fail_closed_without_creating_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = PlatformDB(root=root).path
            result = canonical_review_audit_timeline(root=root)
            self.assertEqual(result["status"], "UNAVAILABLE")
            self.assertFalse(db_path.exists())

            db_path.parent.mkdir(parents=True, exist_ok=True)
            sqlite3.connect(db_path).close()
            result = canonical_review_audit_timeline(root=root)
            self.assertEqual(result["status"], "UNAVAILABLE")
            self.assertEqual(result["timelines"], [])

    def test_malformed_event_payload_and_evidence_are_safe_and_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db, recommendation = self._ready(root)
            with db.connect() as con:
                con.execute(
                    "UPDATE events SET payload_json='{bad', evidence_json='[bad' "
                    "WHERE correlation_id=? AND event_type='recommendation.proposed'",
                    (f"recommendation:{recommendation['id']}",),
                )
            audit = canonical_review_audit_timeline(root=root, limit=50)
            self.assertEqual(audit["status"], "PARTIAL")
            self.assertGreater(audit["malformed_rows"], 0)
            timeline = self._timeline_for(root, recommendation["recommendation_key"])
            proposed = next(event for event in timeline["events"] if event["stage"] == "PROPOSAL")
            self.assertFalse(proposed["data_valid"])

    def test_duplicate_events_are_collapsed_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db, recommendation = self._ready(root)
            correlation = f"recommendation:{recommendation['id']}"
            with db.connect() as con:
                row = con.execute(
                    "SELECT * FROM events WHERE correlation_id=? AND event_type='recommendation.proposed'",
                    (correlation,),
                ).fetchone()
                con.execute(
                    "INSERT INTO events(event_type,source,payload_json,created_at_utc,event_version,severity,"
                    "subject_type,subject_id,correlation_id,evidence_json) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    tuple(row[name] for name in (
                        "event_type", "source", "payload_json", "created_at_utc", "event_version", "severity",
                        "subject_type", "subject_id", "correlation_id", "evidence_json"
                    )),
                )
            audit = canonical_review_audit_timeline(root=root, limit=50)
            timeline = self._timeline_for(root, recommendation["recommendation_key"])
            self.assertEqual(sum(event["stage"] == "PROPOSAL" for event in timeline["events"]), 1)
            self.assertGreaterEqual(audit["duplicate_events_ignored"], 1)

    def test_audit_query_never_changes_governance_or_execution_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db, recommendation = self._ready(root)
            before = db.recommendations(limit=50)
            audit = canonical_review_audit_timeline(root=root, limit=50)
            after = db.recommendations(limit=50)
            self.assertEqual(before, after)
            self.assertEqual(recommendation["status"], "PROPOSED")
            for flag in (
                "automatic_acceptance", "automatic_execution", "automatic_threshold_change",
                "automatic_rule_change", "external_action_authority"
            ):
                self.assertFalse(audit[flag])


if __name__ == "__main__":
    unittest.main()
