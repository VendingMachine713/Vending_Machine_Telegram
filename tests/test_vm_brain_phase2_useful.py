from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from shared.vm_core.db import PlatformDB
from shared.vm_core.entity_graph import entity_graph
from shared.vm_core.mission_control import mission_control
from shared.vm_core.opportunity_intelligence import opportunities, opportunity_summary


class VMBrainPhase2UsefulTests(unittest.TestCase):
    def _db(self, root: Path) -> PlatformDB:
        db = PlatformDB(root=root)
        db.init()
        return db

    def test_entity_graph_links_shared_metadata_without_message_content(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            db = self._db(root)
            with db.connect() as con:
                con.execute(
                    "INSERT INTO destinations(telegram_id,title,entity_type,active,source,last_seen_utc,metadata_json) VALUES('42','Test Group','telegram_destination',1,'test','2026-01-01','{}')"
                )
            db.upsert_signal(
                "signal:42", "relationship_attention", "attention", subject_type="destination",
                subject_id="42", score=80, confidence=0.9,
            )
            graph = entity_graph(root)
            self.assertGreaterEqual(graph["node_count"], 2)
            self.assertTrue(any(edge["relation"] == "about" for edge in graph["edges"]))
            self.assertFalse(graph["message_content_copied"])
            self.assertFalse(graph["bot_databases_written"])
            self.assertFalse(graph["external_action_authority"])

    def test_positive_signal_creates_ranked_opportunity(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            db = self._db(root)
            db.upsert_signal(
                "momentum:1", "relationship_momentum", "growing", subject_type="contact",
                subject_id="1", score=85, confidence=0.9,
            )
            rows = opportunities(root)
            self.assertEqual(rows[0]["subject_id"], "1")
            self.assertGreater(rows[0]["opportunity_score"], 0)
            self.assertFalse(rows[0]["blocked"])
            self.assertFalse(rows[0]["automatic_execution"])

    def test_blocking_incident_suppresses_high_risk_opportunity(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            db = self._db(root)
            db.upsert_signal(
                "campaign:9", "campaign_state", "active", subject_type="destination",
                subject_id="9", score=95, confidence=1.0,
            )
            db.upsert_incident(
                "uncertain:9", "campaign.delivery_uncertain", "test", "ERROR",
                "Delivery is uncertain", subject_type="destination", subject_id="9",
            )
            row = opportunities(root)[0]
            self.assertTrue(row["blocked"])
            self.assertEqual(row["block_reason"], "Delivery is uncertain")
            self.assertGreater(row["risk_score"], 0)

    def test_delivery_risk_reduces_opportunity_score(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            db = self._db(root)
            db.upsert_signal(
                "positive:7", "campaign_state", "active", subject_type="destination",
                subject_id="7", score=100, confidence=1.0,
            )
            before = opportunities(root)[0]["opportunity_score"]
            db.upsert_signal(
                "risk:7", "delivery_risk", "uncertain", subject_type="destination",
                subject_id="7", score=80, confidence=1.0,
            )
            after = opportunities(root)[0]["opportunity_score"]
            self.assertLess(after, before)

    def test_mission_control_is_passive_and_surfaces_attention(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            db = self._db(root)
            db.upsert_incident(
                "incident:1", "test", "unit", "WARNING", "Needs review",
                subject_type="contact", subject_id="1",
            )
            db.upsert_signal(
                "momentum:1", "relationship_momentum", "growing", subject_type="contact",
                subject_id="1", score=70, confidence=0.8,
            )
            summary = mission_control(root)
            self.assertEqual(summary["headline"]["open_incidents"], 1)
            self.assertGreaterEqual(summary["headline"]["opportunities"], 1)
            self.assertFalse(summary["automatic_acceptance"])
            self.assertFalse(summary["automatic_execution"])
            self.assertFalse(summary["external_action_authority"])

    def test_opportunity_summary_never_claims_action_authority(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            self._db(root)
            summary = opportunity_summary(root)
            self.assertFalse(summary["automatic_acceptance"])
            self.assertFalse(summary["automatic_execution"])
            self.assertFalse(summary["external_action_authority"])


if __name__ == "__main__":
    unittest.main()
