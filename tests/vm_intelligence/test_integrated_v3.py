import json, sqlite3, tempfile, unittest, zipfile
from pathlib import Path

from shared.vm_intelligence.store import IntelligenceStore
from shared.vm_intelligence.integrated_schema import ensure_v3_schema
from shared.vm_intelligence.adapters import AdapterHub
from shared.vm_intelligence.brain import Brain
from shared.vm_intelligence.releases import ReleaseIntelligence
from shared.vm_intelligence.notifications import TelegramNotifier

class V3IntegratedTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        for name in ("Smart_Auto_Poster_V2","VM_Relationship_Manager","Universal_Search","VM_Guard","Admin_Command_Centre"):
            (self.root/"bots"/name).mkdir(parents=True,exist_ok=True)
        (self.root/"shared"/"exports"/"VM_Relationship_Manager").mkdir(parents=True)
        (self.root/"diagnostics").mkdir()
        (self.root/"backups").mkdir()
        self.store=IntelligenceStore(self.root/"state"/"vm_intelligence.sqlite3")
        ensure_v3_schema(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def make_sap(self):
        db=self.root/"bots"/"Smart_Auto_Poster_V2"/"data"/"smart_autoposter.sqlite3"
        db.parent.mkdir(parents=True)
        con=sqlite3.connect(db)
        con.executescript("""
        CREATE TABLE queue(id INTEGER PRIMARY KEY,status TEXT,updated_at TEXT,error_kind TEXT);
        CREATE TABLE accounts(enabled INTEGER,authorized INTEGER,health_score INTEGER,consecutive_failures INTEGER,cooldown_until TEXT);
        CREATE TABLE campaigns(enabled INTEGER);
        CREATE TABLE destinations(enabled INTEGER,quarantine_until TEXT);
        CREATE TABLE events(created_at TEXT,severity TEXT);
        CREATE TABLE recommendations(status TEXT);
        CREATE TABLE heartbeats(component TEXT,last_seen_at TEXT,status TEXT);
        """)
        now="2099-01-01T00:00:00+00:00"
        for status in ("sent","sent","sent","failed","uncertain"):
            con.execute("INSERT INTO queue(status,updated_at,error_kind) VALUES(?,?,?)",(status,now,"network" if status!="sent" else None))
        con.execute("INSERT INTO accounts VALUES(1,1,80,1,NULL)")
        con.execute("INSERT INTO campaigns VALUES(1)")
        con.execute("INSERT INTO destinations VALUES(1,NULL)")
        con.commit();con.close()

    def make_rm(self):
        db=self.root/"shared"/"exports"/"VM_Relationship_Manager"/"vm_relationships.db"
        con=sqlite3.connect(db)
        con.executescript("""
        CREATE TABLE contacts(telegram_id INTEGER,last_seen TEXT);
        CREATE TABLE followups(status TEXT,due_at TEXT);
        CREATE TABLE risk_flags(review_status TEXT);
        CREATE TABLE attention_queue(status TEXT);
        CREATE TABLE bot_health(id INTEGER PRIMARY KEY,component TEXT,status TEXT,details TEXT,created_at TEXT);
        CREATE TABLE recommended_actions(status TEXT);
        CREATE TABLE relationship_goals(status TEXT);
        CREATE TABLE contact_forecasts(disengagement_risk INTEGER);
        CREATE TABLE data_quality_metrics(completeness_score INTEGER,confidence_score INTEGER);
        CREATE TABLE integration_events(status TEXT);
        CREATE TABLE admin_audit(action TEXT,created_at TEXT);
        CREATE TABLE app_meta(meta_key TEXT,meta_value TEXT);
        CREATE TABLE backup_audit(id INTEGER PRIMARY KEY,integrity_status TEXT,created_at TEXT);
        """)
        con.execute("INSERT INTO contacts VALUES(1,'2099-01-01T00:00:00+00:00')")
        con.execute("INSERT INTO followups VALUES('open','2000-01-01T00:00:00+00:00')")
        con.execute("INSERT INTO bot_health VALUES(1,'scheduler','ok','ok','2099-01-01T00:00:00+00:00')")
        con.execute("INSERT INTO backup_audit VALUES(1,'verified','2099-01-01T00:00:00+00:00')")
        con.commit();con.close()

    def make_search(self):
        db=self.root/"bots"/"Universal_Search"/"data"/"universal_search.db"
        db.parent.mkdir(parents=True)
        con=sqlite3.connect(db)
        con.executescript("""
        CREATE TABLE indexed_messages(chat_id INTEGER,message_id INTEGER);
        CREATE TABLE chats(chat_id INTEGER);
        CREATE TABLE senders(sender_id INTEGER);
        CREATE TABLE search_audit(created_utc TEXT);
        """)
        con.execute("INSERT INTO indexed_messages VALUES(1,1)")
        con.execute("INSERT INTO chats VALUES(1)")
        con.execute("INSERT INTO senders VALUES(1)")
        con.commit();con.close()

    def make_runtime(self, admin_alive=True):
        data={"services":[
            {"name":"VM_Guard","process_alive":True,"runtime_status":"RUNNING","policy":{"auto_restart":True}},
            {"name":"Admin_Command_Centre","process_alive":admin_alive,"runtime_status":"RUNNING" if admin_alive else "STOPPED","policy":{"auto_restart":True}},
            {"name":"Smart_Auto_Poster_V2","process_alive":False,"runtime_status":"READY","policy":{"auto_restart":False}},
            {"name":"VM_Relationship_Manager","process_alive":False,"runtime_status":"READY","policy":{"auto_restart":False}},
        ],"components":{"VM_Guard":{"age_seconds":3,"legacy_component_expected":True,"legacy_component":{"alive":True}}},"open_alerts":[]}
        (self.root/"diagnostics"/"live_runtime.json").write_text(json.dumps(data),encoding="utf-8")
        (self.root/"diagnostics"/"full_validation.json").write_text(json.dumps({
            "all_test_suites_ok":True,"critical_tests_ok":True,"preflight_ok":True,
            "bots_runnable":5,"failed_test_suites":[],"doctor_summary":{"PASS":30,"WARN":0,"FAIL":0},
            "supervisor_actions":[
                {"service":"Admin_Command_Centre","policy":{"auto_start":True,"auto_restart":True}},
                {"service":"VM_Guard","policy":{"auto_start":True,"auto_restart":True}},
                {"service":"Smart_Auto_Poster_V2","policy":{"auto_start":False,"auto_restart":False}},
                {"service":"VM_Relationship_Manager","policy":{"auto_start":False,"auto_restart":False}}
            ]
        }),encoding="utf-8")

    def test_schema_v3(self):
        with self.store.connect() as con:
            names={r["name"] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for name in {"bot_metrics","root_cause_reports","automation_opportunities","operational_goals",
                     "goal_evaluations","release_events","notification_state","intelligence_cycles"}:
            self.assertIn(name,names)

    def test_native_adapters(self):
        self.make_sap();self.make_rm();self.make_search();self.make_runtime()
        data=AdapterHub(self.store,self.root).collect()
        self.assertEqual(data["Smart_Auto_Poster_V2"]["metrics"]["uncertain_queue"],1)
        self.assertEqual(data["VM_Relationship_Manager"]["metrics"]["contacts_total"],1)
        self.assertEqual(data["Universal_Search"]["metrics"]["legacy_messages"],1)
        self.assertEqual(data["Admin_Command_Centre"]["metrics"]["process_alive"],1)

    def test_brain_detects_managed_service_down_and_root_cause(self):
        self.make_runtime(admin_alive=False)
        snap=Brain(self.store,self.root).executive_snapshot()
        cats={x["category"] for x in snap["incidents"]}
        self.assertIn("managed_service_down",cats)
        self.assertTrue(any(x["confidence"]>=.9 for x in snap["root_causes"]))

    def test_release_change_history(self):
        self.make_runtime()
        bot=self.root/"bots"/"VM_Guard"
        (bot/"main.py").write_text("print('a')\n",encoding="utf-8")
        ri=ReleaseIntelligence(self.store,self.root)
        self.assertEqual(ri.refresh(90),[])
        (bot/"main.py").write_text("print('b')\n",encoding="utf-8")
        changes=ri.refresh(91)
        self.assertTrue(any(x["source"]=="VM_Guard" for x in changes))
        with self.store.connect() as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM release_events WHERE source='VM_Guard'").fetchone()[0],1)


    def test_fresh_regression_status_overrides_stale_full_validation(self):
        old="2026-01-01T00:00:00+00:00";new="2099-01-01T00:00:00+00:00"
        (self.root/"diagnostics"/"full_validation.json").write_text(json.dumps({
            "completed_at_utc":old,"critical_tests_ok":False,"all_test_suites_ok":False,
            "failed_test_suites":["Smart_Auto_Poster_V2"],"preflight_ok":False,"bots_runnable":5,
            "supervisor_actions":[]
        }),encoding="utf-8")
        (self.root/"diagnostics"/"intelligence_regression.json").write_text(json.dumps({
            "completed_at_utc":new,"failed_test_suites":[],"new_failed_test_suites":[],
            "all_test_suites_ok":True,"no_new_regressions":True
        }),encoding="utf-8")
        data=AdapterHub(self.store,self.root).collect()["VM_Platform"]
        self.assertEqual(data["metrics"]["critical_tests_ok"],1)
        self.assertEqual(data["evidence"]["test_status_source"],"intelligence_regression")

    def test_intentionally_stopped_services_are_not_managed_down(self):
        self.make_runtime(admin_alive=True)
        data=json.loads((self.root/"diagnostics"/"live_runtime.json").read_text())
        data["services"].append({"name":"VM_Relationship_Manager","process_alive":False,"runtime_status":"READY"})
        (self.root/"diagnostics"/"live_runtime.json").write_text(json.dumps(data),encoding="utf-8")
        platform=AdapterHub(self.store,self.root).collect()["VM_Platform"]
        self.assertEqual(platform["metrics"]["managed_services_down"],0)

    def test_notifier_is_safe_without_credentials(self):
        self.make_runtime()
        n=TelegramNotifier(self.store,self.root)
        self.assertEqual(n._send("test"),0)

if __name__=="__main__":
    unittest.main()
