from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest

from shared.vm_core.db import PlatformDB
from shared.vm_core.fleet_heartbeat import fleet_heartbeat_snapshot
from shared.vm_core.publisher import BotEventPublisher


class FleetHeartbeatTests(unittest.TestCase):
    def _guard_root(self, td: str) -> Path:
        root = Path(td)
        bot = root / "bots" / "VM_Guard"
        bot.mkdir(parents=True)
        (bot / "main.py").write_text(
            "from shared.vm_core.publisher import BotEventPublisher\n"
            "publisher = BotEventPublisher('VM_Guard', ROOT)\n"
            "publisher.started()\n",
            encoding="utf-8",
        )
        (bot / "START.ps1").write_text("python main.py\n", encoding="utf-8")
        (bot / "BOT_MANIFEST.json").write_text(
            json.dumps(
                {
                    "schema_version": 3,
                    "name": "VM_Guard",
                    "version": "1.0.0",
                    "classification": "CANONICAL",
                    "entrypoint": "main.py",
                    "entrypoint_confidence": "high",
                    "launchers": ["START.ps1"],
                    "lifecycle": {"managed_by_vm": True, "auto_start": False, "auto_restart": False},
                }
            ),
            encoding="utf-8",
        )
        return root

    def test_publisher_started_inherits_periodic_durable_heartbeat(self) -> None:
        with TemporaryDirectory() as td:
            root = self._guard_root(td)
            publisher = BotEventPublisher("VM_Guard", root, instance_id="test-lease")
            publisher.start_heartbeat_loop(interval_seconds=0.01)
            time.sleep(0.03)
            publisher.stop_heartbeat_loop()
            db = PlatformDB(root=root)
            db.init()
            rows = db.latest_heartbeats()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["service"], "VM_Guard")
        self.assertEqual(rows[0]["instance_id"], "test-lease")

    def test_fleet_snapshot_reports_integration_coverage_without_authority(self) -> None:
        with TemporaryDirectory() as td:
            root = self._guard_root(td)
            snapshot = fleet_heartbeat_snapshot(root)

        self.assertEqual(snapshot["expected_service_count"], 1)
        self.assertEqual(snapshot["integrated_service_count"], 1)
        self.assertEqual(snapshot["integration_coverage_percent"], 100.0)
        self.assertTrue(snapshot["read_only"])
        self.assertFalse(snapshot["automatic_restart"])
        self.assertFalse(snapshot["automatic_execution"])
        self.assertFalse(snapshot["external_action_authority"])

    def test_sustained_missing_heartbeat_becomes_incident_candidate_only(self) -> None:
        with TemporaryDirectory() as td:
            root = self._guard_root(td)
            db = PlatformDB(root=root)
            db.init()
            db.upsert_service("VM_Guard", "VM_Guard", "main.py", "START.ps1")
            db.set_service_runtime("VM_Guard", "RUNNING", 123)
            now = datetime.now(timezone.utc) + timedelta(seconds=700)
            snapshot = fleet_heartbeat_snapshot(root, now=now, stale_seconds=600)

        self.assertEqual(snapshot["incident_candidate_count"], 1)
        candidate = snapshot["incident_candidates"][0]
        self.assertEqual(candidate["incident_type"], "service_heartbeat_missing")
        self.assertEqual(candidate["subject_id"], "VM_Guard")
        self.assertTrue(snapshot["read_only"])

    def test_stale_heartbeat_synthesizes_stale_candidate(self) -> None:
        with TemporaryDirectory() as td:
            root = self._guard_root(td)
            db = PlatformDB(root=root)
            db.init()
            db.upsert_service("VM_Guard", "VM_Guard", "main.py", "START.ps1")
            db.set_service_runtime("VM_Guard", "RUNNING", 123)
            now = datetime(2026, 9, 5, 0, 20, tzinfo=timezone.utc)
            db.record_heartbeat(
                "VM_Guard",
                "guard-1",
                "healthy",
                observed_at_utc=(now - timedelta(seconds=700)).isoformat(),
            )
            snapshot = fleet_heartbeat_snapshot(root, now=now, stale_seconds=600)

        self.assertEqual(snapshot["incident_candidate_count"], 1)
        self.assertEqual(snapshot["incident_candidates"][0]["incident_type"], "service_heartbeat_stale")


if __name__ == "__main__":
    unittest.main()
