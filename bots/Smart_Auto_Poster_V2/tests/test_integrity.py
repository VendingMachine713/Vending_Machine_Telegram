import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from smart_autoposter.db import Database, utcnow
from smart_autoposter.integrity import integrity_report


class IntegrityReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "db.sqlite3")
        self.db.init()
        now = utcnow()
        with self.db.connect() as con:
            con.execute("INSERT INTO content(content_id,caption,media_json,enabled,lifecycle_state,created_at,updated_at) VALUES('content','x','[]',1,'ready',?,?)", (now, now))
            con.execute("INSERT INTO campaigns(campaign_id,name,content_id,enabled,lifecycle_state,priority,created_at,updated_at) VALUES('campaign','C','content',1,'active',50,?,?)", (now, now))
            con.execute("INSERT INTO destinations(group_id,group_name,primary_access,secondary_access,preferred_account,mode,enabled,needs_review,updated_at) VALUES(-1001,'G',1,0,'primary','text',1,0,?)", (now,))

    def tearDown(self):
        self.tmp.cleanup()

    def _insert_job(self, key, status, *, updated_at=None, resolved_at=None, error_kind=None, attempts=0, max_attempts=4):
        now = utcnow()
        with self.db.connect() as con:
            con.execute(
                "INSERT INTO queue(job_key,run_key,campaign_id,group_id,content_id,due_at,status,attempts,max_attempts,error_kind,resolved_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (key, 'run', 'campaign', -1001, 'content', now, status, attempts, max_attempts, error_kind, resolved_at, now, updated_at or now),
            )

    def test_clean_database_is_healthy(self):
        report = integrity_report(self.db)
        self.assertTrue(report['quick_check_ok'])
        self.assertTrue(report['healthy'])

    def test_stale_sending_is_detected_without_mutation(self):
        old = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat(timespec='seconds')
        self._insert_job('stale', 'sending', updated_at=old)
        report = integrity_report(self.db, stale_sending_seconds=60)
        self.assertFalse(report['healthy'])
        self.assertEqual(report['issue_counts']['stale_sending'], 1)
        with self.db.connect() as con:
            status = con.execute("SELECT status FROM queue WHERE job_key='stale'").fetchone()[0]
        self.assertEqual(status, 'sending')

    def test_uncertain_without_reason_is_detected(self):
        self._insert_job('uncertain', 'uncertain')
        report = integrity_report(self.db)
        self.assertEqual(report['issue_counts']['uncertain_without_reason'], 1)

    def test_terminal_without_resolution_is_detected(self):
        self._insert_job('failed', 'failed')
        report = integrity_report(self.db)
        self.assertEqual(report['issue_counts']['terminal_without_resolution'], 1)


if __name__ == '__main__':
    unittest.main()
