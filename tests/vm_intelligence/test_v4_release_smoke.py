from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from shared.vm_intelligence.store import IntelligenceStore
from shared.vm_intelligence.reporting import build_report, write_report
from shared.vm_intelligence.doctor import run_doctor


class V4ReleaseSmokeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        for d in ("bots","shared","diagnostics","state","backups","config"):
            (self.root/d).mkdir(parents=True,exist_ok=True)
        self.store=IntelligenceStore(self.root/"state"/"vm_intelligence.sqlite3")
        # Minimal managed bot topology for registry/architecture surfaces.
        for name in ("Admin_Command_Centre","VM_Guard"):
            bot=self.root/"bots"/name;runtime=bot/name/name;runtime.mkdir(parents=True)
            (runtime/"main.py").write_text("print('ok')\n",encoding="utf-8")
            (runtime/"BOT_MANIFEST.json").write_text(json.dumps({
                "name":name,"classification":"CANONICAL","entrypoint":"main.py","entrypoint_confidence":"high",
                "lifecycle":{"auto_start":True,"auto_restart":True},"version":"1.0"
            }),encoding="utf-8")
        (self.root/"diagnostics"/"live_runtime.json").write_text(json.dumps({
            "services":[
                {"name":"Admin_Command_Centre","process_alive":True,"runtime_status":"RUNNING"},
                {"name":"VM_Guard","process_alive":True,"runtime_status":"RUNNING"},
            ],"components":{},"open_alerts":[]
        }),encoding="utf-8")
        (self.root/"diagnostics"/"full_validation.json").write_text(json.dumps({
            "critical_tests_ok":True,"all_test_suites_ok":True,"preflight_ok":True,"bots_runnable":2,
            "failed_test_suites":[],"supervisor_actions":[]
        }),encoding="utf-8")
        (self.root/"config"/"vm_intelligence.json").write_text("{}",encoding="utf-8")
        # Installed-mode doctor surfaces.
        (self.root/"state"/"vm_intelligence_release.json").write_text(json.dumps({"version":"6.0.0"}),encoding="utf-8")
        (self.root/"state"/"runtime_bridge.json").write_text(json.dumps({"services":[]}),encoding="utf-8")
        admin=self.root/"bots"/"Admin_Command_Centre"/"admin_core.py"
        admin.write_text("# VM_INTELLIGENCE_V3_DISPATCH_BEGIN\n",encoding="utf-8")

    def tearDown(self):self.tmp.cleanup()

    def test_report_writes_v4_artifacts_and_doctor_accepts_schema(self):
        report=build_report(self.store,hours=24,root=self.root)
        self.assertEqual(report["schema_version"],12)
        for key in ("runtime_registry","platform_normalization","reliability","objectives","autonomy","dependency_graph","attention_budget"):
            self.assertIn(key,report)
        write_report(report,self.root/"diagnostics")
        for name in (
            "intelligence_runtime_registry.json","intelligence_platform_normalization.json",
            "intelligence_reliability.json","intelligence_objectives.json","intelligence_autonomy.json",
            "intelligence_dependency_graph.json","intelligence_attention_budget.json","intelligence_release_gate.json",
        ):
            self.assertTrue((self.root/"diagnostics"/name).is_file(),name)
        with self.store.connect() as con:
            self.assertEqual(con.execute("PRAGMA quick_check").fetchone()[0],"ok")
            self.assertEqual(con.execute("SELECT value FROM intelligence_meta WHERE key='schema_version'").fetchone()[0],"12")
        # Doctor requires a recorded healthy cycle in installed mode.
        from datetime import datetime,timezone
        now=datetime.now(timezone.utc).isoformat()
        with self.store.connect() as con:
            con.execute("""INSERT INTO intelligence_cycles(started_at_utc,completed_at_utc,duration_ms,ingested_events,metric_sources,incident_count,action_count,status,details_json)
                VALUES(?,?,?,?,?,?,?,?,?)""",(now,now,1,0,2,0,0,"ok","{}"))
        doctor=run_doctor(self.root)
        self.assertTrue(doctor["ok"],doctor)


if __name__=="__main__":unittest.main()
