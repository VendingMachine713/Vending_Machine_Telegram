from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from shared.vm_core.db import PlatformDB
from shared.vm_core.group_search_intelligence import group_search_intelligence_summary
from shared.vm_core.intelligence_trust import canonical_entity_id


class GroupSearchIntelligenceTests(unittest.TestCase):
    def _event(
        self,
        db: PlatformDB,
        native_subject: str,
        *,
        canonical: bool = True,
        confidence: float = 0.85,
        attributes: dict | None = None,
    ) -> int:
        subject = canonical_entity_id("chat", native_subject) if canonical else native_subject
        return db.add_event(
            "intelligence.signal.search_activity_spike",
            "Universal_Search",
            {"confidence": confidence, "attributes": dict(attributes or {})},
            subject_type="chat",
            subject_id=subject,
        )

    def test_builds_canonical_group_activity_profile_without_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            event_id = self._event(
                db,
                "9001",
                attributes={
                    "recent_24h_messages": 48,
                    "baseline_daily_messages": 12.0,
                    "recent_24h_ads": 6,
                    "ratio": 4.0,
                    "window_hours": 24,
                    "baseline_days": 7,
                    "score": 88,
                    "message_text": "must never leak",
                },
            )
            summary = group_search_intelligence_summary(root=root)
            self.assertEqual(summary["status"], "OK")
            self.assertEqual(summary["group_count"], 1)
            group = summary["groups"][0]
            self.assertEqual(group["evidence_event_id"], event_id)
            self.assertEqual(group["recent_24h_messages"], 48)
            self.assertEqual(group["baseline_daily_messages"], 12.0)
            self.assertEqual(group["activity_ratio"], 4.0)
            self.assertEqual(group["recent_24h_ads"], 6)
            self.assertEqual(group["recent_ad_share"], 0.125)
            self.assertEqual(group["source_signal_score"], 88.0)
            self.assertGreater(group["group_momentum_score"], 0)
            self.assertNotIn("9001", group["canonical_subject_id"])
            self.assertNotIn("message_text", repr(summary))
            self.assertFalse(summary["content_exposed"])

    def test_latest_spike_per_group_is_idempotent_current_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            first = self._event(db, "1", attributes={"ratio": 2.0, "recent_24h_messages": 20})
            latest = self._event(db, "1", attributes={"ratio": 3.0, "recent_24h_messages": 30})
            summary = group_search_intelligence_summary(root=root)
            self.assertEqual(summary["group_count"], 1)
            group = summary["groups"][0]
            self.assertEqual(group["evidence_event_id"], latest)
            self.assertNotEqual(group["evidence_event_id"], first)
            self.assertEqual(group["activity_ratio"], 3.0)

    def test_ratio_can_be_derived_from_safe_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            self._event(
                db,
                "2",
                attributes={
                    "recent_24h_messages": 30,
                    "baseline_daily_messages": 10,
                    "recent_24h_ads": 0,
                },
            )
            group = group_search_intelligence_summary(root=root)["groups"][0]
            self.assertEqual(group["activity_ratio"], 3.0)
            self.assertEqual(group["recent_ad_share"], 0.0)

    def test_raw_group_ids_are_ignored_and_not_leaked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            self._event(db, "raw-group-123", canonical=False)
            self._event(db, "safe")
            summary = group_search_intelligence_summary(root=root)
            self.assertEqual(summary["noncanonical_events_ignored"], 1)
            self.assertEqual(summary["group_count"], 1)
            self.assertNotIn("raw-group-123", repr(summary))

    def test_malformed_payload_is_skipped_safely(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            broken = self._event(db, "1")
            self._event(db, "2", attributes={"ratio": 2})
            with db.connect() as con:
                con.execute("UPDATE events SET payload_json='{bad' WHERE id=?", (broken,))
            summary = group_search_intelligence_summary(root=root)
            self.assertEqual(summary["status"], "PARTIAL")
            self.assertEqual(summary["malformed_events"], 1)
            self.assertEqual(summary["group_count"], 1)

    def test_other_sources_and_signal_types_do_not_pollute_group_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            subject = canonical_entity_id("chat", "3")
            db.add_event(
                "intelligence.signal.search_activity_spike",
                "Other_Search",
                {"confidence": 1, "attributes": {"ratio": 99}},
                subject_type="chat",
                subject_id=subject,
            )
            db.add_event(
                "intelligence.signal.search_query_match",
                "Universal_Search",
                {"confidence": 1, "attributes": {}},
                subject_type="chat",
                subject_id=subject,
            )
            summary = group_search_intelligence_summary(root=root)
            self.assertEqual(summary["status"], "NO_EVIDENCE")
            self.assertEqual(summary["groups"], [])

    def test_missing_database_is_read_only_and_does_not_create_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = PlatformDB(root=root).path
            summary = group_search_intelligence_summary(root=root)
            self.assertEqual(summary["status"], "UNAVAILABLE")
            self.assertFalse(path.exists())

    def test_read_model_has_no_recommendation_or_execution_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            self._event(db, "4", attributes={"ratio": 5, "recent_24h_messages": 60})
            before_events = db.events(limit=100)
            before_recommendations = db.recommendations(limit=100)
            summary = group_search_intelligence_summary(root=root)
            self.assertEqual(before_events, db.events(limit=100))
            self.assertEqual(before_recommendations, db.recommendations(limit=100))
            self.assertTrue(summary["read_only"])
            self.assertTrue(summary["diagnostic_momentum_only"])
            self.assertFalse(summary["recommendation_created"])
            self.assertFalse(summary["automatic_acceptance"])
            self.assertFalse(summary["automatic_execution"])
            self.assertFalse(summary["automatic_rule_change"])
            self.assertFalse(summary["external_action_authority"])


if __name__ == "__main__":
    unittest.main()
