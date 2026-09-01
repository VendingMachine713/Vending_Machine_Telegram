import json
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from shared.vm_core.git_audit import audit as git_audit
from shared.vm_core.runtime_snapshot import verify as runtime_verify
from shared.vm_core.child_supervisor import LegacyChildSupervisor
from shared.vm_core.components import write_component

class V14OperationalHardeningTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("git"), "git not installed")
    def test_git_audit_detects_tracked_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/"bots").mkdir()
            subprocess.run(["git","init","-q"],cwd=root,check=True)
            (root/".env").write_text("BOT_TOKEN=secret\n",encoding="utf-8")
            subprocess.run(["git","add","-f",".env"],cwd=root,check=True)
            result=git_audit(root)
            self.assertFalse(result["ok"])
            self.assertTrue(any(x["severity"]=="CRITICAL" for x in result["findings"]))
            self.assertNotIn("secret",json.dumps(result))

    def test_runtime_check_requires_managed_component_heartbeat(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); bot=root/"bots"/"Universal_Search"; bot.mkdir(parents=True)
            (bot/"main.py").write_text("print('x')\n")
            (bot/"BOT_MANIFEST.json").write_text(json.dumps({
                "schema_version":3,"name":"Universal_Search","entrypoint":"main.py",
                "runtime_requirements":{"env":[]},
                "lifecycle":{"auto_start":True,"auto_restart":True}
            }))
            result=runtime_verify(root)
            self.assertFalse(result["ok"])
            self.assertTrue(any("heartbeat missing" in x for x in result["failures"]))

    def test_runtime_check_flags_missing_legacy_entrypoint_when_evidence_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); bot=root/"bots"/"Universal_Search"; bot.mkdir(parents=True)
            (bot/"main.py").write_text("print('wrapper')\n")
            (bot/"core.py").write_text("VALUE=1\n")
            (bot/"BOT_MANIFEST.json").write_text(json.dumps({
                "schema_version":3,"name":"Universal_Search","entrypoint":"main.py",
                "runtime_requirements":{"env":[]},
                "lifecycle":{"auto_start":False,"auto_restart":False}
            }))
            result=runtime_verify(root,require_legacy_components=True)
            self.assertFalse(result["ok"])
            self.assertTrue(any("entrypoint missing" in x for x in result["failures"]))

    def test_legacy_child_supervisor_starts_and_stops_dummy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); bot=root/"bots"/"Demo"; bot.mkdir(parents=True)
            (root/"logs").mkdir()
            (bot/"legacy_main.py").write_text("import time\ntime.sleep(30)\n",encoding="utf-8")
            sup=LegacyChildSupervisor(bot,"Demo",root)
            state=sup.tick()
            try:
                self.assertTrue(state["available"])
                self.assertTrue(state["alive"])
            finally:
                sup.stop()
            self.assertTrue(sup.proc is None)

if __name__=="__main__":
    unittest.main()
