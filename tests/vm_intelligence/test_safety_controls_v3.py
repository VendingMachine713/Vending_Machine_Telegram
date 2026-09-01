import json,sys,tempfile,types,unittest
from pathlib import Path

from shared.vm_intelligence.store import IntelligenceStore
from shared.vm_intelligence.integrated_schema import ensure_v3_schema
from shared.vm_intelligence.self_heal import SelfHealingController
from shared.vm_intelligence.rootcause import RootCauseEngine
from shared.vm_intelligence.admin_commands import handle_intelligence_command

class SafetyControlV3Tests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory()
        self.root=Path(self.t.name)
        (self.root/"bots").mkdir()
        (self.root/"shared").mkdir()
        (self.root/"diagnostics").mkdir()
        self.store=IntelligenceStore(self.root/"state"/"vm_intelligence.sqlite3")
        ensure_v3_schema(self.store)

    def tearDown(self):
        self.t.cleanup()

    def _manifest(self,name,auto_restart):
        bot=self.root/"bots"/name
        bot.mkdir(parents=True,exist_ok=True)
        (bot/"main.py").write_text("print('ok')\n",encoding="utf-8")
        (bot/"BOT_MANIFEST.json").write_text(json.dumps({
            "name":name,"version":"1.0","entrypoint":"main.py",
            "entrypoint_confidence":"high","classification":"CANONICAL",
            "lifecycle":{"auto_start":bool(auto_restart),"auto_restart":bool(auto_restart)}
        }),encoding="utf-8")

    def _runtime(self,rows):
        (self.root/"diagnostics"/"live_runtime.json").write_text(json.dumps({"services":rows}),encoding="utf-8")

    def test_self_heal_never_restarts_non_managed_service(self):
        self._manifest("Smart_Auto_Poster_V2",False)
        self._runtime([{"name":"Smart_Auto_Poster_V2","process_alive":False}])
        called=[]
        vm_core=types.ModuleType("shared.vm_core")
        supervisor=types.ModuleType("shared.vm_core.supervisor")
        supervisor.supervise_once=lambda *a,**k: called.append(True)
        old_core=sys.modules.get("shared.vm_core");old_super=sys.modules.get("shared.vm_core.supervisor")
        sys.modules["shared.vm_core"]=vm_core;sys.modules["shared.vm_core.supervisor"]=supervisor
        try:
            self.assertEqual(SelfHealingController(self.store,self.root).run(),[])
            self.assertEqual(called,[])
        finally:
            if old_core is None:sys.modules.pop("shared.vm_core",None)
            else:sys.modules["shared.vm_core"]=old_core
            if old_super is None:sys.modules.pop("shared.vm_core.supervisor",None)
            else:sys.modules["shared.vm_core.supervisor"]=old_super

    def test_self_heal_executes_only_managed_recovery_and_cooldown_blocks_repeat(self):
        self._manifest("Admin_Command_Centre",True)
        self._runtime([{"name":"Admin_Command_Centre","process_alive":False}])
        calls=[]
        vm_core=types.ModuleType("shared.vm_core")
        supervisor=types.ModuleType("shared.vm_core.supervisor")
        supervisor.supervise_once=lambda root,apply=True: calls.append((str(root),apply)) or {"restarted":["Admin_Command_Centre"]}
        old_core=sys.modules.get("shared.vm_core");old_super=sys.modules.get("shared.vm_core.supervisor")
        sys.modules["shared.vm_core"]=vm_core;sys.modules["shared.vm_core.supervisor"]=supervisor
        try:
            first=SelfHealingController(self.store,self.root).run()
            second=SelfHealingController(self.store,self.root).run()
            self.assertEqual(first[0]["outcome"],"executed")
            self.assertEqual(first[0]["down"],["Admin_Command_Centre"])
            self.assertEqual(second,[])
            self.assertEqual(len(calls),1)
            with self.store.connect() as con:
                row=con.execute("SELECT authority,outcome FROM decisions ORDER BY decision_id DESC LIMIT 1").fetchone()
            self.assertEqual(row["authority"],"automatic")
            self.assertEqual(row["outcome"],"executed")
        finally:
            if old_core is None:sys.modules.pop("shared.vm_core",None)
            else:sys.modules["shared.vm_core"]=old_core
            if old_super is None:sys.modules.pop("shared.vm_core.supervisor",None)
            else:sys.modules["shared.vm_core.supervisor"]=old_super

    def test_root_cause_classifies_uncertain_delivery(self):
        inc={"incident_id":7,"source":"Smart_Auto_Poster_V2","category":"uncertain_delivery","evidence_json":"{}"}
        confidence,cause,evidence=RootCauseEngine(self.store)._derive(inc,{})
        self.assertGreaterEqual(confidence,.9)
        self.assertIn("acknowledgement",cause.lower())
        self.assertTrue(any("duplicate" in x.lower() for x in evidence))

    def test_root_cause_uses_failed_suite_evidence(self):
        inc={"incident_id":8,"source":"VM_Platform","category":"critical_test_failure",
             "evidence_json":json.dumps({"failed_test_suites":["Smart_Auto_Poster_V2"]})}
        confidence,cause,evidence=RootCauseEngine(self.store)._derive(inc,{})
        self.assertEqual(confidence,.98)
        self.assertTrue(any("Smart_Auto_Poster_V2" in x for x in evidence))

    def test_admin_feedback_records_only_valid_verdict(self):
        with self.store.connect() as con:
            con.execute("""INSERT INTO incidents(fingerprint,source,category,severity,title,status,
                first_seen_utc,last_seen_utc,occurrences,evidence_json,resolution)
                VALUES('x','A','test','medium','test','open','2026-01-01','2026-01-01',1,'{}','')""")
            incident_id=con.execute("SELECT incident_id FROM incidents WHERE fingerprint='x'").fetchone()[0]
        # Use a cached minimal report so command dispatch does not need a full project scan.
        report={
            "generated_at_utc":"2099-01-01T00:00:00+00:00",
            "scorecard":{"overall":100},"incidents":[],"inbox":[],"security":{"score":100},
            "predictive_maintenance":[],"automation_opportunities":[],"goals":[],
            "meta_intelligence":{"self_health":"healthy"},"cto_priorities":[]
        }
        (self.root/"diagnostics"/"intelligence_report.json").write_text(json.dumps(report),encoding="utf-8")
        bad=handle_intelligence_command("intelfeedback",[str(incident_id),"maybe"],self.root)
        self.assertIn("useful or noise",bad)
        ok=handle_intelligence_command("intelfeedback",[str(incident_id),"useful","correct alert"],self.root)
        self.assertIn("Recorded",ok)
        with self.store.connect() as con:
            row=con.execute("SELECT verdict,details FROM intelligence_feedback WHERE incident_id=?",(incident_id,)).fetchone()
        self.assertEqual(row["verdict"],"useful")
        self.assertEqual(row["details"],"correct alert")

if __name__=="__main__":
    unittest.main()
