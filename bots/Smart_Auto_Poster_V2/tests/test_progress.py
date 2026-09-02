import asyncio
import io
import tempfile
import unittest
from pathlib import Path

from shared.vm_core.progress import render_bar, transfer_percent
from smart_autoposter.core import create_campaign, create_content, enqueue_campaign
from smart_autoposter.db import Database, utcnow
from smart_autoposter.progress import TerminalProgressReporter, current_group_progress, progress_text, run_progress, set_group_progress
from smart_autoposter.worker import Worker


class FakePool:
    def __init__(self):
        self.progress_values = []

    async def send(self, account_key, group_id, caption, media, mode, topic_id=None, progress_callback=None):
        if progress_callback:
            progress_callback(36, 100)
            self.progress_values.append(36)
            progress_callback(50, 100)
            self.progress_values.append(50)
            progress_callback(100, 100)
            self.progress_values.append(100)
        return [12345]


class ProgressTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = Database(self.root / "data" / "test.sqlite3")
        self.db.init()
        self.media = self.root / "one.jpg"
        self.media.write_bytes(b"test-media")
        now = utcnow()
        with self.db.connect() as con:
            for gid in (-1001, -1002, -1003, -1004):
                con.execute(
                    '''INSERT INTO destinations(group_id,group_name,primary_access,secondary_access,preferred_account,mode,enabled,needs_review,updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?)''',
                    (gid, f"Group {abs(gid)}", 1, 1, "primary", "photo", 1, 0, now),
                )
                con.execute("INSERT INTO destination_tags(group_id,tag) VALUES(?,?)", (gid, "main"))
        create_content(self.db, "AD1", "hello", [str(self.media)])
        create_campaign(self.db, "C1", "Campaign 1", "AD1", tags="main")
        with self.db.connect() as con:
            con.execute("UPDATE campaigns SET enabled=1,lifecycle_state='active' WHERE campaign_id='C1'")
        result = enqueue_campaign(self.db, "C1", run_key="progress-run")
        self.assertEqual(result["inserted"], 4)

    def tearDown(self):
        self.tmp.cleanup()

    def _job(self, gid=-1001):
        with self.db.connect() as con:
            row = con.execute(
                '''SELECT q.*,d.group_name,d.mode,d.topic_id,d.preferred_account,
                          d.primary_access,d.secondary_access,d.quiet_start,d.quiet_end,
                          d.min_interval_seconds,c.min_destination_interval_seconds campaign_interval,
                          ct.caption,ct.media_json,COALESCE(q.content_id,c.content_id) content_id
                   FROM queue q JOIN destinations d ON d.group_id=q.group_id
                   JOIN campaigns c ON c.campaign_id=q.campaign_id
                   JOIN content ct ON ct.content_id=COALESCE(q.content_id,c.content_id)
                   WHERE q.group_id=?''',
                (gid,),
            ).fetchone()
        return dict(row)

    def test_bar_fill_correlates_with_numeric_percentage(self):
        bar36 = render_bar(36, width=100)
        self.assertEqual(bar36.count("🟩"), 36)
        self.assertTrue(bar36.endswith("36%"))
        bar50 = render_bar(50, width=20)
        self.assertEqual(bar50.count("🟩"), 10)
        self.assertEqual(bar50.count("⬜"), 10)
        self.assertEqual(transfer_percent(36, 100), 36.0)

    def test_group_progress_is_persisted_for_other_processes(self):
        job = self._job()
        set_group_progress(self.db, job, "uploading", 36)
        row = current_group_progress(self.db, run_key="progress-run", campaign_id="C1")
        self.assertEqual(row["job_id"], job["id"])
        self.assertEqual(row["stage"], "uploading")
        self.assertEqual(row["percent"], 36.0)
        self.assertIn("Uploading media", row["status_text"])

    def test_overall_progress_uses_real_queue_counts(self):
        with self.db.connect() as con:
            ids = [r[0] for r in con.execute("SELECT id FROM queue WHERE run_key='progress-run' ORDER BY id").fetchall()]
            con.execute("UPDATE queue SET status='sent' WHERE id=?", (ids[0],))
            con.execute("UPDATE queue SET status='failed' WHERE id=?", (ids[1],))
            con.execute("UPDATE queue SET status='uncertain' WHERE id=?", (ids[2],))
            con.execute("UPDATE queue SET status='sending' WHERE id=?", (ids[3],))
        summary = run_progress(self.db, run_key="progress-run", campaign_id="C1")
        self.assertEqual(summary.total, 4)
        self.assertEqual(summary.sent, 1)
        self.assertEqual(summary.posted_percent, 25.0)
        self.assertEqual(summary.remaining, 3)
        self.assertEqual(summary.failed, 1)
        self.assertEqual(summary.uncertain, 1)
        text = progress_text(self.db, campaign_id="C1")
        self.assertIn("Posted 1/4", text)
        self.assertIn("Left to post 3", text)
        self.assertIn("Problems 2", text)

    def test_terminal_callback_reports_milestones_without_chunk_spam(self):
        stream = io.StringIO()
        reporter = TerminalProgressReporter(self.db, stream=stream, min_percent_step=5)
        callback = reporter.callback(self._job())
        callback(1, 100)
        callback(2, 100)
        callback(4, 100)
        callback(5, 100)
        lines = [x for x in stream.getvalue().splitlines() if x.strip()]
        self.assertEqual(len(lines), 2)
        self.assertIn("1%", lines[0])
        self.assertIn("5%", lines[1])

    def test_worker_records_real_transfer_then_completed_delivery(self):
        pool = FakePool()
        stream = io.StringIO()
        reporter = TerminalProgressReporter(self.db, stream=stream, min_percent_step=1)
        worker = Worker(self.db, pool, progress_reporter=reporter)
        auth = {
            "primary": {"authorized": True, "identity": "primary", "user_id": 1},
            "secondary": {"authorized": True, "identity": "secondary", "user_id": 2},
        }
        worker.sync_accounts(auth, {"primary": "p", "secondary": "s"})
        worked = asyncio.run(worker.run_once(auth))
        self.assertTrue(worked)
        self.assertEqual(pool.progress_values, [36, 50, 100])
        with self.db.connect() as con:
            sent = con.execute("SELECT COUNT(*) FROM queue WHERE status='sent'").fetchone()[0]
            progress = con.execute("SELECT stage,percent FROM live_progress ORDER BY updated_at DESC LIMIT 1").fetchone()
        self.assertEqual(sent, 1)
        self.assertEqual(progress["stage"], "sent")
        self.assertEqual(progress["percent"], 100.0)
        output = stream.getvalue()
        self.assertIn("36%", output)
        self.assertIn("50%", output)
        self.assertIn("Posted successfully", output)


if __name__ == "__main__":
    unittest.main()
