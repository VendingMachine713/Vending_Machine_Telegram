import json, sqlite3, tempfile, unittest
from pathlib import Path
from datetime import datetime, timezone, timedelta

from shared.vm_intelligence.store import IntelligenceStore
from shared.vm_intelligence.integrated_schema import ensure_v3_schema
from shared.vm_intelligence.security_intelligence import SecurityBrain
from shared.vm_intelligence.config_intelligence import ConfigurationIntelligence
from shared.vm_intelligence.meta_intelligence import MetaIntelligence
from shared.vm_intelligence.simulation import SimulationEngine
from shared.vm_intelligence.predictive import PredictiveMaintenance
from shared.vm_intelligence.digital_twin import DigitalTwin
from shared.vm_intelligence.code_intelligence import CodeIntelligence
from shared.vm_intelligence.reporting import build_report, write_report
from shared.vm_intelligence.brain import Brain
from shared.vm_intelligence.release_learning import ReleaseLearning
from shared.vm_intelligence.inbox import IntelligenceInbox

class FinalBrainV3Tests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory()
        self.root=Path(self.t.name)
        (self.root/"bots"/"Admin_Command_Centre").mkdir(parents=True)
        (self.root/"shared").mkdir()
        (self.root/"diagnostics").mkdir()
        (self.root/"config").mkdir()
        (self.root/"backups").mkdir()
        self.store=IntelligenceStore(self.root/"state"/"vm_intelligence.sqlite3")
        ensure_v3_schema(self.store)

    def tearDown(self):
        self.t.cleanup()

    def test_schema_final_tables(self):
        with self.store.connect() as con:
            names={r["name"] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for name in {"config_baselines","postmortems","test_proposals","intelligence_feedback"}:
            self.assertIn(name,names)

    def test_config_drift_hash_only(self):
        env=self.root/"bots"/"Admin_Command_Centre"/".env"
        secret="SUPER_PRIVATE_TOKEN_VALUE_123456789"
        env.write_text("VM_ADMIN_BOT_TOKEN="+secret+"\n",encoding="utf-8")
        engine=ConfigurationIntelligence(self.store,self.root)
        first=engine.refresh()
        self.assertEqual(first["changes"],[])
        env.write_text("VM_ADMIN_BOT_TOKEN=DIFFERENT_SECRET_VALUE_987654321\n",encoding="utf-8")
        second=engine.refresh()
        self.assertEqual(len(second["changes"]),1)
        blob=json.dumps(second)
        self.assertNotIn(secret,blob)
        with self.store.connect() as con:
            db_blob=" ".join(str(tuple(r)) for r in con.execute("SELECT * FROM config_baselines").fetchall())
        self.assertNotIn(secret,db_blob)

    def test_security_finding_never_returns_secret_value(self):
        p=self.root/"bots"/"Admin_Command_Centre"/"bad.py"
        token="123:FAKE"
        p.write_text(f'BOT_TOKEN="{token}"\n',encoding="utf-8")
        result=SecurityBrain(self.root).analyze({})
        self.assertTrue(result["findings"])
        self.assertNotIn(token,json.dumps(result))
        self.assertIn("bad.py",json.dumps(result))

    def test_meta_feedback_usefulness(self):
        with self.store.connect() as con:
            con.execute("""INSERT INTO intelligence_feedback(incident_id,verdict,details,created_at_utc)
                VALUES(1,'useful','',?), (2,'useful','',?), (3,'noise','',?)""",
                (datetime.now(timezone.utc).isoformat(),)*3)
        meta=MetaIntelligence(self.store).analyze()
        self.assertEqual(meta["alert_usefulness_pct"],66.7)

    def test_simulation_safety(self):
        sim=SimulationEngine()
        self.assertEqual(sim.simulate("delete all data",{})["decision"],"blocked")
        self.assertEqual(sim.simulate("increase workers to 20",{})["decision"],"insufficient_evidence")
        managed={"Admin_Command_Centre":{"metrics":{"auto_restart":1}}}
        self.assertEqual(sim.simulate("restart Admin_Command_Centre",managed)["decision"],"safe_candidate")

    def test_predictive_threshold(self):
        now=datetime.now(timezone.utc)
        with self.store.connect() as con:
            for i,value in enumerate([1,2,4,12]):
                stamp=(now-timedelta(hours=3-i)).isoformat()
                con.execute("""INSERT INTO bot_metrics(
                    bucket_utc,observed_at_utc,source,metric,value,unit,quality,metadata_json)
                    VALUES(?,?,?,?,?,?,?,?)""",
                    (stamp,stamp,"Smart_Auto_Poster_V2","failed_24h",value,None,"observed","{}"))
        rows=PredictiveMaintenance(self.store).forecast()
        item=next(x for x in rows if x["metric"]=="failed_24h")
        self.assertEqual(item["estimated_periods_to_threshold"],0)
        self.assertEqual(item["confidence"],"high")

    def test_digital_twin_has_module_endpoints(self):
        bot=self.root/"bots"/"Admin_Command_Centre"
        (bot/"main.py").write_text("from shared.vm_core import paths\n",encoding="utf-8")
        code=CodeIntelligence(self.root).build()
        twin=DigitalTwin().build({"Admin_Command_Centre":{"available":True,"metrics":{}}},code)
        node_ids={n["id"] for n in twin["nodes"]}
        module="bots/Admin_Command_Centre/main.py"
        self.assertIn(module,node_ids)
        self.assertTrue(any(e["from"]==module and e["to"]=="VM_Core" for e in twin["edges"]))


    def test_inbox_escalates_security_and_config_drift(self):
        rows=IntelligenceInbox().build(
            [],[],[],[],[],
            security={"findings":[{"severity":"high","title":"Secret exposure indicator"}]},
            config_drift={"changes":[{"config_key":"A"}]})
        self.assertEqual(rows[0]["priority"],"P1")
        self.assertEqual(rows[0]["type"],"security")
        self.assertTrue(any(x["type"]=="config_drift" and x["priority"]=="P2" for x in rows))

    def test_release_learning_is_observational(self):
        old=(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat()
        with self.store.connect() as con:
            con.execute("""INSERT INTO release_events(
                source,detected_at_utc,previous_version,version,previous_hash,source_hash,status,baseline_score)
                VALUES('VM_Guard',?,'1','2','a','b','observing',90)""",(old,))
        rows=ReleaseLearning(self.store).evaluate(94,min_age_minutes=30)
        self.assertEqual(rows[0]["status"],"improved")
        with self.store.connect() as con:
            row=con.execute("SELECT * FROM release_events WHERE source='VM_Guard'").fetchone()
        self.assertEqual(row["evaluated_score"],94)
        self.assertIn("observational",row["notes"].lower())

    def test_reporting_writes_final_artifacts(self):
        (self.root/"diagnostics"/"live_runtime.json").write_text(
            json.dumps({"services":[],"components":{},"open_alerts":[]}),encoding="utf-8")
        (self.root/"diagnostics"/"full_validation.json").write_text(
            json.dumps({"all_test_suites_ok":True,"critical_tests_ok":True,"preflight_ok":True,
                        "bots_runnable":1,"failed_test_suites":[],"doctor_summary":{"PASS":1,"WARN":0,"FAIL":0}}),
            encoding="utf-8")
        report=build_report(self.store,hours=24,root=self.root)
        write_report(report,self.root/"diagnostics")
        for name in (
            "intelligence_report.json","intelligence_report.txt","intelligence_attention.json",
            "intelligence_brief.txt","intelligence_weekly.txt","intelligence_digital_twin.json",
            "intelligence_inbox.json","intelligence_security.json","intelligence_cto.json",
            "intelligence_postmortems.json","intelligence_testing.json",
            "intelligence_predictive.json","intelligence_scoreboard.json","intelligence_meta.json",
        ):
            self.assertTrue((self.root/"diagnostics"/name).exists(),name)

if __name__=="__main__":
    unittest.main()
