import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

BOT = Path(__file__).resolve().parents[1]
ROOT = BOT.parents[1]
for p in (str(BOT), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

import admin_core


class PosterProgressTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.poster = Path(self.tmp.name) / "Smart_Auto_Poster_V2"
        (self.poster / "data").mkdir(parents=True)
        self.db = self.poster / "data" / "smart_autoposter.sqlite3"
        con = sqlite3.connect(self.db)
        try:
            con.executescript(
                '''
                CREATE TABLE queue(
                    id INTEGER PRIMARY KEY,
                    run_key TEXT,
                    campaign_id TEXT,
                    status TEXT,
                    created_at TEXT
                );
                CREATE TABLE live_progress(
                    job_id INTEGER PRIMARY KEY,
                    run_key TEXT,
                    campaign_id TEXT,
                    group_id INTEGER,
                    group_name TEXT,
                    stage TEXT,
                    percent REAL,
                    status_text TEXT,
                    error_text TEXT,
                    updated_at TEXT
                );
                '''
            )
            statuses = ["sent", "sent", "sending", "pending"]
            for i, status in enumerate(statuses, start=1):
                con.execute(
                    "INSERT INTO queue(id,run_key,campaign_id,status,created_at) VALUES(?,?,?,?,?)",
                    (i, "run-1", "C1", status, f"2026-09-02T00:00:0{i}+00:00"),
                )
            con.execute(
                '''INSERT INTO live_progress(job_id,run_key,campaign_id,group_id,group_name,stage,percent,status_text,error_text,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?)''',
                (3, "run-1", "C1", -1003, "Group Three", "uploading", 36.0, "Uploading media to Telegram", None, "2026-09-02T00:00:10+00:00"),
            )
            con.commit()
        finally:
            con.close()

    def tearDown(self):
        self.tmp.cleanup()

    def test_progress_command_renders_overall_and_current_group(self):
        cfg = {"admin_ids": {123}, "allow_mutations": False, "token": "x"}
        with patch.object(admin_core, "POSTER_DIR", self.poster):
            text = admin_core.handle_command(123, "/poster_progress", cfg)
        self.assertIn("LIVE POSTING PROGRESS", text)
        self.assertIn("Posted 2/4", text)
        self.assertIn("50%", text)
        self.assertIn("Left to post 2", text)
        self.assertIn("Current group: Group Three", text)
        self.assertIn("36%", text)
        self.assertIn("Uploading media to Telegram", text)
        self.assertIn("Run: ACTIVE", text)

    def test_progress_off_is_read_only(self):
        cfg = {"admin_ids": {123}, "allow_mutations": False, "token": "x"}
        self.assertIn("stopped", admin_core.handle_command(123, "/poster_progress_off", cfg).lower())


if __name__ == "__main__":
    unittest.main()
