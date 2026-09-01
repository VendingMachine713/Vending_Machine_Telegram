import importlib.util, os, subprocess, sys, tempfile, unittest
from pathlib import Path

class RegressionDiscovery302Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
        (self.root/'bots').mkdir()
        pkg=Path(__file__).resolve().parents[2]
        path=pkg/'tools'/'Intelligence'/'DISCOVER_BOT_TESTS.py'
        spec=importlib.util.spec_from_file_location('discover_bot_tests',path)
        self.mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(self.mod)
    def tearDown(self): self.tmp.cleanup()

    def test_manifest_canonical_tests_beat_foreign_development_source(self):
        bot=self.root/'bots'/'VM_Relationship_Manager'; bot.mkdir()
        canon=bot/'VM_Relationship_Manager'; (canon/'tests').mkdir(parents=True); (canon/'main.py').write_text('')
        (canon/'BOT_MANIFEST.json').write_text('{"name":"VM_Relationship_Manager","entrypoint":"main.py","classification":"CANONICAL","entrypoint_confidence":"high","lifecycle":{"auto_restart":false}}')
        foreign=bot/'Smart_Auto_Poster_V3_4_Development_Source'/'bot_source'; (foreign/'tests').mkdir(parents=True)
        (foreign/'main.py').write_text('')
        (foreign/'BOT_MANIFEST.json').write_text('{"name":"Smart_Auto_Poster_V2","entrypoint":"main.py","classification":"CANONICAL","lifecycle":{"auto_restart":false}}')
        out=self.mod.discover(self.root,'VM_Relationship_Manager')
        self.assertTrue(out['available'])
        self.assertEqual(Path(out['test_dir']).resolve(),(canon/'tests').resolve())
        self.assertNotIn('Smart_Auto_Poster',out['test_dir'])

    def test_direct_tests_win(self):
        bot=self.root/'bots'/'Smart_Auto_Poster_V2'; (bot/'tests').mkdir(parents=True)
        other=bot/'nested'; (other/'tests').mkdir(parents=True)
        out=self.mod.discover(self.root,'Smart_Auto_Poster_V2')
        self.assertEqual(Path(out['test_dir']).resolve(),(bot/'tests').resolve())

    def test_explicit_runner_imports_project_shared_package(self):
        (self.root/'shared'/'vm_core').mkdir(parents=True)
        pkg=Path(__file__).resolve().parents[2]
        (self.root/'shared'/'__init__.py').write_text((pkg/'shared'/'__init__.py').read_text(encoding='utf-8'),encoding='utf-8')
        (self.root/'shared'/'vm_core'/'__init__.py').write_text('VALUE=42\n')
        bot=self.root/'bots'/'Admin_Command_Centre'; suite=bot/'Admin_Command_Centre'; tests=suite/'tests'
        tests.mkdir(parents=True)
        (tests/'test_import.py').write_text(
            'import unittest\nfrom shared.vm_core import VALUE\nclass T(unittest.TestCase):\n    def test_value(self): self.assertEqual(VALUE,42)\n')
        runner=pkg/'tools'/'Intelligence'/'RUN_TEST_SUITE.py'
        result=subprocess.run([sys.executable,str(runner),'--root',str(self.root),'--suite-root',str(suite),
                               '--test-dir',str(tests),'--bot-root',str(bot)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stdout+'\n'+result.stderr)

    def test_shared_boundary_repair_beats_hostile_regular_shared_package(self):
        # Reproduce the Windows failure: project shared/ is namespace-only while a
        # regular third-party package named shared exists later on sys.path.
        project=self.root
        vm_core=project/'shared'/'vm_core'; vm_core.mkdir(parents=True)
        (vm_core/'__init__.py').write_text('VALUE=77\n')
        hostile=project/'hostile_site'; (hostile/'shared').mkdir(parents=True)
        (hostile/'shared'/'__init__.py').write_text('HOSTILE=True\n')
        pkg=Path(__file__).resolve().parents[2]
        probe=pkg/'tools'/'Intelligence'/'PROBE_SHARED_IMPORT.py'
        env=os.environ.copy(); env['PYTHONPATH']=str(hostile)
        before=subprocess.run([sys.executable,str(probe),'--root',str(project)],capture_output=True,text=True,env=env)
        self.assertNotEqual(before.returncode,0,before.stdout+before.stderr)
        (project/'shared'/'__init__.py').write_text((pkg/'shared'/'__init__.py').read_text(encoding='utf-8'),encoding='utf-8')
        after=subprocess.run([sys.executable,str(probe),'--root',str(project)],capture_output=True,text=True,env=env)
        self.assertEqual(after.returncode,0,after.stdout+after.stderr)

if __name__=='__main__': unittest.main()
