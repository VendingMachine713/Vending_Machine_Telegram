import tempfile,unittest,json,os
from pathlib import Path
from shared.vm_core.db import PlatformDB
from shared.vm_core.search_index import SearchIndex
from shared.vm_core.admins import add_admin_id,load_admin_ids
from shared.vm_core.duplicates import build_safe_text_diff
from shared.vm_core.services import start_service,stop_service
from shared.vm_core.checks import run_all_tests

class V13OperationsTests(unittest.TestCase):
    def test_alert_resolves_when_condition_clears(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/"bots").mkdir()
            db=PlatformDB(root=root); db.init()
            db.upsert_alert("x","WARN","VM_Guard","x","x")
            self.assertEqual(len(db.alerts()),1)
            db.resolve_alerts_except("VM_Guard",set())
            self.assertEqual(len(db.alerts()),0)

    def test_shared_admin_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            add_admin_id(123,root)
            self.assertEqual(load_admin_ids(root),{123})

    def test_search_index_platform_events_closes_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/"bots").mkdir()
            db=PlatformDB(root=root); db.init()
            db.add_event("campaign.sent","test",{"message":"hello search world"})
            idx=SearchIndex(root); idx.rebuild()
            self.assertTrue(idx.search("hello"))
            # If SearchIndex leaked a Windows handle, TemporaryDirectory cleanup fails.

    def test_background_start_prevents_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); bot=root/"bots"/"Worker"; bot.mkdir(parents=True)
            (bot/"main.py").write_text("import time\ntime.sleep(30)\n",encoding="utf-8")
            (bot/"BOT_MANIFEST.json").write_text(json.dumps({
                "schema_version":3,"name":"Worker","entrypoint":"main.py",
                "runtime_requirements":{"env":[]},
                "lifecycle":{"auto_start":True,"auto_restart":True}
            }),encoding="utf-8")
            first=start_service("Worker",root,dry_run=False,background=True)
            try:
                self.assertTrue(first["ok"],first)
                second=start_service("Worker",root,dry_run=False,background=True)
                self.assertTrue(second.get("already_running"),second)
                self.assertEqual(first["pid"],second["pid"])
            finally:
                stop_service("Worker",root,dry_run=False)

    def test_bot_suite_runs_from_bot_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/"tests").mkdir(parents=True)
            (root/"tests"/"test_platform.py").write_text(
                "import unittest\nclass T(unittest.TestCase):\n def test_ok(self): self.assertTrue(True)\n",
                encoding="utf-8"
            )
            bot=root/"bots"/"LocalBot"; (bot/"tests").mkdir(parents=True)
            (bot/"main.py").write_text("print('x')\n",encoding="utf-8")
            (bot/"core.py").write_text("VALUE=42\n",encoding="utf-8")
            (bot/"tests"/"test_core.py").write_text(
                "import unittest\nfrom core import VALUE\nclass T(unittest.TestCase):\n def test_value(self): self.assertEqual(VALUE,42)\n",
                encoding="utf-8"
            )
            result=run_all_tests(root)
            self.assertTrue(result["ok"],result)

    def test_duplicate_diff_excludes_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); outer=root/"bots"/"Demo"; nested=outer/"Demo"; nested.mkdir(parents=True)
            (outer/"main.py").write_text("x=1\n")
            (nested/"main.py").write_text("x=2\n")
            (outer/".env").write_text("BOT_TOKEN=outersecret\n")
            (nested/".env").write_text("BOT_TOKEN=nestedsecret\n")
            diff=build_safe_text_diff(root)
            self.assertIn("main.py",diff)
            self.assertNotIn("outersecret",diff)
            self.assertNotIn("nestedsecret",diff)
