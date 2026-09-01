from __future__ import annotations
import json, tempfile, unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

from shared.vm_intelligence.store import IntelligenceStore
from shared.vm_intelligence.v42_schema import ensure_v42_schema
from shared.vm_intelligence.platform_registry import PlatformServiceRegistry
from shared.vm_intelligence.config_registry import ConfigRegistry
from shared.vm_intelligence.drift_guardian import DriftGuardian
from shared.vm_intelligence.platform_normalization import PlatformNormalizer
from shared.vm_intelligence.reliability import ReliabilityBrain
from shared.vm_intelligence.reliability_engineering import ReliabilityEngineering
from shared.vm_intelligence.runbooks import RunbookEngine
from shared.vm_intelligence.brain import Brain

class V42NormalisationReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)/"project";self.root.mkdir()
        self.store=IntelligenceStore(self.root/"state"/"vm_intelligence.sqlite3")
        ensure_v42_schema(self.store)

    def tearDown(self):self.tmp.cleanup()

    def make_bot(self,name="Admin_Command_Centre",managed=True):
        bot=self.root/"bots"/name
        runtime=bot/name/name
        runtime.mkdir(parents=True)
        (runtime/"main.py").write_text("VALUE=1\n",encoding="utf-8")
        (runtime/"BOT_MANIFEST.json").write_text(json.dumps({
            "name":name,"classification":"CANONICAL","entrypoint":"main.py","version":"1.2.3",
            "entrypoint_confidence":"high",
            "lifecycle":{"auto_start":managed,"auto_restart":managed}
        }),encoding="utf-8")
        (runtime/"config.json").write_text('{"mode":"test"}',encoding="utf-8")
        (runtime/".env").write_text("TOKEN=secret-value-never-report\n",encoding="utf-8")
        (runtime/"service.sqlite3").write_bytes(b"not-a-real-db-for-inventory")
        return bot,runtime

    def test_v42_schema_tables_and_version(self):
        with self.store.connect() as con:
            names={r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            version=con.execute("SELECT value FROM intelligence_meta WHERE key='schema_version'").fetchone()[0]
        for name in {"platform_services","config_registry","platform_drift_snapshots",
                     "reliability_service_stats","runbook_trust","reliability_windows"}:
            self.assertIn(name,names)
        self.assertEqual(version,"5")

    def test_platform_registry_inventory_is_authoritative_and_secret_safe(self):
        bot,runtime=self.make_bot()
        rows=PlatformServiceRegistry(self.store,self.root).refresh()
        self.assertEqual(len(rows),1)
        row=rows[0]
        self.assertEqual(row["service"],"Admin_Command_Centre")
        self.assertEqual(Path(row["canonical_entrypoint"]),runtime/"main.py")
        self.assertEqual(row["owner"],"Admin_Command_Centre")
        self.assertEqual(row["health_provider"],"VM_Core")
        self.assertIn(str(runtime/"service.sqlite3"),row["database_paths"])
        cfg=ConfigRegistry(self.store,self.root).refresh(rows)
        env=next(x for x in cfg if x["path"].endswith(".env"))
        self.assertTrue(env["secret_bearing"])
        state=(self.root/"state"/"config_registry.json").read_text(encoding="utf-8")
        self.assertNotIn("secret-value-never-report",state)
        self.assertIn(env["sha256"],state)
        authoritative=json.loads((self.root/"state"/"platform_service_registry.json").read_text(encoding="utf-8"))
        self.assertIn("canonical source",authoritative["authoritative_for"])

    def test_missing_previous_config_becomes_explicit_drift(self):
        bot,runtime=self.make_bot()
        preg=PlatformServiceRegistry(self.store,self.root)
        services=preg.refresh()
        creg=ConfigRegistry(self.store,self.root)
        first=creg.refresh(services)
        config=runtime/"config.json";config.unlink()
        services=preg.refresh()
        second=creg.refresh(services)
        missing=[x for x in second if x["path"]==str(config.resolve()) and not x["exists"]]
        self.assertEqual(len(missing),1)
        norm=PlatformNormalizer(self.store,self.root).refresh(services)
        drift=DriftGuardian(self.store,self.root).evaluate(services,second,norm)
        self.assertTrue(any(x["category"]=="missing_registered_config" for x in drift["findings"]))
        self.assertFalse(drift["automatic_mutation"])

    def test_runtime_identity_change_is_preserved_for_drift_comparison(self):
        bot,runtime=self.make_bot()
        preg=PlatformServiceRegistry(self.store,self.root)
        first=preg.refresh()
        old_id=first[0]["runtime_id"]
        newdir=bot/"new_runtime";newdir.mkdir()
        newmain=newdir/"main.py";newmain.write_text("VALUE=2\n",encoding="utf-8")
        row={**first[0],"runtime_id":"changed-runtime-id","canonical_root":str(newdir),
             "canonical_entrypoint":str(newmain),"source_hash":"newhash","topology_hash":"newtopology",
             "manifest_count":1,"candidate_count":1,"nested_depth":1,"status":"canonical"}
        second=preg.refresh([row])
        self.assertEqual(second[0]["previous_runtime_id"],old_id)
        self.assertTrue(second[0]["runtime_identity_changed"])
        norm=PlatformNormalizer(self.store,self.root).refresh(second)
        configs=ConfigRegistry(self.store,self.root).refresh(second)
        drift=DriftGuardian(self.store,self.root).evaluate(second,configs,norm)
        self.assertTrue(any(x["category"]=="runtime_identity_changed" for x in drift["findings"]))

    def test_reliability_history_calculates_burn_mttr_mtbf_and_freeze(self):
        rb=ReliabilityBrain(self.store)
        context={
            "VM_Intelligence":{"overall_score":95,"latest_backup_integrity":1},
            "Smart_Auto_Poster_V2":{"success_rate_24h":95,"uncertain_queue":1},
            "Admin_Command_Centre":{"process_alive":1},
            "VM_Guard":{"process_alive":1},
            "VM_Platform":{"managed_services_down":0},
        }
        current=rb.evaluate(context)
        now=datetime.now(timezone.utc)
        with self.store.connect() as con:
            for i in range(3):
                a=(now-timedelta(days=10-i*3)).isoformat()
                b=(now-timedelta(days=10-i*3)+timedelta(minutes=5+i)).isoformat()
                con.execute("""INSERT INTO incidents(fingerprint,source,category,severity,title,status,first_seen_utc,last_seen_utc,occurrences,evidence_json,resolution)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (f"f{i}","Admin_Command_Centre","runtime","medium","runtime issue","resolved",a,b,2,"{}","recovered"))
        hist=ReliabilityEngineering(self.store).evaluate(current,{
            "Admin_Command_Centre":{"metrics":{"process_alive":1}},
            "VM_Guard":{"metrics":{"process_alive":1}},
            "Smart_Auto_Poster_V2":{"metrics":{}},
            "VM_Platform":{"metrics":{}},
            "VM_Intelligence":{"metrics":{}},
        })
        admin=next(x for x in hist["service_stats"] if x["service"]=="Admin_Command_Centre")
        self.assertEqual(admin["incidents_30d"],3)
        self.assertEqual(admin["recurrences_30d"],3)
        self.assertIsNotNone(admin["mttr_seconds"])
        self.assertIsNotNone(admin["mtbf_seconds"])
        self.assertGreater(hist["max_burn_rate"],2)
        self.assertTrue(hist["experiment_freeze_recommended"])

    def test_runbook_trust_requires_evidence_before_certification(self):
        engine=RunbookEngine(self.store)
        for _ in range(5):
            engine.record("managed_service_offline","VM_Guard","success",["restart"])
        hist=ReliabilityEngineering(self.store)._runbook_trust()
        self.assertEqual(hist["managed_service_offline"]["certification"],"provisional")
        for _ in range(15):
            engine.record("managed_service_offline","VM_Guard","success",["restart"])
        hist=ReliabilityEngineering(self.store)._runbook_trust()
        self.assertEqual(hist["managed_service_offline"]["certification"],"certified")
        self.assertEqual(hist["managed_service_offline"]["trust_score"],100.0)

    def test_brain_snapshot_exposes_v42_control_surfaces(self):
        self.make_bot("Admin_Command_Centre",managed=True)
        snap=Brain(self.store,self.root).executive_snapshot(24)
        for key in ("platform_registry","config_registry","platform_drift"):
            self.assertIn(key,snap)
        self.assertIn("historical",snap["reliability"])
        self.assertTrue((self.root/"state"/"platform_service_registry.json").is_file())
        self.assertTrue((self.root/"state"/"config_registry.json").is_file())
        self.assertTrue((self.root/"diagnostics"/"platform_drift.json").is_file())

if __name__=="__main__":
    unittest.main()
