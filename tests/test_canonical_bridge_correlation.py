from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from shared.vm_core.canonical_bridge import bridge_legacy_signals
from shared.vm_core.canonical_correlation import correlate_relationship_search
from shared.vm_core.db import PlatformDB
from shared.vm_core.intelligence_audit import AuditQuery, query_intelligence_events
from shared.vm_core.intelligence_trust import canonical_entity_id


class CanonicalBridgeCorrelationTests(unittest.TestCase):
    def _seed_relationship(self, db: PlatformDB, *, chat_id: str = "123") -> None:
        db.upsert_signal(
            f"relationship:presence:999:{chat_id}",
            "relationship_dormant_presence",
            "A dormant relationship is present in this Telegram chat",
            subject_type="chat",
            subject_id=chat_id,
            score=72,
            confidence=0.95,
            evidence={
                "contact_id": "999",
                "relationship_type": "supplier",
                "lifecycle_stage": "dormant",
                "relationship_score": 28,
                "trust_score": 76,
                "days_overdue": 14,
                "group_interactions": 7,
                "group_last_seen": "2026-09-04T12:00:00+00:00",
            },
        )

    def _seed_search(self, db: PlatformDB, *, chat_id: str = "123") -> None:
        db.upsert_signal(
            f"search:activity_spike:{chat_id}",
            "search_activity_spike",
            "Indexed Telegram activity in this chat is materially above its recent baseline",
            subject_type="chat",
            subject_id=chat_id,
            score=84,
            confidence=0.90,
            evidence={
                "recent_24h_messages": 42,
                "baseline_daily_messages": 10.0,
                "recent_24h_ads": 3,
                "ratio": 4.2,
                "window_hours": 24,
                "baseline_days": 7,
            },
        )

    def test_bridge_publishes_canonical_records_without_raw_contact_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            self._seed_relationship(db)
            result = bridge_legacy_signals(root=root)
            self.assertEqual(result["published"], 1)

            rows = query_intelligence_events(
                AuditQuery(source="VM_Relationship_Manager", limit=10), root=root
            )
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row["subject_id"], canonical_entity_id("chat", "123"))

            payload = json.loads(row["payload_json"])
            evidence = json.loads(row["evidence_json"])
            attributes = payload["attributes"]
            item = evidence["items"][0]
            self.assertNotIn("contact_id", attributes)
            self.assertNotIn("contact_id", item["attributes"])
            self.assertNotEqual(row["subject_id"], "123")
            self.assertNotEqual(item["reference"], "relationship:presence:999:123")
            self.assertTrue(item["reference"].startswith("legacy_signal:"))

    def test_bridge_preserves_legacy_signal_and_skips_unchanged_repeat(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            self._seed_relationship(db)
            first = bridge_legacy_signals(root=root)
            second = bridge_legacy_signals(root=root)
            self.assertEqual(first["published"], 1)
            self.assertEqual(second["published"], 0)
            self.assertEqual(second["skipped_unchanged"], 1)
            self.assertEqual(len(db.signals(10)), 1)

    def test_relationship_and_search_share_one_canonical_chat_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            self._seed_relationship(db)
            self._seed_search(db)
            result = bridge_legacy_signals(root=root)
            self.assertEqual(result["published"], 2)
            rows = query_intelligence_events(AuditQuery(limit=10), root=root)
            subjects = {row["subject_id"] for row in rows}
            self.assertEqual(subjects, {canonical_entity_id("chat", "123")})

    def test_correlation_uses_verified_canonical_event_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            self._seed_relationship(db)
            self._seed_search(db)
            bridge_legacy_signals(root=root)
            result = correlate_relationship_search(root=root)
            self.assertEqual(result["matched_subjects"], 1)
            self.assertEqual(result["published"], 1)
            self.assertEqual(result["invalid_evidence"], 0)

            rows = query_intelligence_events(
                AuditQuery(event_type_prefix="intelligence.inference.relationship_reengagement_opportunity", source="vm_core"),
                root=root,
            )
            self.assertEqual(len(rows), 1)
            payload = json.loads(rows[0]["payload_json"])
            evidence = json.loads(rows[0]["evidence_json"])
            self.assertFalse(payload["attributes"]["recommendation_created"])
            self.assertFalse(payload["attributes"]["automatic_execution"])
            evidence_ids = sorted(item["event_id"] for item in evidence["items"])
            self.assertEqual(evidence_ids, payload["attributes"]["supporting_event_ids"])
            self.assertTrue(all(value > 0 for value in evidence_ids))

    def test_correlation_is_idempotent_for_same_supporting_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            self._seed_relationship(db)
            self._seed_search(db)
            bridge_legacy_signals(root=root)
            first = correlate_relationship_search(root=root)
            second = correlate_relationship_search(root=root)
            self.assertEqual(first["published"], 1)
            self.assertEqual(second["published"], 0)
            self.assertEqual(second["skipped_existing"], 1)

    def test_different_chats_do_not_create_cross_bot_inference(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            self._seed_relationship(db, chat_id="123")
            self._seed_search(db, chat_id="456")
            bridge_legacy_signals(root=root)
            result = correlate_relationship_search(root=root)
            self.assertEqual(result["matched_subjects"], 0)
            self.assertEqual(result["published"], 0)


if __name__ == "__main__":
    unittest.main()
