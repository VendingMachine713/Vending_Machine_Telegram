import json
import tempfile
import unittest
from pathlib import Path

from shared.vm_core.manifests import discover_bots, refresh_bot_manifests
from shared.vm_core.health import run_health
from shared.vm_core.doctor import run_doctor
from shared.vm_core.duplicates import analyze_nested_duplicates

class V11HardeningTests(unittest.TestCase):
    def test_placeholder_is_planned_not_degraded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); bot=root/"bots"/"Planned"; bot.mkdir(parents=True)
            (bot/".gitkeep").write_text("")
            found=discover_bots(root)
            self.assertEqual(found[0].classification,"PLACEHOLDER")
            health=run_health(root)
            self.assertEqual(health[0]["status"],"PLANNED")
            doctor=run_doctor(root)
            self.assertFalse(any(c["status"]=="WARN" and "Planned:entrypoint" in c["name"] for c in doctor["checks"]))

    def test_refresh_manifest_preserves_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); bot=root/"bots"/"Demo"; bot.mkdir(parents=True)
            (bot/"main.py").write_text("print('x')")
            (bot/"BOT_MANIFEST.json").write_text(json.dumps({
                "schema_version":2,
                "lifecycle":{"managed_by_vm":True,"auto_start":True,"auto_restart":True},
                "custom":{"keep":123}
            }))
            refresh_bot_manifests(root,write=True)
            data=json.loads((bot/"BOT_MANIFEST.json").read_text())
            self.assertTrue(data["lifecycle"]["auto_restart"])
            self.assertEqual(data["custom"]["keep"],123)
            self.assertEqual(data["classification"],"CANONICAL")

    def test_doctor_names_invalid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/"bots"/"Planned").mkdir(parents=True)
            bad=root/"config"; bad.mkdir(); (bad/"broken.json").write_text("{oops")
            report=run_doctor(root)
            self.assertEqual(report["invalid_json_files"][0]["path"],"config/broken.json")

    def test_duplicate_analysis_detects_different_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); outer=root/"bots"/"Demo"; nested=outer/"Demo"; nested.mkdir(parents=True)
            (outer/"main.py").write_text("root")
            (nested/"main.py").write_text("nested")
            report=analyze_nested_duplicates(root)
            self.assertEqual(report["bots"][0]["summary"]["DIFFERENT"],1)
            self.assertFalse(report["bots"][0]["safe_exact_duplicate_only"])
