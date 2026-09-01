from __future__ import annotations
import json,tempfile,unittest
from pathlib import Path

from shared.vm_intelligence.store import IntelligenceStore
from shared.vm_intelligence.brain import Brain
from shared.vm_intelligence.reporting import build_report,write_report
from shared.vm_intelligence.doctor import run_doctor

class V5ReleaseSmokeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)/"project";self.root.mkdir()
        (self.root/"config").mkdir()
        (self.root/"config"/"vm_intelligence.json").write_text("{}",encoding="utf-8")
        (self.root/"state").mkdir()
        self.store=IntelligenceStore(self.root/"state"/"vm_intelligence.sqlite3")

    def tearDown(self):self.tmp.cleanup()

    def test_report_writes_v5_operating_system_artifacts(self):
        report=build_report(self.store,hours=24,root=self.root)
        self.assertEqual(report["schema_version"],12)
        self.assertEqual(report["strategic_planner_v5"]["planner_level"],7)
        write_report(report,self.root/"diagnostics")
        for name in (
            "intelligence_root_cause_v5.json","intelligence_predictive_v5.json",
            "intelligence_release_intelligence_v5.json","intelligence_automation_discovery_v5.json",
            "intelligence_capability_trust_v5.json","intelligence_engineering_v5.json",
            "intelligence_strategic_planner_v5.json"):
            self.assertTrue((self.root/"diagnostics"/name).is_file(),name)

    def test_doctor_schema_v8_and_v5_surface_gates(self):
        report=build_report(self.store,hours=24,root=self.root)
        write_report(report,self.root/"diagnostics")
        # Source-workspace mode intentionally permits absent installed release/runtime markers.
        result=run_doctor(self.root)
        checks={x["check"]:x for x in result["checks"]}
        self.assertTrue(checks["schema_version"]["ok"])
        self.assertEqual(str(checks["schema_version"]["detail"]),"12")
        self.assertTrue(checks["v5_strategic_planner"]["ok"])
        self.assertTrue(checks["v5_capability_trust"]["ok"])
        self.assertTrue(checks["v5_predictive_ops"]["ok"])

if __name__=="__main__":unittest.main()
