import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from shared.vm_core.heartbeat import record_heartbeat
from shared.vm_core.watchdog import watchdog_snapshot


class WatchdogTests(unittest.TestCase):
    def _root(self, tmp: str) -> Path:
        root = Path(tmp)
        bot = root / "bots" / "Demo"
        bot.mkdir(parents=True)
        (bot / "main.py").write_text("x=1\n", encoding="utf-8")
        (bot / "BOT_MANIFEST.json").write_text(json.dumps({
            "schema_version": 3,
            "name": "Demo",
            "version": "1.0.0",
            "classification": "CANONICAL",
            "entrypoint": "main.py",
            "launchers": [],
            "runtime_requirements": {},
            "vm_core": {"compatible": True},
            "lifecycle": {"managed_by_vm": True, "auto_start": False, "auto_restart": False},
        }), encoding="utf-8")
        return root

    @patch("shared.vm_core.watchdog.health_snapshot")
    @patch("shared.vm_core.watchdog.service_status")
    def test_missing_heartbeat_is_degraded_for_live_process(self, status, health):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            status.return_value = [{"name": "Demo", "process_alive": True, "runtime_status": "RUNNING"}]
            health.return_value = {"services": [{"service": "Demo", "status": "HEALTHY"}]}
            snap = watchdog_snapshot(root)
            item = snap["services"][0]
            self.assertEqual(item["state"], "DEGRADED")
            self.assertEqual(item["findings"][0]["code"], "HEARTBEAT_MISSING")

    @patch("shared.vm_core.watchdog.health_snapshot")
    @patch("shared.vm_core.watchdog.service_status")
    def test_expired_heartbeat_requires_attention(self, status, health):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            now = datetime(2026, 9, 4, tzinfo=timezone.utc)
            record_heartbeat("Demo", "i1", observed_at_utc=(now - timedelta(seconds=400)).isoformat(), root=root)
            status.return_value = [{"name": "Demo", "process_alive": True, "runtime_status": "RUNNING"}]
            health.return_value = {"services": [{"service": "Demo", "status": "HEALTHY"}]}
            snap = watchdog_snapshot(root, now=now)
            self.assertEqual(snap["services"][0]["state"], "ATTENTION_REQUIRED")


if __name__ == "__main__":
    unittest.main()
