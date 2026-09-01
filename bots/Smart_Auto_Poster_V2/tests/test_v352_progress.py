import tempfile
import unittest
from pathlib import Path

from smart_autoposter.admin_bot import progress_text, queue_text
from smart_autoposter.cli import build_parser
from smart_autoposter.db import Database, utcnow
from smart_autoposter.progress import progress_bar, progress_snapshot, render_progress_text, status_stage


class V352ProgressTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "db.sqlite3")
        self.db.init()
        now = utcnow()
        with self.db.connect() as con:
            con.execute(
                "INSERT INTO content(content_id,caption,media_json,enabled,lifecycle_state,created_at,updated_at) VALUES('c','caption','[]',1,'ready',?,?)",
                (now, now),
            )
            con.execute(
                "INSERT INTO campaigns(campaign_id,name,content_id,enabled,lifecycle_state,created_at,updated_at) VALUES('camp','Campaign','c',1,'active',?,?)",
                (now, now),
            )
            for i in range(1, 40):
                con.execute(
                    "INSERT INTO destinations(group_id,group_name,primary_access,preferred_account,mode,enabled,needs_review,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                    (-1000 - i, f"Destination {i}", 1, "primary", "photo", 1, 0, now),
                )

    def tearDown(self):
        self.tmp.cleanup()

    def _job(self, n, status, *, run="run:new", error_kind=None, last_error=None, account=None):
        now = utcnow()
        gid = -1000 - n
        with self.db.connect() as con:
            con.execute(
                "INSERT INTO queue(job_key,run_key,campaign_id,group_id,content_id,due_at,status,attempts,max_attempts,error_kind,last_error,account_key,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (f"{run}:{n}", run, "camp", gid, "c", now, status, 0, 4, error_kind, last_error, account, now, now),
            )
            return con.execute("SELECT last_insert_rowid()").fetchone()[0]

    def test_progress_bar_and_stage_mapping(self):
        self.assertEqual(progress_bar(0, 10), "[----------]")
        self.assertEqual(progress_bar(50, 10), "[#####-----]")
        self.assertEqual(progress_bar(100, 10), "[##########]")
        self.assertEqual(status_stage("sent")["stage"], "SENT")
        self.assertEqual(status_stage("deferred")["percent"], 25)
        self.assertEqual(status_stage("sending")["percent"], 65)

    def test_latest_run_snapshot_tracks_each_post_and_outcome(self):
        self._job(1, "sent", run="run:old")
        self._job(2, "pending")
        self._job(3, "deferred", error_kind="slow_mode", last_error="slow_mode: wait", account="primary")
        self._job(4, "sending", account="primary")
        self._job(5, "sent", account="primary")
        self._job(6, "failed", error_kind="write_forbidden", last_error="cannot post", account="primary")
        self._job(7, "uncertain", error_kind="send_timeout_uncertain", last_error="ack missing", account="primary")

        snap = progress_snapshot(self.db, campaign_id="camp", limit=20)
        self.assertTrue(snap["found"])
        self.assertEqual(snap["run_key"], "run:new")
        self.assertEqual(snap["total"], 6)
        self.assertEqual(snap["progress_percent"], 64)
        self.assertEqual(snap["finalised"], 3)
        self.assertEqual(snap["sent"], 1)
        self.assertEqual(snap["deferred"], 1)
        self.assertEqual(snap["attention"], 2)
        self.assertEqual(snap["counts"]["pending"], 1)
        by_status = {j["status"]: j for j in snap["jobs"]}
        self.assertEqual(by_status["deferred"]["stage"], "DEFERRED")
        self.assertEqual(by_status["sent"]["stage_percent"], 100)

    def test_render_explicitly_shows_sent_deferred_sending_and_reason(self):
        self._job(2, "deferred", error_kind="slow_mode", last_error="slow mode", account="primary")
        self._job(3, "sending", account="primary")
        self._job(4, "sent", account="primary")
        text = render_progress_text(progress_snapshot(self.db), emoji=False)
        self.assertIn("AUTO-POST PROGRESS", text)
        self.assertIn("DEFERRED", text)
        self.assertIn("slow_mode", text)
        self.assertIn("SENDING", text)
        self.assertIn("SENT", text)
        self.assertIn("Overall [", text)
        self.assertIn("-> Destination", text)

    def test_admin_progress_stays_within_telegram_message_limit_for_32_posts(self):
        for i in range(1, 33):
            self._job(
                i,
                "deferred",
                error_kind="slow_mode",
                last_error="A deliberately long timing explanation that should be compacted for Telegram progress output",
                account="primary",
            )
        text = progress_text(self.db, limit=40)
        self.assertIn("ðŸ“Š AUTO-POST PROGRESS", text)
        self.assertEqual(text.count("DEFERRED"), 33)  # summary + 32 per-post lines
        self.assertLess(len(text), 4096)

    def test_queue_summary_links_latest_run_progress(self):
        self._job(2, "pending")
        self._job(3, "sent", account="primary")
        text = queue_text(self.db)
        self.assertIn("LATEST RUN", text)
        self.assertIn("finalised", text)
        self.assertIn("sent 1", text)

    def test_cli_exposes_read_only_progress_command(self):
        parser = build_parser()
        args = parser.parse_args(["progress", "--campaign", "camp", "--limit", "32", "--json-only", "--watch", "--interval", "3"])
        self.assertEqual(args.campaign, "camp")
        self.assertEqual(args.limit, 32)
        self.assertTrue(args.json_only)
        self.assertTrue(args.watch)
        self.assertEqual(args.interval, 3.0)

    def test_progress_reader_contains_no_database_mutation_statements(self):
        root = Path(__file__).resolve().parents[1]
        text = (root / "smart_autoposter" / "progress.py").read_text(encoding="utf-8").upper()
        for token in ("UPDATE ", "INSERT ", "DELETE ", "ALTER ", "DROP "):
            self.assertNotIn(token, text)

    def test_admin_and_control_panel_expose_progress_controls(self):
        root = Path(__file__).resolve().parents[1]
        admin = (root / "smart_autoposter" / "admin_bot.py").read_text(encoding="utf-8")
        panel = (root / "CONTROL_PANEL.ps1").read_text(encoding="utf-8-sig")
        self.assertIn('cmd == "/progress"', admin)
        self.assertIn('Refresh progress', admin)
        self.assertIn('b"progress"', admin)
        self.assertIn("89. Auto-post progress", panel)
        self.assertIn("app.py progress", panel)


if __name__ == "__main__":
    unittest.main()
