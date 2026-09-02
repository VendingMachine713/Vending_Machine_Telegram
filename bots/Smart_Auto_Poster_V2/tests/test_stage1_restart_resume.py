import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from smart_autoposter.db import Database, utcnow
from smart_autoposter.worker import Worker


class Stage1RestartResumeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "db.sqlite3")
        self.db.init()
        now = utcnow()
        ended = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(timespec="seconds")
        with self.db.connect() as con:
            con.execute(
                "INSERT INTO content(content_id,caption,media_json,enabled,lifecycle_state,created_at,updated_at) VALUES('content','x','[]',1,'ready',?,?)",
                (now, now),
            )
            campaigns = [
                ("active", "Active", 1, "active", None),
                ("paused", "Paused", 0, "paused", None),
                ("archived", "Archived", 0, "archived", None),
                ("ended", "Ended", 1, "active", ended),
            ]
            for cid, name, enabled, lifecycle, end_at in campaigns:
                con.execute(
                    "INSERT INTO campaigns(campaign_id,name,content_id,enabled,lifecycle_state,priority,end_at,created_at,updated_at) VALUES(?,?,?,?,?,50,?,?,?)",
                    (cid, name, "content", enabled, lifecycle, end_at, now, now),
                )
            con.execute(
                "INSERT INTO destinations(group_id,group_name,primary_access,secondary_access,preferred_account,mode,enabled,needs_review,updated_at) VALUES(-1001,'G',1,0,'primary','text',1,0,?)",
                (now,),
            )

    def tearDown(self):
        self.tmp.cleanup()

    def _job(self, key, campaign, status):
        now = utcnow()
        with self.db.connect() as con:
            con.execute(
                "INSERT INTO queue(job_key,run_key,campaign_id,group_id,content_id,due_at,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (key, "run", campaign, -1001, "content", now, status, now, now),
            )

    def _statuses(self):
        with self.db.connect() as con:
            return {
                r["job_key"]: r["status"]
                for r in con.execute("SELECT job_key,status FROM queue ORDER BY id").fetchall()
            }

    def test_startup_recovery_preserves_resumable_work_and_expires_terminal_work(self):
        self._job("inflight", "active", "sending")
        self._job("pending", "active", "pending")
        self._job("retry", "active", "retry")
        self._job("paused", "paused", "deferred")
        self._job("archived", "archived", "pending")
        self._job("ended", "ended", "pending")

        worker = Worker(self.db, None)
        recovered = worker.recover_interrupted_sends()

        self.assertEqual(recovered, 1)
        self.assertEqual(
            self._statuses(),
            {
                "inflight": "uncertain",
                "pending": "pending",
                "retry": "retry",
                "paused": "deferred",
                "archived": "expired",
                "ended": "expired",
            },
        )
        summary = worker.last_recovery_summary
        self.assertEqual(summary["interrupted_to_uncertain"], 1)
        self.assertEqual(summary["terminal_campaign_jobs_expired"], 2)
        self.assertEqual(summary["resumable_active_jobs"], 2)
        self.assertEqual(summary["preserved_paused_jobs"], 1)
        self.assertEqual(summary["uncertain_total"], 1)

    def test_startup_recovery_is_idempotent_within_worker_runtime(self):
        self._job("inflight", "active", "sending")
        worker = Worker(self.db, None)
        self.assertEqual(worker.recover_interrupted_sends(), 1)
        first_summary = dict(worker.last_recovery_summary)
        self.assertEqual(worker.recover_interrupted_sends(), 0)
        self.assertEqual(worker.last_recovery_summary, first_summary)
        self.assertEqual(self._statuses()["inflight"], "uncertain")

    def test_restart_recovery_never_makes_uncertain_job_claimable(self):
        self._job("inflight", "active", "sending")
        self._job("pending", "active", "pending")
        worker = Worker(self.db, None)
        worker.recover_interrupted_sends()

        claimed = worker.claim()
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed["job_key"], "pending")
        with self.db.connect() as con:
            uncertain = con.execute("SELECT status FROM queue WHERE job_key='inflight'").fetchone()[0]
        self.assertEqual(uncertain, "uncertain")

    def test_paused_queue_is_preserved_and_not_claimed(self):
        self._job("paused", "paused", "pending")
        worker = Worker(self.db, None)
        worker.recover_interrupted_sends()
        self.assertIsNone(worker.claim())
        self.assertEqual(self._statuses()["paused"], "pending")


if __name__ == "__main__":
    unittest.main()
