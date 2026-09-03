from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from shared.vm_core.guard_progress import vm_guard_progress


class GuardProgressTests(unittest.TestCase):
    def _root(self, *, runtime_status: str = "RUNNING", age_seconds: int = 0):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        guard_state = root / "bots" / "VM_Guard" / "state"
        guard_state.mkdir(parents=True)
        (guard_state / "config.json").write_text(
            json.dumps({"mutations_enabled": False, "risk_threshold": 65, "flood_delete": False}),
            encoding="utf-8",
        )
        state = root / "state"
        state.mkdir(parents=True)
        db = state / "vm_platform.sqlite3"
        con = sqlite3.connect(db)
        con.executescript(
            """
            CREATE TABLE services(
                name TEXT PRIMARY KEY,
                runtime_status TEXT,
                pid INTEGER,
                last_error TEXT,
                updated_at_utc TEXT
            );
            CREATE TABLE events(
                id INTEGER PRIMARY KEY,
                event_type TEXT,
                source TEXT,
                payload_json TEXT,
                created_at_utc TEXT,
                severity TEXT
            );
            """
        )
        updated = (datetime.now(timezone.utc) - timedelta(seconds=age_seconds)).isoformat()
        con.execute(
            "INSERT INTO services VALUES(?,?,?,?,?)",
            ("VM_Guard", runtime_status, 4321, None, updated),
        )
        con.execute(
            "INSERT INTO events VALUES(1,'signal.guard_risk_elevated','VM_Guard',?,?,'WARN')",
            (json.dumps({"rationale": "risk threshold exceeded"}), updated),
        )
        con.commit()
        con.close()
        return tmp, root

    def test_running_monitor_mode_reports_ready_and_recent_event(self):
        tmp, root = self._root()
        self.addCleanup(tmp.cleanup)
        snapshot = vm_guard_progress(root)
        self.assertEqual(snapshot["headline"], "VM GUARD - UNIVERSAL PROGRESS")
        self.assertEqual(snapshot["overall"]["percent"], 100)
        self.assertEqual(snapshot["overall"]["status"], "RUNNING")
        self.assertEqual(snapshot["metrics"]["mode"], "MONITOR ONLY")
        self.assertEqual(snapshot["metrics"]["risk_threshold"], 65)
        self.assertEqual(snapshot["metrics"]["recent_events"], 1)
        self.assertEqual(snapshot["services"][0]["status"], "HEALTHY")
        self.assertIn("risk threshold exceeded", snapshot["events"][0]["message"])

    def test_stale_runtime_evidence_reports_attention_without_mutating_state(self):
        tmp, root = self._root(age_seconds=900)
        self.addCleanup(tmp.cleanup)
        config_before = (root / "bots" / "VM_Guard" / "state" / "config.json").read_text(encoding="utf-8")
        snapshot = vm_guard_progress(root)
        config_after = (root / "bots" / "VM_Guard" / "state" / "config.json").read_text(encoding="utf-8")
        self.assertEqual(snapshot["overall"]["status"], "ATTENTION")
        self.assertEqual(snapshot["overall"]["percent"], 0)
        self.assertEqual(snapshot["services"][0]["status"], "DEGRADED")
        self.assertTrue(any("stale" in message.lower() for message in snapshot["recovery_messages"]))
        self.assertEqual(config_before, config_after)

    def test_missing_platform_database_degrades_safely(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot = vm_guard_progress(root)
        self.assertEqual(snapshot["overall"]["status"], "DEGRADED")
        self.assertEqual(snapshot["overall"]["percent"], 0)
        self.assertTrue(snapshot["recovery_messages"])


if __name__ == "__main__":
    unittest.main()
