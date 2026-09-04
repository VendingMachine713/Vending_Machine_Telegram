from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from shared.vm_core.db import PlatformDB
from shared.vm_core.service_telemetry import service_telemetry_snapshot


class ServiceTelemetryTests(unittest.TestCase):
    def _root(self, service: str = "VM_Guard"):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        bot = root / "bots" / service
        bot.mkdir(parents=True)
        (bot / "main.py").write_text("print('ok')\n", encoding="utf-8")
        (bot / "START.ps1").write_text("python main.py\n", encoding="utf-8")
        (bot / "BOT_MANIFEST.json").write_text(
            json.dumps(
                {
                    "schema_version": 3,
                    "name": service,
                    "version": "1.0.0",
                    "classification": "CANONICAL",
                    "entrypoint": "main.py",
                    "entrypoint_confidence": "high",
                    "launchers": ["START.ps1"],
                    "lifecycle": {
                        "managed_by_vm": True,
                        "auto_start": False,
                        "auto_restart": False,
                    },
                }
            ),
            encoding="utf-8",
        )
        return temp, root

    def test_running_service_with_fresh_heartbeat_is_healthy(self):
        temp, root = self._root()
        self.addCleanup(temp.cleanup)
        db = PlatformDB(root=root)
        db.init()
        db.upsert_service("VM_Guard", "VM_Guard", "main.py", "START.ps1")
        db.set_service_runtime("VM_Guard", "RUNNING", 123)
        db.record_heartbeat(
            "VM_Guard",
            "guard-1",
            "RUNNING",
            counters={"events": 9},
            last_success_utc="2026-09-05T00:09:30+00:00",
            observed_at_utc="2026-09-05T00:09:30+00:00",
        )
        result = service_telemetry_snapshot(
            root,
            now=datetime(2026, 9, 5, 0, 10, tzinfo=timezone.utc),
        )
        self.assertEqual(result["status"], "HEALTHY")
        self.assertEqual(result["fresh_running_count"], 1)
        row = result["services"][0]
        self.assertEqual(row["freshness"], "FRESH")
        self.assertEqual(row["heartbeat_age_seconds"], 30)
        self.assertEqual(row["counters"], {"events": 9})
        self.assertTrue(row["adapter_supported"])

    def test_running_service_with_stale_heartbeat_needs_attention(self):
        temp, root = self._root()
        self.addCleanup(temp.cleanup)
        db = PlatformDB(root=root)
        db.init()
        db.upsert_service("VM_Guard", "VM_Guard", "main.py", "START.ps1")
        db.set_service_runtime("VM_Guard", "RUNNING", 123)
        db.record_heartbeat(
            "VM_Guard",
            "guard-1",
            "RUNNING",
            observed_at_utc="2026-09-05T00:00:00+00:00",
        )
        result = service_telemetry_snapshot(
            root,
            now=datetime(2026, 9, 5, 0, 11, tzinfo=timezone.utc),
        )
        self.assertEqual(result["status"], "ATTENTION")
        self.assertEqual(result["stale_running_heartbeat_count"], 1)
        self.assertEqual(result["attention_services"][0]["freshness"], "STALE")

    def test_missing_heartbeat_is_attention_only_when_runtime_is_running(self):
        temp, root = self._root()
        self.addCleanup(temp.cleanup)
        db = PlatformDB(root=root)
        db.init()
        db.upsert_service("VM_Guard", "VM_Guard", "main.py", "START.ps1")
        result = service_telemetry_snapshot(
            root,
            now=datetime(2026, 9, 5, 0, 10, tzinfo=timezone.utc),
        )
        self.assertEqual(result["status"], "IDLE")
        self.assertEqual(result["services"][0]["freshness"], "NOT_EXPECTED")

        db.set_service_runtime("VM_Guard", "RUNNING", 123)
        result = service_telemetry_snapshot(
            root,
            now=datetime(2026, 9, 5, 0, 10, tzinfo=timezone.utc),
        )
        self.assertEqual(result["status"], "ATTENTION")
        self.assertEqual(result["missing_running_heartbeat_count"], 1)
        self.assertEqual(result["services"][0]["freshness"], "MISSING")


if __name__ == "__main__":
    unittest.main()
