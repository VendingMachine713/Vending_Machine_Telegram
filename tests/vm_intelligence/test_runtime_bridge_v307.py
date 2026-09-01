from __future__ import annotations
import importlib.util, json, os, signal, sys, tempfile, unittest
from pathlib import Path

class RuntimeBridgeV307Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)/"project";self.root.mkdir()
        self.package=Path(__file__).resolve().parents[2]
        tool=self.package/"tools"/"Intelligence"/"RUNTIME_BRIDGE.py"
        spec=importlib.util.spec_from_file_location("runtime_bridge_v307",tool)
        self.mod=importlib.util.module_from_spec(spec);sys.modules[spec.name]=self.mod;spec.loader.exec_module(self.mod)

    def tearDown(self):
        # Kill any direct bridge process created by tests.
        state=self.root/"state"/"runtime_bridge"
        if state.is_dir():
            for p in state.glob("*.pid"):
                try:
                    pid=int(p.read_text().strip())
                    if os.name=="nt":
                        import subprocess
                        subprocess.run(["taskkill","/PID",str(pid),"/T","/F"],capture_output=True)
                    else:
                        os.kill(pid,signal.SIGTERM)
                except Exception:
                    pass
        self.tmp.cleanup()

    def make_bot(self,name,managed=False,main_body="import time\ntime.sleep(30)\n"):
        bot=self.root/"bots"/name;runtime=bot/name/name
        runtime.mkdir(parents=True)
        (runtime/"main.py").write_text(main_body,encoding="utf-8")
        (runtime/"BOT_MANIFEST.json").write_text(json.dumps({
            "name":name,"classification":"CANONICAL","entrypoint":"main.py",
            "entrypoint_confidence":"high","lifecycle":{"auto_start":False,"auto_restart":False}
        }),encoding="utf-8")
        (bot/"BOT_MANIFEST.json").write_text(json.dumps({
            "name":name,"classification":"CANONICAL","entrypoint":None,
            "lifecycle":{"auto_start":False,"auto_restart":False}
        }),encoding="utf-8")
        if managed:
            diag=self.root/"diagnostics";diag.mkdir(exist_ok=True)
            data={"critical_tests_ok":True,"supervisor_actions":[{
                "service":name,"action":"none","alive":True,
                "policy":{"auto_start":True,"auto_restart":True}
            }]}
            (diag/"full_validation.json").write_text(json.dumps(data),encoding="utf-8")
        return bot,runtime

    def test_prepare_creates_root_shim_and_restores_validated_policy(self):
        bot,runtime=self.make_bot("Admin_Command_Centre",managed=True)
        out=self.mod.prepare(self.root,self.root/"backup",True,["Admin_Command_Centre"])
        self.assertTrue(out["ok"])
        row=out["services"][0]
        self.assertTrue(row["desired_running"])
        root_main=bot/"main.py"
        self.assertTrue(root_main.is_file())
        text=root_main.read_text(encoding="utf-8")
        self.assertIn(self.mod.MARKER,text)
        self.assertIn("runpy.run_path",text)
        manifest=json.loads((bot/"BOT_MANIFEST.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["entrypoint"],"main.py")
        self.assertTrue(manifest["lifecycle"]["auto_start"])
        self.assertEqual(manifest["runtime_bridge"]["canonical_target"],str((runtime/"main.py").resolve()))

    def test_existing_real_root_main_is_never_overwritten(self):
        bot,runtime=self.make_bot("VM_Guard",managed=False)
        root_main=bot/"main.py";root_main.write_text("print('real root')\n",encoding="utf-8")
        before=root_main.read_bytes()
        out=self.mod.prepare(self.root,self.root/"backup",True,["VM_Guard"])
        self.assertTrue(out["ok"])
        self.assertEqual(root_main.read_bytes(),before)
        self.assertTrue(out["services"][0]["root_main_existing_non_bridge"])

    def test_shim_executes_nested_runtime_with_nested_cwd_and_project_on_path(self):
        body=(
            "from pathlib import Path\n"
            "import os,sys\n"
            "Path('bridge_probe.json').write_text(str(Path.cwd())+'|'+sys.path[0],encoding='utf-8')\n"
        )
        bot,runtime=self.make_bot("Universal_Search",managed=False,main_body=body)
        state=self.mod.prepare(self.root,None,True,["Universal_Search"])
        row=state["services"][0]
        # Directly execute generated shim; nested runtime exits successfully.
        import subprocess
        r=subprocess.run([sys.executable,str(bot/"main.py")],cwd=bot,capture_output=True,text=True,timeout=10)
        self.assertEqual(r.returncode,0,r.stderr)
        probe=(runtime/"bridge_probe.json").read_text(encoding="utf-8")
        self.assertIn(str(runtime.resolve()),probe)

    def test_ensure_preserves_explicit_stopped_policy(self):
        self.make_bot("VM_Guard",managed=False)
        state=self.mod.prepare(self.root,None,True,["VM_Guard"])
        out=self.mod.ensure(self.root,state)
        self.assertTrue(out["ok"])
        self.assertEqual(out["services"][0]["action"],"preserve_stopped_policy")

    def test_ensure_direct_bridge_starts_managed_nested_runtime(self):
        self.make_bot("Admin_Command_Centre",managed=True)
        state=self.mod.prepare(self.root,None,True,["Admin_Command_Centre"])
        out=self.mod.ensure(self.root,state)
        self.assertTrue(out["ok"])
        row=out["services"][0]
        self.assertTrue(row["status"]["alive"])
        self.assertIn(row["action"],{"direct_bridge","vm_core","already_running"})

    def test_prepare_is_two_phase_and_does_not_partially_modify_on_bad_bot(self):
        good,_=self.make_bot("Admin_Command_Centre",managed=True)
        bad=self.root/"bots"/"VM_Guard";bad.mkdir(parents=True)
        (bad/"BOT_MANIFEST.json").write_text(json.dumps({
            "name":"VM_Guard","classification":"CANONICAL","entrypoint":None
        }),encoding="utf-8")
        before=(good/"BOT_MANIFEST.json").read_bytes()
        out=self.mod.prepare(self.root,self.root/"backup",True,["Admin_Command_Centre","VM_Guard"])
        self.assertFalse(out["ok"])
        self.assertEqual((good/"BOT_MANIFEST.json").read_bytes(),before)
        self.assertFalse((good/"main.py").exists())

if __name__=="__main__":
    unittest.main()
