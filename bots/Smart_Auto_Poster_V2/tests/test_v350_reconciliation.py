import tempfile
import unittest
from pathlib import Path

from smart_autoposter.db import Database, utcnow
from smart_autoposter.operations import manage_job
from smart_autoposter.reconciliation import (
    CONFIRM_NOT_SENT,
    CONFIRM_SENT,
    reconcile_uncertain,
    reconciliation_history,
    uncertain_jobs,
)


class V350UncertainReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "data.sqlite3")
        self.db.init()
        now = utcnow()
        with self.db.connect() as con:
            con.execute("INSERT INTO destinations(group_id,group_name,updated_at) VALUES(-1001,'History Test',?)", (now,))
            con.execute("INSERT INTO content(content_id,caption,created_at,updated_at) VALUES('content','x',?,?)", (now, now))
            con.execute("INSERT INTO campaigns(campaign_id,name,content_id,created_at,updated_at) VALUES('camp','Camp','content',?,?)", (now, now))

    def tearDown(self):
        self.tmp.cleanup()

    def _job(self, suffix: str = "1") -> int:
        now = utcnow()
        with self.db.connect() as con:
            cur = con.execute(
                """INSERT INTO queue(job_key,run_key,campaign_id,group_id,content_id,due_at,status,error_kind,last_error,created_at,updated_at)
                   VALUES(?,?,'camp',-1001,'content',?,'uncertain','uncertain_telegram_ack','ambiguous',?,?)""",
                (f"job-{suffix}", f"run-{suffix}", now, now, now),
            )
            return int(cur.lastrowid)

    def test_schema_v8_has_reconciliation_ledger(self):
        with self.db.connect() as con:
            self.assertEqual(con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0], "20")
            names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn("delivery_reconciliations", names)

    def test_generic_retry_and_mark_sent_are_blocked_for_uncertain(self):
        job = self._job()
        with self.assertRaisesRegex(RuntimeError, "reconcile Telegram history"):
            manage_job(self.db, job, "retry")
        with self.assertRaisesRegex(RuntimeError, "evidence-backed"):
            manage_job(self.db, job, "mark-sent")

    def test_confirmed_sent_requires_token_and_is_idempotent(self):
        job = self._job()
        with self.assertRaisesRegex(RuntimeError, CONFIRM_SENT):
            reconcile_uncertain(self.db, job, "sent", evidence="Checked destination history")
        result = reconcile_uncertain(
            self.db, job, "sent", evidence="Album visible in Telegram history", confirmation=CONFIRM_SENT, actor="test"
        )
        self.assertEqual(result["status"], "sent")
        again = reconcile_uncertain(
            self.db, job, "sent", evidence="Album visible in Telegram history", confirmation=CONFIRM_SENT, actor="test"
        )
        self.assertTrue(again["idempotent"])
        self.assertEqual(len(reconciliation_history(self.db, queue_id=job)), 1)

    def test_confirmed_not_sent_releases_only_that_job(self):
        job = self._job("a")
        other = self._job("b")
        with self.assertRaisesRegex(RuntimeError, CONFIRM_NOT_SENT):
            reconcile_uncertain(self.db, job, "not_sent", evidence="No album in history")
        result = reconcile_uncertain(
            self.db, job, "not_sent", evidence="History checked across expected time window",
            confirmation=CONFIRM_NOT_SENT, actor="test",
        )
        self.assertEqual(result["status"], "retry")
        with self.db.connect() as con:
            statuses = {int(r["id"]): r["status"] for r in con.execute("SELECT id,status FROM queue")}
        self.assertEqual(statuses[job], "retry")
        self.assertEqual(statuses[other], "uncertain")

    def test_unresolved_records_evidence_without_mutation(self):
        job = self._job()
        result = reconcile_uncertain(self.db, job, "unresolved", evidence="History unavailable during Telegram outage", actor="test")
        self.assertEqual(result["status"], "uncertain")
        self.assertEqual(len(uncertain_jobs(self.db)), 1)
        history = reconciliation_history(self.db, queue_id=job)
        self.assertEqual(history[0]["outcome"], "unresolved")

    def test_admin_and_control_panel_do_not_offer_generic_uncertain_retry(self):
        root = Path(__file__).parents[1]
        admin = (root / "smart_autoposter" / "admin_bot.py").read_text(encoding="utf-8")
        self.assertIn('if r["status"] == "uncertain"', admin)
        self.assertIn("Retry is blocked until Telegram history is reconciled", admin)
        panel = (root / "CONTROL_PANEL.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("uncertain-list --limit 100", panel)
        self.assertIn("TELEGRAM_HISTORY_CONFIRMED_SENT", panel)
        self.assertIn("TELEGRAM_HISTORY_CONFIRMED_NOT_SENT", panel)


if __name__ == "__main__":
    unittest.main()
