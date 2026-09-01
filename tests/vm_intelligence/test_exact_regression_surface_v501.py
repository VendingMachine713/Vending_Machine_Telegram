from __future__ import annotations
import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path

class ExactRegressionSurfaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)/"project"
        (self.root/"shared"/"vm_core").mkdir(parents=True)
        (self.root/"shared"/"__init__.py").write_text("",encoding="utf-8")
        (self.root/"shared"/"vm_core"/"__init__.py").write_text("",encoding="utf-8")
        self.suite=self.root/"bots"/"Demo";self.tests=self.suite/"tests";self.tests.mkdir(parents=True)
        (self.tests/"test_demo.py").write_text(
            "import unittest\nclass T(unittest.TestCase):\n"
            " def test_one(self): self.assertTrue(True)\n"
            " def test_two(self): self.assertEqual(1,1)\n",encoding="utf-8")
        self.runner=Path(__file__).resolve().parents[2]/"tools"/"Intelligence"/"RUN_TEST_SUITE.py"

    def tearDown(self):self.tmp.cleanup()

    def test_runner_emits_exact_machine_readable_test_ids(self):
        out=self.root/"result.json"
        r=subprocess.run([sys.executable,str(self.runner),"--root",str(self.root),
            "--suite-root",str(self.suite),"--test-dir",str(self.tests),"--bot-root",str(self.suite),
            "--result-json",str(out)],capture_output=True,text=True)
        self.assertEqual(r.returncode,0,r.stderr)
        data=json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(data["test_count_discovered"],2)
        self.assertEqual(data["tests_run"],2)
        self.assertEqual(len(data["test_ids"]),2)
        self.assertTrue(any(x.endswith("T.test_one") for x in data["test_ids"]))
        self.assertTrue(any(x.endswith("T.test_two") for x in data["test_ids"]))
        self.assertEqual(data["failed_test_ids"],[])
        self.assertEqual(data["error_test_ids"],[])

    def test_project_regression_contract_fails_closed_on_test_surface_change(self):
        ps=(Path(__file__).resolve().parents[2]/"tools"/"Intelligence"/"RUN_PROJECT_REGRESSION.ps1").read_text(encoding="utf-8")
        for token in ("test_ids_added","test_ids_removed","test_surface_changed_suites",
                      "stable_test_surface","exit 3","--result-json"):
            self.assertIn(token,ps)

if __name__=="__main__":unittest.main()
