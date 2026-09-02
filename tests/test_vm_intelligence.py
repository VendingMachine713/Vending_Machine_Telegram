import json
import tempfile
import unittest
from pathlib import Path

from shared.vm_core.db import PlatformDB
from shared.vm_core.events import EventEnvelope, publish
from shared.vm_core.publisher import BotEventPublisher


class VMIntelligenceTests(unittest.TestCase):
    def test_schema_v3_preserves_legacy_events_and_adds_intelligence_tables(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            event_id = db.add_event("legacy.event", "test", {"ok": True})
            with db.connect() as con:
                version = con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
                event = con.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
                tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertEqual(version, "3")
            self.assertEqual(event["event_version"], 1)
            self.assertEqual(event["severity"], "INFO")
            self.assertIn("incidents", tables)
            self.assertIn("intelligence_signals", tables)
            self.assertIn("intelligence_recommendations", tables)

    def test_structured_event_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            event_id = publish(EventEnvelope(
                event_type="Campaign Delivery Failed",
                source="Smart_Auto_Poster_V2",
                payload={"reason": "timeout"},
                severity="error",
                subject_type="destination",
                subject_id="-100123",
                correlation_id="run-1",
                evidence={"attempt_id": 44},
            ), root)
            row = PlatformDB(root=root).events(1)[0]
            self.assertEqual(row["id"], event_id)
            self.assertEqual(row["event_type"], "campaign_delivery_failed")
            self.assertEqual(row["severity"], "ERROR")
            self.assertEqual(row["subject_id"], "-100123")
            self.assertEqual(row["correlation_id"], "run-1")
            self.assertEqual(json.loads(row["evidence_json"])["attempt_id"], 44)

    def test_incident_and_signal_upserts_are_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            first = db.upsert_incident("x", "runtime", "test", "WARNING", "first")
            second = db.upsert_incident("x", "runtime", "test", "ERROR", "second")
            self.assertEqual(first, second)
            incident = db.incidents(1, "OPEN")[0]
            self.assertEqual(incident["severity"], "ERROR")
            self.assertEqual(incident["summary"], "second")
            s1 = db.upsert_signal("sig", "opportunity", "first", score=10, confidence=.5)
            s2 = db.upsert_signal("sig", "opportunity", "second", score=90, confidence=.9)
            self.assertEqual(s1, s2)
            signal = db.signals(1)[0]
            self.assertEqual(signal["score"], 90)
            self.assertEqual(signal["rationale"], "second")

    def test_bot_publisher_is_failure_isolated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pub = BotEventPublisher("Example_Bot", root, instance_id="test-instance")
            event_id = pub.started(mode="test")
            self.assertIsInstance(event_id, int)
            row = PlatformDB(root=root).events(1)[0]
            payload = json.loads(row["payload_json"])
            self.assertEqual(payload["instance_id"], "test-instance")
            self.assertEqual(row["subject_id"], "Example_Bot")

    def test_recommendation_upsert_is_idempotent_and_preserves_human_decisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = PlatformDB(root=Path(tmp))
            db.init()
            first = db.upsert_recommendation(
                "rec-1", "review", "Review evidence", "Initial rationale",
                rule_id="rule-1", priority=60, confidence=.7,
            )
            second = db.upsert_recommendation(
                "rec-1", "review", "Review updated evidence", "Updated rationale",
                rule_id="rule-1", priority=90, confidence=.9,
            )
            self.assertEqual(first, second)
            with db.connect() as con:
                con.execute("UPDATE intelligence_recommendations SET status='DISMISSED' WHERE id=?", (first,))
            db.upsert_recommendation(
                "rec-1", "review", "Review again", "Refreshed rationale",
                rule_id="rule-1", priority=80, confidence=.8, status="PROPOSED",
            )
            row = db.recommendations(1)[0]
            self.assertEqual(row["status"], "DISMISSED")
            self.assertEqual(row["priority"], 80)


if __name__ == "__main__":
    unittest.main()
