import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shared.vm_core.health_engine import health_snapshot


class UniversalHealthEngineTests(unittest.TestCase):
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
        db = bot / "demo.sqlite3"
        con = sqlite3.connect(db)
        con.execute("create table t(id integer primary key)")
        con.commit()
        con.close()
        return root

    @patch("shared.vm_core.health_engine.service_status")
    def test_running_clean_service_is_healthy(self, status):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            status.return_value = [{
                "name": "Demo", "runtime_status": "RUNNING", "process_alive": True, "pid": 111
            }]
            report = health_snapshot(root)
            self.assertEqual(report["status"], "HEALTHY")
            self.assertEqual(report["services"][0]["status"], "HEALTHY")

    @patch("shared.vm_core.health_engine.service_status")
    def test_stopped_service_is_degraded_not_attention(self, status):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            status.return_value = [{
                "name": "Demo", "runtime_status": "STOPPED", "process_alive": False, "pid": None
            }]
            report = health_snapshot(root)
            self.assertEqual(report["status"], "DEGRADED")
            self.assertEqual(report["services"][0]["status"], "DEGRADED")

    @patch("shared.vm_core.health_engine.service_status")
    def test_missing_required_configuration_requires_attention(self, status):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            manifest = root / "bots" / "Demo" / "BOT_MANIFEST.json"
            data = json.loads(manifest.read_text(encoding="utf-8"))
            data["runtime_requirements"] = {"env": ["BOT_TOKEN"]}
            manifest.write_text(json.dumps(data), encoding="utf-8")
            status.return_value = [{
                "name": "Demo", "runtime_status": "RUNNING", "process_alive": True, "pid": 111
            }]
            with patch.dict("os.environ", {}, clear=True):
                report = health_snapshot(root)
            self.assertEqual(report["status"], "ATTENTION_REQUIRED")


if __name__ == "__main__":
    unittest.main()
