from __future__ import annotations

from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from shared.vm_core.posting_intelligence import posting_intelligence_summary


class PostingIntelligenceTests(unittest.TestCase):
    def _db(self, root: Path) -> sqlite3.Connection:
        path = root / "bots" / "Smart_Auto_Poster_V2" / "data" / "smart_autoposter.sqlite3"
        path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(path)
        con.executescript(
            """
            CREATE TABLE destinations(
                group_id TEXT PRIMARY KEY,
                enabled INTEGER,
                needs_review INTEGER,
                quarantine_until TEXT,
                last_post_at TEXT,
                next_eligible_at TEXT
            );
            CREATE TABLE queue(
                id INTEGER PRIMARY KEY,
                campaign_id TEXT,
                group_id TEXT,
                status TEXT,
                updated_at TEXT,
                due_at TEXT
            );
            CREATE TABLE campaigns(
                campaign_id TEXT PRIMARY KEY,
                enabled INTEGER,
                lifecycle_state TEXT
            );
            """
        )
        return con

    def test_builds_canonical_destination_delivery_profile(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            con = self._db(root)
            con.execute(
                "INSERT INTO destinations VALUES(?,?,?,?,?,?)",
                ("-100123", 1, 0, None, "2026-09-04T19:00:00+00:00", "2026-09-05T00:00:00+00:00"),
            )
            con.execute("INSERT INTO campaigns VALUES('camp-1',1,'active')")
            con.execute(
                "INSERT INTO queue VALUES(1,'camp-1','-100123','sent','2099-01-01T00:00:00+00:00',NULL)"
            )
            con.execute(
                "INSERT INTO queue VALUES(2,'camp-1','-100123','pending','2099-01-01T00:01:00+00:00',NULL)"
            )
            con.commit()
            con.close()

            summary = posting_intelligence_summary(root=root)
            self.assertEqual(summary["status"], "OK")
            self.assertEqual(summary["destination_count"], 1)
            self.assertEqual(summary["campaign_count"], 1)
            self.assertEqual(summary["active_campaign_count"], 1)
            row = summary["destinations"][0]
            self.assertNotIn("-100123", row["canonical_subject_id"])
            self.assertEqual(row["recent_sent"], 1)
            self.assertEqual(row["active_queue_items"], 1)
            self.assertEqual(row["delivery_health"], "HEALTHY")
            self.assertEqual(row["delivery_success_rate"], 1.0)
            self.assertGreater(row["posting_readiness_score"], 0)

    def test_uncertain_delivery_is_attention_and_never_auto_retried(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            con = self._db(root)
            con.execute("INSERT INTO destinations VALUES('42',1,0,NULL,NULL,NULL)")
            con.execute(
                "INSERT INTO queue VALUES(1,'c','42','uncertain','2099-01-01T00:00:00+00:00',NULL)"
            )
            con.commit()
            con.close()

            summary = posting_intelligence_summary(root=root)
            row = summary["destinations"][0]
            self.assertEqual(row["uncertain_queue_items"], 1)
            self.assertEqual(row["delivery_health"], "ATTENTION")
            self.assertFalse(summary["automatic_retry"])
            self.assertFalse(summary["automatic_queue_mutation"])
            self.assertFalse(summary["automatic_execution"])

    def test_failure_history_degrades_destination(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            con = self._db(root)
            con.execute("INSERT INTO destinations VALUES('42',1,0,NULL,NULL,NULL)")
            con.execute(
                "INSERT INTO queue VALUES(1,'c','42','failed','2099-01-01T00:00:00+00:00',NULL)"
            )
            con.commit()
            con.close()

            row = posting_intelligence_summary(root=root)["destinations"][0]
            self.assertEqual(row["recent_failed"], 1)
            self.assertEqual(row["delivery_health"], "DEGRADED")
            self.assertEqual(row["delivery_success_rate"], 0.0)

    def test_review_and_quarantine_reduce_diagnostic_readiness(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            con = self._db(root)
            con.execute("INSERT INTO destinations VALUES('good',1,0,NULL,NULL,NULL)")
            con.execute(
                "INSERT INTO destinations VALUES('review',1,1,'2099-01-01T00:00:00+00:00',NULL,NULL)"
            )
            con.commit()
            con.close()

            summary = posting_intelligence_summary(root=root)
            by_id = {row["needs_review"]: row for row in summary["destinations"]}
            self.assertGreater(
                by_id[False]["posting_readiness_score"],
                by_id[True]["posting_readiness_score"],
            )
            self.assertTrue(by_id[True]["quarantined"])
            self.assertTrue(by_id[True]["posting_readiness_is_diagnostic_only"])

    def test_missing_database_is_passive(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            expected = root / "bots" / "Smart_Auto_Poster_V2" / "data" / "smart_autoposter.sqlite3"
            summary = posting_intelligence_summary(root=root)
            self.assertEqual(summary["status"], "UNAVAILABLE")
            self.assertFalse(expected.exists())
            self.assertTrue(summary["read_only"])

    def test_missing_required_tables_fails_closed(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "bots" / "Smart_Auto_Poster_V2" / "data" / "smart_autoposter.sqlite3"
            path.parent.mkdir(parents=True, exist_ok=True)
            con = sqlite3.connect(path)
            con.execute("CREATE TABLE queue(id INTEGER)")
            con.commit()
            con.close()

            summary = posting_intelligence_summary(root=root)
            self.assertEqual(summary["status"], "REQUIRED_TABLES_MISSING")
            self.assertEqual(summary["destinations"], [])

    def test_no_raw_telegram_ids_or_content_are_exposed(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            con = self._db(root)
            con.execute("INSERT INTO destinations VALUES('987654321',1,0,NULL,NULL,NULL)")
            con.commit()
            con.close()

            summary = posting_intelligence_summary(root=root)
            self.assertNotIn("987654321", repr(summary))
            self.assertFalse(summary["raw_telegram_ids_exposed"])
            self.assertFalse(summary["content_exposed"])

    def test_read_model_has_no_recommendation_or_action_authority(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            con = self._db(root)
            con.execute("INSERT INTO destinations VALUES('42',1,0,NULL,NULL,NULL)")
            con.commit()
            before = con.execute("SELECT * FROM destinations").fetchall()
            con.close()

            summary = posting_intelligence_summary(root=root)
            check = sqlite3.connect(
                root / "bots" / "Smart_Auto_Poster_V2" / "data" / "smart_autoposter.sqlite3"
            )
            after = check.execute("SELECT * FROM destinations").fetchall()
            check.close()
            self.assertEqual(before, after)
            self.assertTrue(summary["diagnostic_only"])
            self.assertFalse(summary["recommendation_created"])
            self.assertFalse(summary["automatic_acceptance"])
            self.assertFalse(summary["automatic_execution"])
            self.assertFalse(summary["automatic_rule_change"])
            self.assertFalse(summary["external_action_authority"])


if __name__ == "__main__":
    unittest.main()
