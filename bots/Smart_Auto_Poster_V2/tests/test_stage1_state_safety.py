import tempfile
import unittest
from pathlib import Path

from smart_autoposter.db import Database, utcnow
from smart_autoposter.operations import manage_job


class Stage1QueueStateSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "db.sqlite3")
        self.db.init()
        now = utcnow()
        with self.db.connect() as con:
            con.execute("INSERT INTO content(content_id,caption,media_json,enabled,lifecycle_state,created_at,updated_at) VALUES('content','x','[]',1,'ready',?,?)", (now, now))
            con.execute("INSERT INTO campaigns(campaign_id,name,content_id,enabled,lifecycle_state,priority,created_at,updated_at) VALUES('campaign','C','content',1,'active',50,?,?)", (now, now))
            con.execute("INSERT INTO destinations(group_id,group_name,primary_access,preferred_account,mode,enabled,needs_review,updated_at) VALUES(-1001,'group',1,'primary','text',1,0,?)", (now,))

    def tearDown(self):
        self.tmp.cleanup()

    def _job(self, status):
        now = utcnow()
        with self.db.connect() as con:
            cur = con.execute("INSERT INTO queue(job_key,run_key,campaign_id,group_id,content_id,due_at,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                              (f'job-{status}', 'run', 'campaign', -1001, 'content', now, status, now, now))
            return int(cur.lastrowid)

    def test_sending_job_cannot_be_mutated(self):
        job_id = self._job('sending')
        for action in ('cancel', 'retry', 'defer', 'mark-sent'):
            with self.subTest(action=action):
                kwargs = {'minutes': 5} if action == 'defer' else {}
                with self.assertRaisesRegex(RuntimeError, 'currently sending'):
                    manage_job(self.db, job_id, action, **kwargs)
        with self.db.connect() as con:
            self.assertEqual(con.execute('SELECT status FROM queue WHERE id=?', (job_id,)).fetchone()[0], 'sending')

    def test_uncertain_job_cannot_be_retried_cancelled_or_deferred(self):
        job_id = self._job('uncertain')
        with self.assertRaisesRegex(RuntimeError, 'reconciliation'):
            manage_job(self.db, job_id, 'retry')
        with self.assertRaisesRegex(RuntimeError, 'reconcile'):
            manage_job(self.db, job_id, 'cancel')
        with self.assertRaisesRegex(RuntimeError, 'Cannot defer'):
            manage_job(self.db, job_id, 'defer', minutes=5)
        with self.db.connect() as con:
            self.assertEqual(con.execute('SELECT status FROM queue WHERE id=?', (job_id,)).fetchone()[0], 'uncertain')

    def test_uncertain_job_can_be_resolved_as_sent(self):
        job_id = self._job('uncertain')
        updated = manage_job(self.db, job_id, 'mark-sent', actor='test')
        self.assertEqual(updated['status'], 'sent')
        self.assertIsNotNone(updated['resolved_at'])

    def test_failed_job_can_still_be_manually_retried(self):
        job_id = self._job('failed')
        updated = manage_job(self.db, job_id, 'retry', actor='test')
        self.assertEqual(updated['status'], 'retry')
        self.assertIsNone(updated['resolved_at'])


if __name__ == '__main__':
    unittest.main()
