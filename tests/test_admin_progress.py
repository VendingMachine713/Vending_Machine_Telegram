from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sqlite3
import tempfile
import unittest
from pathlib import Path

from shared.vm_core.admin_progress import admin_command_centre_progress


class AdminProgressTests(unittest.TestCase):
    def _root(self, status="RUNNING", age_seconds=0):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        state = root / "state"; state.mkdir(parents=True)
        db = state / "vm_platform.sqlite3"
        con = sqlite3.connect(db)
        con.executescript(
            """
            CREATE TABLE services(name TEXT PRIMARY KEY,runtime_status TEXT,pid INTEGER,last_error TEXT,updated_at_utc TEXT);
            CREATE TABLE events(id INTEGER PRIMARY KEY,event_type TEXT,source TEXT,payload_json TEXT,created_at_utc TEXT,severity TEXT);
            """
        )
        updated = (datetime.now(timezone.utc)-timedelta(seconds=age_seconds)).isoformat()
        con.execute("INSERT INTO services VALUES(?,?,?,?,?)",("Admin_Command_Centre",status,1234,None,updated))
        con.execute("INSERT INTO events VALUES(1,'service.started','Admin_Command_Centre','{}',?,'INFO')",(updated,))
        con.commit(); con.close()
        return tmp, root

    def test_running_admin_surface_reports_ready(self):
        tmp, root = self._root(); self.addCleanup(tmp.cleanup)
        snapshot = admin_command_centre_progress(root)
        self.assertEqual(snapshot["headline"], "ADMIN COMMAND CENTRE - UNIVERSAL PROGRESS")
        self.assertEqual(snapshot["overall"]["percent"], 100)
        self.assertEqual(snapshot["overall"]["status"], "RUNNING")
        self.assertEqual(snapshot["services"][0]["status"], "HEALTHY")
        self.assertEqual(snapshot["metrics"]["recent_events"], 1)

    def test_stale_admin_runtime_reports_attention(self):
        tmp, root = self._root(age_seconds=900); self.addCleanup(tmp.cleanup)
        snapshot = admin_command_centre_progress(root)
        self.assertEqual(snapshot["overall"]["status"], "ATTENTION")
        self.assertEqual(snapshot["overall"]["percent"], 0)
        self.assertEqual(snapshot["services"][0]["status"], "DEGRADED")
        self.assertTrue(any("stale" in item.lower() for item in snapshot["recovery_messages"]))

    def test_missing_platform_database_degrades_safely(self):
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = admin_command_centre_progress(Path(tmp))
        self.assertEqual(snapshot["overall"]["status"], "DEGRADED")
        self.assertTrue(snapshot["recovery_messages"])


if __name__ == "__main__":
    unittest.main()
