from __future__ import annotations
import json,tempfile,unittest
from pathlib import Path

from shared.vm_intelligence.store import IntelligenceStore
from shared.vm_intelligence.reliability import ReliabilityBrain
from shared.vm_intelligence.reliability_engineering import ReliabilityEngineering
from shared.vm_intelligence.platform_registry import PlatformServiceRegistry
from shared.vm_intelligence.config_registry import ConfigRegistry
from shared.vm_intelligence.platform_normalization import PlatformNormalizer
from shared.vm_intelligence.drift_guardian import DriftGuardian

class V501LiveCalibrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)/"project";self.root.mkdir()
        self.store=IntelligenceStore(self.root/"state"/"vm_intelligence.sqlite3")

    def tearDown(self):self.tmp.cleanup()

    def _nested_bot(self,name="Admin_Command_Centre"):
        runtime=self.root/"bots"/name/name/name
        runtime.mkdir(parents=True)
        (runtime/"main.py").write_text("VALUE=1\n",encoding="utf-8")
        (runtime/"BOT_MANIFEST.json").write_text(json.dumps({
            "name":name,"classification":"CANONICAL","entrypoint":"main.py",
            "lifecycle":{"auto_start":True,"auto_restart":True}
        }),encoding="utf-8")
        # Root bridge is expected legacy architecture debt, not change drift.
        root=self.root/"bots"/name
        (root/"main.py").write_text("# compatibility shim\n",encoding="utf-8")
        (root/"BOT_MANIFEST.json").write_text(json.dumps({
            "name":name,"entrypoint":"main.py","lifecycle":{"auto_start":True,"auto_restart":True}
        }),encoding="utf-8")
        return runtime

    def test_zero_tolerance_slo_breach_has_no_fake_999_numeric_burn(self):
        current=ReliabilityBrain(self.store).evaluate({
            "VM_Intelligence":{"overall_score":95,"latest_backup_integrity":1},
            "Smart_Auto_Poster_V2":{"success_rate_24h":99,"uncertain_queue":1},
            "Admin_Command_Centre":{"process_alive":1},
            "VM_Guard":{"process_alive":1},
            "VM_Platform":{"managed_services_down":0},
        })
        hist=ReliabilityEngineering(self.store).evaluate(current,{})
        strict=next(x for x in hist["slos"] if x["slo_key"]=="sap_uncertain")
        self.assertTrue(strict["strict_zero_budget"])
        self.assertTrue(strict["strict_budget_breach"])
        self.assertIsNone(strict["burn_rate"])
        self.assertNotEqual(hist["max_burn_rate"],999)
        self.assertGreaterEqual(hist["strict_zero_budget_breaches"],1)
        self.assertTrue(hist["experiment_freeze_recommended"])

    def test_known_nested_bridge_debt_is_hygiene_not_drift(self):
        self._nested_bot()
        registry=PlatformServiceRegistry(self.store,self.root)
        services=registry.refresh()
        configs=ConfigRegistry(self.store,self.root).refresh(services)
        normalization=PlatformNormalizer(self.store,self.root).refresh(services)
        self.assertTrue(normalization["violations"])  # known architecture debt remains visible
        drift=DriftGuardian(self.store,self.root).evaluate(services,configs,normalization)
        self.assertEqual(drift["score"],100.0)
        self.assertEqual(drift["findings"],[])
        self.assertGreater(drift["architecture_hygiene_findings"],0)

    def test_real_source_change_is_drift_after_baseline(self):
        runtime=self._nested_bot("VM_Guard")
        registry=PlatformServiceRegistry(self.store,self.root)
        first=registry.refresh()
        ConfigRegistry(self.store,self.root).refresh(first)
        (runtime/"main.py").write_text("VALUE=2\n",encoding="utf-8")
        # Runtime registry hash should observe modified canonical source.
        second=registry.refresh()
        row=second[0]
        self.assertTrue(row["source_changed"])
        configs=ConfigRegistry(self.store,self.root).refresh(second)
        normalization=PlatformNormalizer(self.store,self.root).refresh(second)
        drift=DriftGuardian(self.store,self.root).evaluate(second,configs,normalization)
        self.assertTrue(any(x["category"]=="canonical_source_changed" for x in drift["findings"]))
        self.assertLess(drift["score"],100)

if __name__=="__main__":unittest.main()
