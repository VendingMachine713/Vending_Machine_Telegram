from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from shared.vm_core.db import PlatformDB
from shared.vm_core.intelligence_trust import canonical_entity_id
from shared.vm_core.relationship_intelligence import relationship_intelligence_summary


class RelationshipIntelligenceTests(unittest.TestCase):
    def _event(
        self,
        db: PlatformDB,
        signal: str,
        native_subject: str,
        *,
        confidence: float = 0.8,
        canonical: bool = True,
        attributes: dict | None = None,
    ) -> int:
        subject = (
            canonical_entity_id("chat", native_subject)
            if canonical
            else native_subject
        )
        return db.add_event(
            f"intelligence.signal.{signal}",
            "VM_Relationship_Manager",
            {
                "confidence": confidence,
                "attributes": dict(attributes or {}),
            },
            subject_type="chat",
            subject_id=subject,
        )

    def test_unifies_relationship_signals_into_one_canonical_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            self._event(
                db,
                "relationship_dormant_presence",
                "123456",
                attributes={
                    "relationship_type": "client",
                    "lifecycle_stage": "dormant",
                    "relationship_score": 32,
                    "trust_score": 74,
                    "days_overdue": 18,
                    "group_interactions": 9,
                },
            )
            self._event(
                db,
                "business_reload_opportunity",
                "123456",
                confidence=0.9,
                attributes={
                    "transaction_count": 4,
                    "days_since_last_business": 21,
                },
            )

            summary = relationship_intelligence_summary(root=root)
            self.assertEqual(summary["status"], "OK")
            self.assertEqual(summary["profile_count"], 1)
            profile = summary["profiles"][0]
            self.assertEqual(profile["relationship_state"], "DORMANT")
            self.assertEqual(profile["relationship_type"], "client")
            self.assertEqual(profile["relationship_score"], 32.0)
            self.assertEqual(profile["trust_score"], 74.0)
            self.assertEqual(profile["transaction_count"], 4)
            self.assertTrue(profile["business_reload_signal"])
            self.assertEqual(profile["evidence_count"], 2)
            self.assertEqual(profile["mean_signal_confidence"], 0.85)
            self.assertGreater(profile["relationship_attention_score"], 0)
            self.assertNotIn("123456", profile["canonical_subject_id"])
            self.assertTrue(profile["canonical_subject_id"].startswith("telegram:chat:"))

    def test_latest_signal_of_each_type_wins_without_duplicate_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            first = self._event(
                db,
                "relationship_cooling_presence",
                "42",
                attributes={"relationship_score": 61},
            )
            latest = self._event(
                db,
                "relationship_cooling_presence",
                "42",
                attributes={"relationship_score": 47},
            )
            summary = relationship_intelligence_summary(root=root)
            self.assertEqual(summary["profile_count"], 1)
            profile = summary["profiles"][0]
            self.assertEqual(profile["relationship_score"], 47.0)
            self.assertEqual(profile["evidence_event_ids"], [latest])
            self.assertNotIn(first, profile["evidence_event_ids"])

    def test_dormant_precedes_cooling_and_business_flags_remain_visible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            self._event(db, "relationship_cooling_presence", "8")
            self._event(db, "relationship_dormant_presence", "8")
            self._event(db, "business_dormant_client_opportunity", "8")
            summary = relationship_intelligence_summary(root=root)
            profile = summary["profiles"][0]
            self.assertEqual(profile["relationship_state"], "DORMANT")
            self.assertTrue(profile["dormant_client_signal"])
            self.assertEqual(summary["state_counts"]["DORMANT"], 1)

    def test_raw_subjects_are_ignored_and_never_leaked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            self._event(
                db,
                "relationship_dormant_presence",
                "raw-telegram-999",
                canonical=False,
            )
            self._event(db, "relationship_cooling_presence", "safe")
            summary = relationship_intelligence_summary(root=root)
            self.assertEqual(summary["noncanonical_events_ignored"], 1)
            self.assertEqual(summary["profile_count"], 1)
            self.assertNotIn("raw-telegram-999", repr(summary))

    def test_malformed_payload_is_skipped_safely(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            event_id = self._event(db, "relationship_dormant_presence", "1")
            self._event(db, "relationship_cooling_presence", "2")
            with db.connect() as con:
                con.execute(
                    "UPDATE events SET payload_json='{bad' WHERE id=?",
                    (event_id,),
                )
            summary = relationship_intelligence_summary(root=root)
            self.assertEqual(summary["status"], "PARTIAL")
            self.assertEqual(summary["malformed_events"], 1)
            self.assertEqual(summary["profile_count"], 1)

    def test_unsupported_relationship_manager_events_do_not_pollute_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            db.add_event(
                "intelligence.signal.unrelated_internal_metric",
                "VM_Relationship_Manager",
                {"confidence": 1.0, "attributes": {}},
                subject_type="chat",
                subject_id=canonical_entity_id("chat", "1"),
            )
            summary = relationship_intelligence_summary(root=root)
            self.assertEqual(summary["status"], "NO_EVIDENCE")
            self.assertEqual(summary["profiles"], [])

    def test_missing_database_is_passive_and_does_not_create_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = PlatformDB(root=root).path
            summary = relationship_intelligence_summary(root=root)
            self.assertEqual(summary["status"], "UNAVAILABLE")
            self.assertEqual(summary["profile_count"], 0)
            self.assertFalse(path.exists())

    def test_read_model_has_no_recommendation_or_execution_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            self._event(db, "relationship_dormant_presence", "100")
            before_events = db.events(limit=100)
            before_recommendations = db.recommendations(limit=100)
            summary = relationship_intelligence_summary(root=root)
            self.assertEqual(before_events, db.events(limit=100))
            self.assertEqual(before_recommendations, db.recommendations(limit=100))
            self.assertTrue(summary["read_only"])
            self.assertTrue(summary["diagnostic_attention_only"])
            self.assertFalse(summary["recommendation_created"])
            self.assertFalse(summary["automatic_acceptance"])
            self.assertFalse(summary["automatic_execution"])
            self.assertFalse(summary["automatic_rule_change"])
            self.assertFalse(summary["external_action_authority"])


if __name__ == "__main__":
    unittest.main()
