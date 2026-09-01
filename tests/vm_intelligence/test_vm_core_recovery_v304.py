from __future__ import annotations
import importlib.util, json, tempfile, unittest, zipfile, sys, os
from pathlib import Path

INSTALLED_RUNTIME_SKIP=os.environ.get("VM_INTELLIGENCE_INSTALLED_RUNTIME","0")=="1"

class VMCoreRecovery304Tests(unittest.TestCase):
    def setUp(self):
        self._old_skip_external=os.environ.get("VM_CORE_RECOVERY_SKIP_EXTERNAL")
        os.environ["VM_CORE_RECOVERY_SKIP_EXTERNAL"]="1"
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)/'project';self.root.mkdir()
        self.package=Path(__file__).resolve().parents[2]
        self.tool=self.package/'tools'/'Intelligence'/'RECOVER_VM_CORE.py'
        spec=importlib.util.spec_from_file_location('recover_vm_core',self.tool)
        self.mod=importlib.util.module_from_spec(spec);sys.modules[spec.name]=self.mod;spec.loader.exec_module(self.mod)
        (self.root/'shared').mkdir()
        for bot in ('Admin_Command_Centre','Universal_Search','VM_Guard'):
            b=self.root/'bots'/bot;(b/'tests').mkdir(parents=True);(b/'main.py').write_text("print('ok')\n",encoding='utf-8')
            (b/'BOT_MANIFEST.json').write_text(json.dumps({'name':bot,'entrypoint':'main.py','classification':'CANONICAL'}),encoding='utf-8')
        (self.root/'bots'/'Admin_Command_Centre'/'tests'/'test_admin.py').write_text(
            "from shared.vm_core.admins import load_admin_ids\nimport unittest\nclass T(unittest.TestCase):\n def test_x(self): self.assertEqual(load_admin_ids(None),set())\n",encoding='utf-8')
        (self.root/'bots'/'Universal_Search'/'tests'/'test_search.py').write_text(
            "from shared.vm_core.db import PlatformDB\nimport unittest\nclass T(unittest.TestCase):\n def test_x(self): self.assertTrue(PlatformDB)\n",encoding='utf-8')
        (self.root/'bots'/'VM_Guard'/'tests'/'test_guard.py').write_text(
            "from shared.vm_core.services import service_status\nimport unittest\nclass T(unittest.TestCase):\n def test_x(self): self.assertEqual(service_status(None),[])\n",encoding='utf-8')
    def tearDown(self):
        self.tmp.cleanup()
        if self._old_skip_external is None:
            os.environ.pop("VM_CORE_RECOVERY_SKIP_EXTERNAL",None)
        else:
            os.environ["VM_CORE_RECOVERY_SKIP_EXTERNAL"]=self._old_skip_external

    def make_candidate(self,missing=None):
        vm=self.root/'backups'/'known_good'/'shared'/'vm_core';vm.mkdir(parents=True)
        files={
            '__init__.py':"__version__='1.4.0'\n",
            'admins.py':"def load_admin_ids(root): return set()\ndef add_admin_id(root,user_id): return True\n",
            'db.py':"class PlatformDB:\n def __init__(self,*a,**k): pass\n",
            'services.py':"def service_status(root): return []\ndef restart_service(*a,**k): return {'ok':True}\n",
            'manifests.py':"def discover_bots(root): return []\n",
            'supervisor.py':"def supervise_once(root,apply=False): return {'ok':True}\n",
        }
        for name,text in files.items():
            if name!=missing:(vm/name).write_text(text,encoding='utf-8')
        return vm

    @unittest.skipIf(INSTALLED_RUNTIME_SKIP,"package qualification-only recovery simulation")
    def test_directory_candidate_restores_deleted_vm_core_and_passes_bot_gates(self):
        self.make_candidate();report=self.root/'diagnostics'/'recovery.json'
        rc=self.mod.main(['--root',str(self.root),'--package-root',str(self.package),'--report',str(report)])
        self.assertEqual(rc,0)
        data=json.loads(report.read_text(encoding='utf-8'))
        self.assertEqual(data['status'],'recovered')
        self.assertTrue((self.root/'shared'/'vm_core'/'db.py').is_file())
        self.assertTrue((self.root/'shared'/'__init__.py').is_file())
        self.assertTrue(all(x['ok'] for x in data['accepted']['tests'] if x['bot'] in {'Admin_Command_Centre','Universal_Search','VM_Guard'}))

    def test_missing_required_candidate_is_rejected_without_partial_vm_core(self):
        self.make_candidate(missing='services.py');report=self.root/'diagnostics'/'recovery.json'
        rc=self.mod.main(['--root',str(self.root),'--package-root',str(self.package),'--report',str(report)])
        self.assertEqual(rc,4)
        self.assertFalse((self.root/'shared'/'vm_core').exists())
        data=json.loads(report.read_text(encoding='utf-8'))
        self.assertEqual(data['status'],'no_acceptable_candidate')

    def test_known_official_filename_with_wrong_hash_is_not_candidate(self):
        zdir=Path(self.tmp.name)/'zips';zdir.mkdir();z=zdir/'VM_Ecosystem_v1.4.0_DIRECT_DROP.zip'
        with zipfile.ZipFile(z,'w') as arc:arc.writestr('shared/vm_core/__init__.py','x')
        rows=self.mod.scan_zips([zdir])
        self.assertEqual(rows,[])

    def test_pre_v143_snapshot_is_prioritized_over_generic_backup(self):
        generic=self.make_candidate()
        preferred=self.root/'backups'/'pre_v1_4_3_ecosystem_20260901_062015'/'shared'/'vm_core'
        preferred.mkdir(parents=True)
        for p in generic.iterdir():
            if p.is_file():
                preferred.joinpath(p.name).write_bytes(p.read_bytes())
        rows=self.mod.scan_dirs(self.root,[self.root/'backups'])
        self.assertGreaterEqual(len(rows),2)
        rows=sorted(rows,key=lambda c:(-c.trust,c.label.casefold()))
        self.assertIn('pre_v1_4_3_ecosystem',rows[0].source.lower())
        self.assertEqual(rows[0].trust,98)

    def test_prefixed_zip_vm_core_is_materialized(self):
        zdir=Path(self.tmp.name)/'zips';zdir.mkdir()
        z=zdir/'private_snapshot.zip'
        files={
            '__init__.py':"__version__='1.4.3'\\n",
            'admins.py':"def load_admin_ids(root): return set()\\ndef add_admin_id(root,user_id): return True\\n",
            'db.py':"class PlatformDB: pass\\n",
            'services.py':"def service_status(root): return []\\ndef restart_service(*a,**k): return {'ok':True}\\n",
            'manifests.py':"def discover_bots(root): return []\\n",
            'supervisor.py':"def supervise_once(root,apply=False): return {'ok':True}\\n",
        }
        with zipfile.ZipFile(z,'w') as arc:
            for name,body in files.items():
                arc.writestr('VM_Ecosystem_v1.4.3/shared/vm_core/'+name,body)
        rows=self.mod.scan_zips([zdir])
        self.assertEqual(len(rows),1)
        stage=Path(self.tmp.name)/'extract'
        vm=self.mod.materialize(rows[0],stage)
        self.assertTrue((vm/'services.py').is_file())
        self.assertIn("1.4.3",(vm/'__init__.py').read_text(encoding='utf-8'))

    def test_candidate_with_unsafe_runtime_file_is_rejected(self):
        vm=self.make_candidate()
        (vm/'.env').write_text('TOKEN=do-not-copy\\n',encoding='utf-8')
        safe,reason=self.mod.safe_tree(vm)
        self.assertFalse(safe)
        self.assertIn('unsafe file',reason)

    @unittest.skipIf(INSTALLED_RUNTIME_SKIP,"package qualification-only recovery simulation")
    def test_successful_recovery_records_tree_provenance(self):
        self.make_candidate();report=self.root/'diagnostics'/'recovery.json'
        rc=self.mod.main(['--root',str(self.root),'--package-root',str(self.package),'--report',str(report)])
        self.assertEqual(rc,0)
        data=json.loads(report.read_text(encoding='utf-8'))
        accepted=data['accepted']
        self.assertEqual(len(accepted['recovered_tree_sha256']),64)
        self.assertGreaterEqual(accepted['recovered_file_count'],6)
        audit=self.root/'state'/'vm_core_recovery.json'
        self.assertTrue(audit.is_file())

    def test_zip_path_traversal_is_refused(self):
        z=Path(self.tmp.name)/'bad.zip'
        with zipfile.ZipFile(z,'w') as arc:
            arc.writestr('bundle/shared/vm_core/__init__.py',"x=1\n")
            arc.writestr('bundle/shared/vm_core/../../escape.py',"bad=1\n")
        c=self.mod.Candidate('zip',str(z),65,'bad zip')
        with self.assertRaises(ValueError):
            self.mod.materialize(c,Path(self.tmp.name)/'bad_extract')

    def test_symlink_candidate_is_rejected(self):
        vm=self.make_candidate()
        try:
            (vm/'linked.py').symlink_to(vm/'db.py')
        except (OSError,NotImplementedError):
            self.skipTest('symlink creation unavailable')
        safe,reason=self.mod.safe_tree(vm)
        self.assertFalse(safe)
        self.assertIn('symlink not allowed',reason)

    @unittest.skipIf(INSTALLED_RUNTIME_SKIP,"package qualification-only recovery simulation")
    def test_exact_pre_v143_snapshot_shape_recovers_end_to_end(self):
        generic=self.make_candidate()
        preferred=self.root/'backups'/'pre_v1_4_3_ecosystem_20260901_062015'/'shared'/'vm_core'
        preferred.mkdir(parents=True)
        for p in generic.iterdir():
            if p.is_file():
                preferred.joinpath(p.name).write_bytes(p.read_bytes())
        # Remove the generic candidate so the end-to-end recovery must use the exact historical shape.
        import shutil
        shutil.rmtree(self.root/'backups'/'known_good')
        report=self.root/'diagnostics'/'recovery.json'
        rc=self.mod.main(['--root',str(self.root),'--package-root',str(self.package),'--report',str(report)])
        self.assertEqual(rc,0)
        data=json.loads(report.read_text(encoding='utf-8'))
        self.assertIn('pre_v1_4_3_ecosystem_20260901_062015',data['accepted']['source'])
        self.assertEqual(data['accepted']['trust'],98)
        self.assertTrue(all(x['ok'] for x in data['accepted']['tests']))

    @unittest.skipIf(INSTALLED_RUNTIME_SKIP,"package qualification-only recovery simulation")
    def test_preferred_snapshot_is_attempted_before_bounded_fallback(self):
        generic=self.make_candidate()
        preferred=self.root/'backups'/'pre_v1_4_3_ecosystem_20260901_062015'/'shared'/'vm_core'
        preferred.mkdir(parents=True)
        for p in generic.iterdir():
            if p.is_file():
                preferred.joinpath(p.name).write_bytes(p.read_bytes())
        import shutil
        shutil.rmtree(self.root/'backups'/'known_good')
        def forbidden(_root, **kwargs):
            raise AssertionError("bounded fallback must not run after preferred recovery succeeds")
        self.mod.bounded_fallback_candidates=forbidden
        report=self.root/'diagnostics'/'recovery.json'
        rc=self.mod.main(['--root',str(self.root),'--package-root',str(self.package),'--report',str(report)])
        self.assertEqual(rc,0)
        data=json.loads(report.read_text(encoding='utf-8'))
        self.assertIn('pre_v1_4_3_ecosystem',data['accepted']['source'].lower())

    def test_bounded_fallback_has_hard_limits_and_progress(self):
        self.assertGreater(self.mod.MAX_FALLBACK_DIRS,0)
        self.assertGreater(self.mod.MAX_FALLBACK_ZIPS,0)
        self.assertGreater(self.mod.MAX_FALLBACK_SECONDS,0)
        source=self.tool.read_text(encoding='utf-8')
        self.assertIn('time.monotonic()-started>=MAX_FALLBACK_SECONDS',source)
        self.assertIn('dirs_seen>=MAX_FALLBACK_DIRS',source)
        self.assertIn('progress(f"Fallback scan:',source)
        self.assertIn('def shallow_local_candidates',source)

if __name__=='__main__':unittest.main()
