import sqlite3
import tempfile
import unittest
from pathlib import Path

from smart_autoposter.db import Database


class MigrationTests(unittest.TestCase):
    def test_additive_migration(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "old.sqlite3"
            con = sqlite3.connect(p)
            con.execute("CREATE TABLE accounts(account_key TEXT PRIMARY KEY,session_name TEXT NOT NULL,enabled INTEGER NOT NULL DEFAULT 1,authorized INTEGER,identity TEXT,cooldown_until TEXT,consecutive_failures INTEGER NOT NULL DEFAULT 0,last_error TEXT,updated_at TEXT NOT NULL)")
            con.execute("CREATE TABLE queue(id INTEGER PRIMARY KEY,job_key TEXT UNIQUE,campaign_id TEXT,group_id INTEGER,account_key TEXT,due_at TEXT,status TEXT,attempts INTEGER,max_attempts INTEGER,last_error TEXT,telegram_message_ids TEXT,created_at TEXT,updated_at TEXT)")
            con.commit(); con.close()
            db=Database(p); db.init()
            with db.connect() as con:
                ac={r[1] for r in con.execute("PRAGMA table_info(accounts)")}
                qc={r[1] for r in con.execute("PRAGMA table_info(queue)")}
                version=con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
            self.assertIn("last_success_at",ac)
            self.assertIn("run_key",qc)
            self.assertIn("content_id",qc)
            self.assertEqual(version, "20")

    def test_existing_content_table_migrates_before_fingerprint_index(self):
        """Regression for V2.2.3 -> V2.4: index creation must follow ALTER TABLE."""
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "v223.sqlite3"
            con = sqlite3.connect(p)
            con.executescript("""
                CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE accounts(account_key TEXT PRIMARY KEY,session_name TEXT NOT NULL,enabled INTEGER NOT NULL DEFAULT 1,authorized INTEGER,identity TEXT,cooldown_until TEXT,consecutive_failures INTEGER NOT NULL DEFAULT 0,last_error TEXT,updated_at TEXT NOT NULL);
                CREATE TABLE destinations(group_id INTEGER PRIMARY KEY,group_name TEXT NOT NULL,chat_type TEXT,username TEXT,forum INTEGER NOT NULL DEFAULT 0,topic_id INTEGER,primary_access INTEGER NOT NULL DEFAULT 0,secondary_access INTEGER NOT NULL DEFAULT 0,preferred_account TEXT NOT NULL DEFAULT 'primary',mode TEXT NOT NULL DEFAULT 'review',enabled INTEGER NOT NULL DEFAULT 0,needs_review INTEGER NOT NULL DEFAULT 1,min_interval_seconds INTEGER NOT NULL DEFAULT 0,quiet_start TEXT,quiet_end TEXT,last_post_at TEXT,next_eligible_at TEXT,consecutive_failures INTEGER NOT NULL DEFAULT 0,quarantine_until TEXT,notes TEXT,updated_at TEXT NOT NULL);
                CREATE TABLE destination_tags(group_id INTEGER NOT NULL,tag TEXT NOT NULL,PRIMARY KEY(group_id,tag));
                CREATE TABLE content(content_id TEXT PRIMARY KEY,caption TEXT NOT NULL DEFAULT '',media_json TEXT NOT NULL DEFAULT '[]',enabled INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
                CREATE TABLE campaigns(campaign_id TEXT PRIMARY KEY,name TEXT NOT NULL,content_id TEXT NOT NULL,enabled INTEGER NOT NULL DEFAULT 0,priority INTEGER NOT NULL DEFAULT 50,target_tags TEXT NOT NULL DEFAULT '',start_at TEXT,end_at TEXT,min_destination_interval_seconds INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
                CREATE TABLE campaign_schedules(campaign_id TEXT PRIMARY KEY,mode TEXT NOT NULL DEFAULT 'manual',interval_seconds INTEGER,daily_times_json TEXT NOT NULL DEFAULT '[]',days_json TEXT NOT NULL DEFAULT '[]',timezone TEXT NOT NULL DEFAULT 'Australia/Adelaide',next_run_at TEXT,last_run_at TEXT,jitter_seconds INTEGER NOT NULL DEFAULT 0,enabled INTEGER NOT NULL DEFAULT 0,updated_at TEXT NOT NULL);
                CREATE TABLE queue(id INTEGER PRIMARY KEY AUTOINCREMENT,job_key TEXT NOT NULL UNIQUE,run_key TEXT,campaign_id TEXT NOT NULL,group_id INTEGER NOT NULL,account_key TEXT,due_at TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',attempts INTEGER NOT NULL DEFAULT 0,max_attempts INTEGER NOT NULL DEFAULT 4,last_error TEXT,telegram_message_ids TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
                CREATE TABLE events(id INTEGER PRIMARY KEY AUTOINCREMENT,created_at TEXT NOT NULL,severity TEXT NOT NULL,event_type TEXT NOT NULL,account_key TEXT,group_id INTEGER,campaign_id TEXT,message TEXT NOT NULL,details TEXT);
            """)
            now="2026-08-27T07:00:00+00:00"
            con.execute("INSERT INTO content VALUES('legacy','caption','[]',1,?,?)", (now,now))
            con.execute("INSERT INTO campaigns(campaign_id,name,content_id,enabled,priority,target_tags,created_at,updated_at) VALUES('legacy_campaign','Legacy','legacy',1,50,'',?,?)", (now,now))
            con.commit(); con.close()
            db=Database(p); db.init()
            with db.connect() as con:
                cols={r[1] for r in con.execute("PRAGMA table_info(content)")}
                indexes={r[1] for r in con.execute("PRAGMA index_list(content)")}
                camp=con.execute("SELECT enabled,lifecycle_state FROM campaigns WHERE campaign_id='legacy_campaign'").fetchone()
            self.assertIn("fingerprint", cols)
            self.assertIn("idx_content_fingerprint", indexes)
            self.assertEqual(tuple(camp), (1, "active"))

    def test_legacy_destination_columns_are_not_lost_by_duplicate_migration_keys(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "legacy_dest.sqlite3"
            con = sqlite3.connect(p)
            con.executescript("""
                CREATE TABLE destinations(group_id INTEGER PRIMARY KEY,group_name TEXT NOT NULL,primary_access INTEGER NOT NULL DEFAULT 0,secondary_access INTEGER NOT NULL DEFAULT 0,preferred_account TEXT NOT NULL DEFAULT 'primary',mode TEXT NOT NULL DEFAULT 'review',enabled INTEGER NOT NULL DEFAULT 0,needs_review INTEGER NOT NULL DEFAULT 1,updated_at TEXT NOT NULL);
                CREATE TABLE queue(id INTEGER PRIMARY KEY,job_key TEXT UNIQUE,campaign_id TEXT,group_id INTEGER,account_key TEXT,due_at TEXT,status TEXT,attempts INTEGER,max_attempts INTEGER,last_error TEXT,telegram_message_ids TEXT,created_at TEXT,updated_at TEXT);
                CREATE TABLE accounts(account_key TEXT PRIMARY KEY,session_name TEXT NOT NULL,enabled INTEGER NOT NULL DEFAULT 1,authorized INTEGER,identity TEXT,cooldown_until TEXT,consecutive_failures INTEGER NOT NULL DEFAULT 0,last_error TEXT,updated_at TEXT NOT NULL);
            """)
            con.commit(); con.close()
            Database(p).init()
            con=sqlite3.connect(p)
            cols={r[1] for r in con.execute("PRAGMA table_info(destinations)")}
            con.close()
            self.assertTrue({'protected','never_auto_post','last_seen_at','text_allowed','photo_allowed','capability_source','capability_updated_at'} <= cols)


if __name__ == "__main__":
    unittest.main()
