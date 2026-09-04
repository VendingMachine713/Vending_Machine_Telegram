from __future__ import annotations

from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from shared.vm_core.db import PlatformDB
from shared.vm_core.intelligence_trust import canonical_entity_id
from shared.vm_core.risk_fusion import canonical_risk_fusion_summary


class RiskFusionTests(unittest.TestCase):
    def _posting_db(self, root: Path) -> sqlite3.Connection:
        path = root / "bots" / "Smart_Auto_Poster_V2" / "data" / "smart_autoposter.sqlite3"
        path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(path)
        con.executescript(
            """
            CREATE TABLE destinations(
                group_id TEXT PRIMARY KEY, enabled INTEGER, needs_review INTEGER,
                quarantine_until TEXT, last_post_at TEXT, next_eligible_at TEXT
            );
            CREATE TABLE queue(
                id INTEGER PRIMARY KEY, campaign_id TEXT, group_id TEXT,
                status TEXT, updated_at TEXT, due_at TEXT
            );
            """
        )
        return con

    def test_fuses_guard_and_posting_risk_by_canonical_subject(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            subject = canonical_entity_id("chat", "42")
            event_id = db.add_event(
                "intelligence.signal.guard_risk_elevated",
                "VM_Guard",
                {"confidence": 1.0, "attributes": {"score": 72}},
                subject_type="chat",
                subject_id=subject,
            )
            con = self._posting_db(root)
            con.execute("INSERT INTO destinations VALUES('42',1,0,NULL,NULL,NULL)")
            con.execute(
                "INSERT INTO queue VALUES(1,'c','42','uncertain','2099-01-01T00:00:00+00:00',NULL)"
            )
            con.commit()
            con.close()

            summary = canonical_risk_fusion_summary(root=root)
            self.assertEqual(summary["status"], "OK")
            self.assertEqual(summary["subject_count"], 1)
            row = summary["subjects"][0]
            self.assertEqual(row["canonical_subject_id"], subject)
            self.assertEqual(row["guard_evidence_event_id"], event_id)
            self.assertEqual(row["guard_risk_score"], 72.0)
            self.assertGreaterEqual(row["posting_risk_score"], 80.0)
            self.assertEqual(row["risk_level"], "HIGH")
            self.assertTrue(row["review_required"])
            self.assertFalse(row["automatic_suppression"])

    def test_guard_only_risk_is_preserved(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            subject = canonical_entity_id("chat", "7")
            db.add_event(
                "intelligence.signal.guard_risk_elevated",
                "VM_Guard",
                {"attributes": {"score": 55}},
                subject_type="chat",
                subject_id=subject,
            )
            summary = canonical_risk_fusion_summary(root=root)
            row = summary["subjects"][0]
            self.assertEqual(row["risk_score"], 55.0)
            self.assertEqual(row["risk_level"], "MEDIUM")
            self.assertFalse(row["posting_evidence_available"])

    def test_posting_only_risk_is_preserved(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            con = self._posting_db(root)
            con.execute("INSERT INTO destinations VALUES('8',1,1,NULL,NULL,NULL)")
            con.commit()
            con.close()
            summary = canonical_risk_fusion_summary(root=root)
            row = summary["subjects"][0]
            self.assertEqual(row["guard_risk_score"], 0.0)
            self.assertEqual(row["posting_risk_score"], 60.0)
            self.assertEqual(row["risk_level"], "MEDIUM")

    def test_latest_guard_event_wins_idempotently(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            subject = canonical_entity_id("chat", "9")
            db.add_event(
                "intelligence.signal.guard_risk_elevated",
                "VM_Guard",
                {"attributes": {"score": 90}},
                subject_type="chat",
                subject_id=subject,
            )
            latest = db.add_event(
                "intelligence.signal.guard_risk_elevated",
                "VM_Guard",
                {"attributes": {"score": 20}},
                subject_type="chat",
                subject_id=subject,
            )
            row = canonical_risk_fusion_summary(root=root)["subjects"][0]
            self.assertEqual(row["guard_evidence_event_id"], latest)
            self.assertEqual(row["guard_risk_score"], 20.0)

    def test_noncanonical_and_malformed_guard_events_fail_closed(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = PlatformDB(root=root)
            db.init()
            raw = db.add_event(
                "intelligence.signal.guard_risk_elevated",
                "VM_Guard",
                {"attributes": {"score": 99}},
                subject_type="chat",
                subject_id="raw-telegram-id",
            )
            subject = canonical_entity_id("chat", "10")
            broken = db.add_event(
                "intelligence.signal.guard_risk_elevated",
                "VM_Guard",
                {"attributes": {"score": 50}},
                subject_type="chat",
                subject_id=subject,
            )
            with db.connect() as con:
                con.execute("UPDATE events SET payload_json='{bad' WHERE id=?", (broken,))
            summary = canonical_risk_fusion_summary(root=root)
            self.assertEqual(summary["noncanonical_guard_events_ignored"], 1)
            self.assertEqual(summary["malformed_guard_events"], 1)
            self.assertNotIn("raw-telegram-id", repr(summary))
            self.assertNotIn(str(raw), repr(summary["subjects"]))

    def test_no_action_or_rule_authority(self) -> None:
        with TemporaryDirectory() as tmp:
            summary = canonical_risk_fusion_summary(root=Path(tmp))
            self.assertTrue(summary["read_only"])
            self.assertTrue(summary["diagnostic_only"])
            self.assertFalse(summary["automatic_acceptance"])
            self.assertFalse(summary["automatic_execution"])
            self.assertFalse(summary["automatic_threshold_change"])
            self.assertFalse(summary["automatic_rule_change"])
            self.assertFalse(summary["external_action_authority"])


if __name__ == "__main__":
    unittest.main()
