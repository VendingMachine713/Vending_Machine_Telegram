import os, unittest
from pathlib import Path

@unittest.skipIf(os.environ.get("VM_INTELLIGENCE_HOTFIX_RUNTIME")=="1",
                 "full-release package contracts are not applicable to an incremental installed hotfix")
class V3ReleasePackageTests(unittest.TestCase):
    def setUp(self):
        package_root=os.environ.get("VM_INTELLIGENCE_PACKAGE_ROOT")
        self.root=Path(package_root).resolve() if package_root else Path(__file__).resolve().parents[2]

    def test_installer_has_backup_rollback_and_live_validation(self):
        text=(self.root/"INSTALL_VM_INTELLIGENCE_v6.0.0.ps1").read_text(encoding="utf-8")
        for token in (
            "pre_vm_intelligence_v6_",
            "[ROLLBACK]",
            "PATCH_ADMIN_INTELLIGENCE.py",
            "py -m py_compile",
            "Admin Command Centre regression tests failed",
            "RUNTIME_BRIDGE.py",
            "PREPARE_V6_VALIDATION_BUNDLE.ps1",
            "INSTALL_INTELLIGENCE_AUTOSTART.ps1",
            "ROLLBACK_INTELLIGENCE_V6.ps1",
            "VERIFY_RELEASE.py",
            "PRAGMA quick_check",
            "src.backup(dst)",
            "Restored consistent pre-v6 Intelligence database",
            "-WaitSeconds 20",
            "vm_intelligence_release.json",
            "VM_INTELLIGENCE_SHA256.json",
            "RUN_PROJECT_REGRESSION.ps1",
            "RUN_TEST_SUITE.py",
            "VM_INTELLIGENCE_PACKAGE_ROOT",
            "PROBE_SHARED_IMPORT.py",
            r"shared\__init__.py",
            r"state\vm_intelligence.sqlite3",
        ):
            self.assertIn(token,text)

    def test_release_manifest_declares_safety_boundary(self):
        import json
        data=json.loads((self.root/"VM_INTELLIGENCE_RELEASE.json").read_text(encoding="utf-8"))
        self.assertEqual(data["version"],"6.0.0")
        self.assertFalse(data["safety"]["destructive_autonomy"])
        self.assertFalse(data["safety"]["automatic_business_logic_rewrite"])

    def test_windows_bootstrap_exists(self):
        self.assertTrue((self.root/"INSTALL_VM_INTELLIGENCE_v6.0.0_FROM_CMD.bat").exists())

    def test_package_has_no_case_insensitive_path_collisions(self):
        seen={}
        collisions=[]
        for p in self.root.rglob("*"):
            if not p.is_file():
                continue
            rel=p.relative_to(self.root).as_posix()
            if rel=="VM_INTELLIGENCE_SHA256.json":
                continue
            key=rel.casefold()
            if key in seen and seen[key]!=rel:
                collisions.append((seen[key],rel))
            else:
                seen[key]=rel
        self.assertEqual(collisions,[])

    def test_early_failure_does_not_run_full_rollback(self):
        text=(self.root/"INSTALL_VM_INTELLIGENCE_v6.0.0.ps1").read_text(encoding="utf-8")
        self.assertIn("$ProjectMutated=$false",text)
        self.assertIn("if(-not $ProjectMutated)",text)
        self.assertIn("[SAFE EXIT] Installation stopped before v6 production feature files were changed.",text)

    def test_project_regression_uses_canonical_discovery_and_explicit_runner(self):
        text=(self.root/"tools"/"Intelligence"/"RUN_PROJECT_REGRESSION.ps1").read_text(encoding="utf-8")
        self.assertIn("DISCOVER_BOT_TESTS.py",text)
        self.assertIn("RUN_TEST_SUITE.py",text)
        self.assertNotIn("unittest discover",text)

    def test_rollback_reuses_runtime_bridge_without_stale_vm_core_gate(self):
        text=(self.root/"INSTALL_VM_INTELLIGENCE_v6.0.0.ps1").read_text(encoding="utf-8")
        self.assertIn("$AdminPatched=$false",text)
        self.assertIn('state\\runtime_bridge.json',text)
        self.assertIn("RUNTIME_BRIDGE.py",text)
        self.assertNotIn("if($AdminPatched -and $AdminShouldRun)",text)

    def test_installer_repairs_missing_top_level_shared_package_boundary(self):
        text=(self.root/"INSTALL_VM_INTELLIGENCE_v6.0.0.ps1").read_text(encoding="utf-8")
        self.assertIn("shared\\__init__.py", text)
        self.assertIn("PROBE_SHARED_IMPORT.py", text)
        self.assertIn("$SharedBoundaryRepairApplied=$false", text)
        self.assertIn("Retained validated shared/__init__.py VM Core import repair", text)
        self.assertIn("required VM Core submodules are unavailable", text)
        self.assertIn("shared package collision repaired; retaining the compatibility repair", text)

    def test_installer_recovers_physically_missing_vm_core_from_local_assets(self):
        text=(self.root/"INSTALL_VM_INTELLIGENCE_v6.0.0.ps1").read_text(encoding="utf-8")
        self.assertIn("RECOVER_VM_CORE.py", text)
        self.assertIn("$VMCoreRecovered=$false", text)
        self.assertIn("VM_CORE_RECOVERY_RESULT.json", text)
        self.assertIn("Admin/Search/Guard regression gates", text)
        self.assertIn("Retaining recovered VM Core", text)
        recovery=(self.root/"tools"/"Intelligence"/"RECOVER_VM_CORE.py").read_text(encoding="utf-8")
        for digest in (
            "fb845efd8d579d3155cc5af62b3b9e01071eb5ae7046a4371b0edaad06fae528",
            "c3f54661a3727c8f73d1742e720ccdc138bd9e9e726d1a2e050f5c91606dbf86",
            "a6e5ae78b39f501f88ffe155282ef159a1622535e5c246fb9e0dd3670abafd3e",
            "e9dbab60d5abbc7b1015c4fd47d16667b481abc1b9321abb211a151b532746db",
            "68a692d27811de27fc11b5392e8da378aa7dceea9bc693d38675b562c113c2a2",
        ):
            self.assertIn(digest,recovery)

    def test_v500_bootstrap_targets_objective_os_zip(self):
        bat=(self.root/"INSTALL_VM_INTELLIGENCE_v6.0.0_FROM_CMD.bat").read_text(encoding="utf-8")
        self.assertIn("VM_Intelligence_v6.0.0_SELF_IMPROVING_PLATFORM_DIRECT_DROP.zip",bat)
        self.assertNotIn("SHARED_PACKAGE_REPAIR_DIRECT_DROP",bat)

    def test_vm_core_recovery_precedes_bot_baseline_and_feature_mutation(self):
        text=(self.root/"INSTALL_VM_INTELLIGENCE_v6.0.0.ps1").read_text(encoding="utf-8")
        recover=text.index("RECOVER_VM_CORE.py")
        baseline=text.index("Capture fresh untouched pre-install bot regression baseline")
        mutate=text.index("$ProjectMutated=$true")
        self.assertLess(recover,baseline)
        self.assertLess(recover,mutate)

    def test_v305_recovery_is_priority_first_progress_visible_and_bounded(self):
        recovery=(self.root/"tools"/"Intelligence"/"RECOVER_VM_CORE.py").read_text(encoding="utf-8")
        self.assertIn("preferred_snapshot_candidates(root)",recovery)
        self.assertIn("shallow_local_candidates(root)",recovery)
        self.assertIn("known_release_zip_candidates(root)",recovery)
        self.assertIn("git_candidates(root)",recovery)
        self.assertIn('("bounded project-local fallback", "project")',recovery)
        self.assertIn('("bounded external fallback", "external")',recovery)
        self.assertIn("MAX_FALLBACK_DIRS",recovery)
        self.assertIn("MAX_FALLBACK_ZIPS",recovery)
        self.assertIn("MAX_FALLBACK_SECONDS",recovery)
        self.assertIn('print(f"[VMCORE] {message}",flush=True)',recovery)

    def test_v420_runtime_bridge_precedes_baseline_and_feature_mutation(self):
        text=(self.root/"INSTALL_VM_INTELLIGENCE_v6.0.0.ps1").read_text(encoding="utf-8")
        preview=text.index('Preview root-level runtime compatibility bridge (no writes)')
        baseline=text.index('Capture fresh untouched pre-install bot regression baseline')
        apply=text.index('Apply and compile validated runtime compatibility bridge')
        mutate=text.index("$ProjectMutated=$true")
        self.assertLess(preview,baseline)
        self.assertLess(baseline,apply)
        self.assertLess(apply,mutate)
        self.assertIn("$RuntimeBridgeApplied=$false",text)
        self.assertIn("Retained validated root runtime compatibility bridge",text)
        self.assertIn('--mode prepare',text)
        self.assertIn('--mode prepare --apply',text)
        self.assertIn('--mode ensure',text)

    def test_v420_installed_runtime_skips_only_release_qualification_process_simulations(self):
        text=(self.root/"INSTALL_VM_INTELLIGENCE_v6.0.0.ps1").read_text(encoding="utf-8")
        self.assertIn('VM_INTELLIGENCE_INSTALLED_RUNTIME="1"',text)
        legacy=(self.root/"tests"/"vm_intelligence"/"test_admin_runtime_gate_v306.py").read_text(encoding="utf-8")
        self.assertIn("package qualification-only legacy process fallback simulation",legacy)
        self.assertIn("taskkill",legacy)
        self.assertIn("pid_alive",legacy)
        recovery=(self.root/"tests"/"vm_intelligence"/"test_vm_core_recovery_v304.py").read_text(encoding="utf-8")
        self.assertIn("package qualification-only recovery simulation",recovery)
        self.assertIn("test_missing_required_candidate_is_rejected_without_partial_vm_core",recovery)

    def test_v420_runtime_tools_are_packaged(self):
        self.assertTrue((self.root/"tools"/"Intelligence"/"RUNTIME_BRIDGE.py").is_file())
        self.assertTrue((self.root/"tools"/"Intelligence"/"REPAIR_RUNTIME_MANIFESTS.py").is_file())
        self.assertTrue((self.root/"tools"/"Intelligence"/"PREPARE_V4_VALIDATION_BUNDLE.ps1").is_file())
        text=(self.root/"INSTALL_VM_INTELLIGENCE_v6.0.0.ps1").read_text(encoding="utf-8")
        self.assertIn("Validate v6 schema, evidence quality, policy kernel and self-improving control plane",text)
        self.assertIn('py -m shared.vm_intelligence.cli --root "$Root" doctor',text)

    def test_v4_objective_autonomy_safety_contract(self):
        import json
        data=json.loads((self.root/"VM_INTELLIGENCE_RELEASE.json").read_text(encoding="utf-8"))
        safety=data["safety"]
        self.assertEqual(safety["default_autonomy_level"],4)
        self.assertFalse(safety["architecture_relocation_automatic"])
        self.assertFalse(safety["release_auto_promotion"])
        self.assertTrue(safety["safe_mode_caps_effective_level"]==4)
        self.assertTrue(safety["objective_plans_bounded_to_registered_actions"])

    def test_v4_doctor_gate_precedes_passive_agent(self):
        text=(self.root/"INSTALL_VM_INTELLIGENCE_v6.0.0.ps1").read_text(encoding="utf-8")
        doctor=text.index("Validate v6 schema, evidence quality, policy kernel and self-improving control plane")
        agent=text.index("Enable v6 passive Intelligence agent")
        self.assertLess(doctor,agent)
        self.assertIn("PREPARE_V6_VALIDATION_BUNDLE.ps1",text)
        self.assertTrue((self.root/"docs"/"VM_INTELLIGENCE_v4_RELEASE_NOTES.md").is_file())
        self.assertTrue((self.root/"START_HERE_VM_INTELLIGENCE_V6.txt").is_file())

    def test_v4_rollback_current_and_v3_rollback_compatibility_are_both_packaged(self):
        v4=self.root/"tools"/"Intelligence"/"ROLLBACK_INTELLIGENCE_V4.ps1"
        v3=self.root/"tools"/"Intelligence"/"ROLLBACK_INTELLIGENCE_V3.ps1"
        self.assertTrue(v4.is_file())
        self.assertTrue(v3.is_file())
        self.assertTrue((self.root/"tools"/"Intelligence"/"ROLLBACK_INTELLIGENCE_V6.ps1").is_file())
        self.assertTrue((self.root/"tools"/"Intelligence"/"PREPARE_V6_VALIDATION_BUNDLE.ps1").is_file())
        self.assertIn("pre_vm_intelligence_v4_",v4.read_text(encoding="utf-8"))
        self.assertIn("pre_vm_intelligence_v6_",(self.root/"tools"/"Intelligence"/"ROLLBACK_INTELLIGENCE_V6.ps1").read_text(encoding="utf-8"))
        self.assertIn("pre_vm_intelligence_v3_",v3.read_text(encoding="utf-8"))
        installer=(self.root/"INSTALL_VM_INTELLIGENCE_v6.0.0.ps1").read_text(encoding="utf-8")
        self.assertIn("ROLLBACK_INTELLIGENCE_V6.ps1",installer)

    def test_v420_schema_registry_drift_and_reliability_are_packaged(self):
        required=[
            "shared/vm_intelligence/v42_schema.py",
            "shared/vm_intelligence/platform_registry.py",
            "shared/vm_intelligence/config_registry.py",
            "shared/vm_intelligence/drift_guardian.py",
            "shared/vm_intelligence/reliability_engineering.py",
            "tests/vm_intelligence/test_v42_normalisation_reliability.py",
        ]
        for rel in required:
            self.assertTrue((self.root/rel).is_file(),rel)
        doctor=(self.root/"shared"/"vm_intelligence"/"doctor.py").read_text(encoding="utf-8")
        self.assertIn('EXPECTED_VERSION="6.0.0"',doctor)
        self.assertIn('str(schema[0])=="12"',doctor)
        bundle=(self.root/"tools"/"Intelligence"/"PREPARE_V4_VALIDATION_BUNDLE.ps1").read_text(encoding="utf-8")
        self.assertIn("intelligence_platform_service_registry.json",bundle)
        self.assertIn("intelligence_config_registry.json",bundle)
        self.assertIn("intelligence_platform_drift.json",bundle)

    def test_v420_secret_safe_config_registry_contract(self):
        text=(self.root/"shared"/"vm_intelligence"/"config_registry.py").read_text(encoding="utf-8")
        self.assertIn("HASH-ONLY" if False else "Hash-only", text)
        self.assertNotIn("read_text(",text)
        self.assertIn("secret_bearing",text)
        self.assertIn("sha256",text)

    def test_v500_objective_os_contract(self):
        required=[
            "shared/vm_intelligence/v5_schema.py",
            "shared/vm_intelligence/root_cause_v5.py",
            "shared/vm_intelligence/predictive_ops_v5.py",
            "shared/vm_intelligence/release_intelligence_v5.py",
            "shared/vm_intelligence/automation_discovery_v5.py",
            "shared/vm_intelligence/experiment_governance_v5.py",
            "shared/vm_intelligence/capability_trust_v5.py",
            "shared/vm_intelligence/engineering_candidate_v5.py",
            "shared/vm_intelligence/strategic_planner_v5.py",
            "tests/vm_intelligence/test_v5_operating_system.py",
        ]
        for rel in required:self.assertTrue((self.root/rel).is_file(),rel)
        doctor=(self.root/"shared"/"vm_intelligence"/"doctor.py").read_text(encoding="utf-8")
        self.assertIn('EXPECTED_VERSION="6.0.0"',doctor)
        self.assertIn('str(schema[0])=="12"',doctor)
        installer=(self.root/"INSTALL_VM_INTELLIGENCE_v6.0.0.ps1").read_text(encoding="utf-8")
        self.assertIn("Validate v6 schema, evidence quality, policy kernel and self-improving control plane",installer)
        self.assertIn("VM_INTELLIGENCE_V6_VALIDATION_BUNDLE.zip",installer)

    def test_v500_authority_progression_contract(self):
        exp=(self.root/"shared"/"vm_intelligence"/"experiment_governance_v5.py").read_text(encoding="utf-8")
        trust=(self.root/"shared"/"vm_intelligence"/"capability_trust_v5.py").read_text(encoding="utf-8")
        eng=(self.root/"shared"/"vm_intelligence"/"engineering_candidate_v5.py").read_text(encoding="utf-8")
        plan=(self.root/"shared"/"vm_intelligence"/"strategic_planner_v5.py").read_text(encoding="utf-8")
        self.assertIn("CERTIFIED_EXPERIMENT_DOMAINS",exp)
        self.assertIn("direct_production_source_rewrite",trust)
        self.assertIn('"production_mutation":False',eng.replace(" ",""))
        self.assertIn('"planner_level":7',plan.replace(" ",""))
        self.assertIn('"execution_authority":"capability_specific"',plan.replace(" ",""))
        self.assertIn('"global_production_execution":False',plan.replace(" ",""))

    def test_v600_self_improving_platform_contract(self):
        required=[
            "shared/vm_intelligence/v6_schema.py",
            "shared/vm_intelligence/evidence_quality_v6.py",
            "shared/vm_intelligence/policy_kernel_v6.py",
            "shared/vm_intelligence/intervention_effectiveness_v6.py",
            "shared/vm_intelligence/runbook_evolution_v6.py",
            "shared/vm_intelligence/disaster_recovery_v6.py",
            "shared/vm_intelligence/attention_governor_v6.py",
            "shared/vm_intelligence/architecture_modernization_v6.py",
            "shared/vm_intelligence/strategic_operator_v6.py",
            "shared/vm_intelligence/self_improvement_v6.py",
            "tests/vm_intelligence/test_v6_self_improving_platform.py",
        ]
        for rel in required:self.assertTrue((self.root/rel).is_file(),rel)
        doctor=(self.root/"shared"/"vm_intelligence"/"doctor.py").read_text(encoding="utf-8")
        self.assertIn('EXPECTED_VERSION="6.0.0"',doctor)
        self.assertIn('str(schema[0])=="12"',doctor)
        installer=(self.root/"INSTALL_VM_INTELLIGENCE_v6.0.0.ps1").read_text(encoding="utf-8")
        self.assertIn("Validate v6 schema, evidence quality, policy kernel and self-improving control plane",installer)
        self.assertIn("VM_INTELLIGENCE_V6_VALIDATION_BUNDLE.zip",installer)

    def test_v600_policy_kernel_hard_invariants_are_packaged(self):
        kernel=(self.root/"shared"/"vm_intelligence"/"policy_kernel_v6.py").read_text(encoding="utf-8")
        for token in ("blind_uncertain_retry","direct_production_source_rewrite","credential_change",
                      "permission_change","bypass_security_gate","bypass_regression_gate"):
            self.assertIn(token,kernel)
        self.assertIn("global_authority_granted",kernel)

    def test_v600_exact_test_surface_gate_is_required(self):
        regression=(self.root/"tools"/"Intelligence"/"RUN_PROJECT_REGRESSION.ps1").read_text(encoding="utf-8")
        for token in ("test_ids_added","test_ids_removed","test_surface_changed_suites",
                      "stable_test_surface","--result-json","exit 3"):
            self.assertIn(token,regression)

    def test_v600_validation_bundle_contains_v6_surfaces(self):
        bundle=(self.root/"tools"/"Intelligence"/"PREPARE_V6_VALIDATION_BUNDLE.ps1").read_text(encoding="utf-8")
        for name in ("intelligence_evidence_quality_v6.json","intelligence_policy_kernel_v6.json",
                     "intelligence_intervention_effectiveness_v6.json","intelligence_runbook_evolution_v6.json",
                     "intelligence_disaster_recovery_v6.json","intelligence_attention_governor_v6.json",
                     "intelligence_architecture_modernization_v6.json","intelligence_strategic_operator_v6.json",
                     "intelligence_self_improvement_v6.json"):
            self.assertIn(name,bundle)

if __name__=="__main__":
    unittest.main()
