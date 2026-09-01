import json,tempfile,unittest
from pathlib import Path
from datetime import datetime,timezone
from shared.vm_intelligence.store import IntelligenceStore
from shared.vm_intelligence.integrated_schema import ensure_v3_schema
from shared.vm_intelligence.events import Event
from shared.vm_intelligence.maintenance import MaintenanceEngine
from shared.vm_intelligence.admin_commands import _snapshot

class OperationsHardeningTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.root=Path(self.t.name)
        (self.root/"bots").mkdir();(self.root/"shared").mkdir();(self.root/"diagnostics").mkdir();(self.root/"backups").mkdir()
        self.store=IntelligenceStore(self.root/"state"/"vm_intelligence.sqlite3")
    def tearDown(self):self.t.cleanup()

    def test_v2_data_survives_v3_schema_upgrade(self):
        self.store.add_event(Event(source="A",kind="health",action="check",outcome="success"))
        eid=self.store.create_experiment(name="x",source="A",hypothesis="h",metric="m",baseline=1)
        ensure_v3_schema(self.store)
        with self.store.connect() as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM events").fetchone()[0],1)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM experiments WHERE experiment_id=?",(eid,)).fetchone()[0],1)
            self.assertEqual(con.execute("SELECT value FROM intelligence_meta WHERE key='schema_version'").fetchone()[0],"3")

    def test_maintenance_quick_check(self):
        ensure_v3_schema(self.store)
        result=MaintenanceEngine(self.store,self.root).run()
        self.assertTrue(result["intelligence_db_integrity"])
        self.assertIn("history_pruned",result)

    def test_admin_uses_fresh_cached_report(self):
        payload={"generated_at_utc":datetime.now(timezone.utc).isoformat(),"scorecard":{"overall":99}}
        (self.root/"diagnostics"/"intelligence_report.json").write_text(json.dumps(payload),encoding="utf-8")
        got,cached=_snapshot(self.root,max_age_seconds=60)
        self.assertTrue(cached);self.assertEqual(got["scorecard"]["overall"],99)


    def test_intelligence_backup_is_valid_zip(self):
        ensure_v3_schema(self.store)
        from shared.vm_intelligence.backup import backup_intelligence
        import zipfile
        out=backup_intelligence(self.root)
        self.assertTrue(out.is_file())
        with zipfile.ZipFile(out) as z:
            self.assertIsNone(z.testzip())
            self.assertIn("vm_intelligence.sqlite3",z.namelist())
            self.assertIn("manifest.json",z.namelist())


    def test_lifecycle_prefers_runnable_nested_manifest_over_shadow_manifest(self):
        import json
        from shared.vm_intelligence.lifecycle import effective_policy
        outer=self.root/"bots"/"Admin_Command_Centre"
        outer.mkdir(parents=True,exist_ok=True)
        (outer/"BOT_MANIFEST.json").write_text(json.dumps({
            "name":"Admin_Command_Centre","version":"unknown","entrypoint":None,
            "entrypoint_confidence":"none","lifecycle":{"auto_start":False,"auto_restart":False}
        }),encoding="utf-8")
        inner=outer/"Admin_Command_Centre"/"Admin_Command_Centre"
        inner.mkdir(parents=True)
        (inner/"main.py").write_text("print('ok')\n",encoding="utf-8")
        (inner/"BOT_MANIFEST.json").write_text(json.dumps({
            "name":"Admin_Command_Centre","version":"0.4.0","entrypoint":"main.py",
            "entrypoint_confidence":"high","classification":"CANONICAL",
            "lifecycle":{"auto_start":True,"auto_restart":True}
        }),encoding="utf-8")
        policy=effective_policy(self.root,"Admin_Command_Centre")
        self.assertTrue(policy["auto_restart"])
        self.assertTrue(policy["auto_start"])

    def test_custom_goal_reads_latest_native_metric(self):
        ensure_v3_schema(self.store)
        from shared.vm_intelligence.metrics import MetricStore
        from shared.vm_intelligence.goals import GoalEngine
        MetricStore(self.store).record("Smart_Auto_Poster_V2","success_rate_24h",97)
        goals=GoalEngine(self.store);goals.set_goal("sap_success","Smart_Auto_Poster_V2","success_rate_24h",">=",95,"Keep SAP success high")
        rows=goals.evaluate({})
        row=next(x for x in rows if x["goal_key"]=="sap_success")
        self.assertEqual(row["status"],"met");self.assertEqual(row["actual"],97)

    def test_doctor_detects_schema_and_integrity(self):
        ensure_v3_schema(self.store)
        with self.store.connect() as con:
            con.execute("""INSERT INTO intelligence_cycles(
              started_at_utc,completed_at_utc,duration_ms,ingested_events,metric_sources,incident_count,action_count,status,details_json)
              VALUES(?,?,?,?,?,?,?,?,?)""",
              (datetime.now(timezone.utc).isoformat(),datetime.now(timezone.utc).isoformat(),1,0,0,0,0,"ok","{}"))
        (self.root/"diagnostics"/"intelligence_report.json").write_text("{}",encoding="utf-8")
        (self.root/"config").mkdir(exist_ok=True)
        (self.root/"config"/"vm_intelligence.json").write_text("{}",encoding="utf-8")
        admin=self.root/"bots"/"Admin_Command_Centre";admin.mkdir(parents=True,exist_ok=True)
        (admin/"admin_core.py").write_text("# VM_INTELLIGENCE_V3_DISPATCH_BEGIN\n",encoding="utf-8")
        from shared.vm_intelligence.doctor import run_doctor
        result=run_doctor(self.root)
        self.assertTrue(result["ok"],result)

if __name__=="__main__":unittest.main()
