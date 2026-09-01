from __future__ import annotations
import importlib.util,tempfile,unittest,sys,json,os,signal,subprocess,time
from pathlib import Path

class AdminRuntimeGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)/"project";self.root.mkdir()
        self.package=Path(__file__).resolve().parents[2]
        p=self.package/"tools"/"Intelligence"/"ADMIN_RUNTIME_GATE.py"
        spec=importlib.util.spec_from_file_location("admin_runtime_gate",p)
        self.mod=importlib.util.module_from_spec(spec);sys.modules[spec.name]=self.mod;spec.loader.exec_module(self.mod)
        bot=self.root/"bots"/"Admin_Command_Centre";runtime=bot/"Admin_Command_Centre"/"Admin_Command_Centre"
        runtime.mkdir(parents=True)
        (bot/"BOT_MANIFEST.json").write_text(json.dumps({"name":"Admin_Command_Centre","classification":"CANONICAL","entrypoint":None}),encoding="utf-8")
        (runtime/"main.py").write_text("import time\ntime.sleep(30)\n",encoding="utf-8")
        (runtime/"BOT_MANIFEST.json").write_text(json.dumps({
            "name":"Admin_Command_Centre","classification":"CANONICAL","entrypoint":"main.py",
            "entrypoint_confidence":"high","lifecycle":{"auto_start":True,"auto_restart":True}
        }),encoding="utf-8")

    def _stop_pid(self,pid):
        if not pid:return
        pid=int(pid)
        if os.name=="nt":
            subprocess.run(["taskkill","/PID",str(pid),"/T","/F"],
                           capture_output=True,text=True,timeout=15)
        else:
            try:os.kill(pid,signal.SIGTERM)
            except ProcessLookupError:return
            except Exception:pass
        deadline=time.time()+10
        while time.time()<deadline:
            if os.name!="nt":
                try:
                    waited,_=os.waitpid(pid,os.WNOHANG)
                    if waited==pid:return
                except ChildProcessError:
                    if not self.mod.pid_alive(pid):return
            elif not self.mod.pid_alive(pid):
                return
            time.sleep(.1)
        if os.name!="nt":
            try:os.kill(pid,signal.SIGKILL)
            except Exception:pass
            try:os.waitpid(pid,0)
            except Exception:pass

    def tearDown(self):
        pid_file=self.root/"state"/"pids"/"Admin_Command_Centre.pid"
        if pid_file.is_file():
            try:self._stop_pid(int(pid_file.read_text(encoding="ascii").strip()))
            except Exception:pass
        # Windows may release a process cwd/file handle fractionally after taskkill returns.
        deadline=time.time()+5
        last=None
        while time.time()<deadline:
            try:
                self.tmp.cleanup()
                return
            except PermissionError as exc:
                last=exc
                time.sleep(.1)
        if last:raise last

    def test_status_resolves_nested_canonical_even_without_vm_core_status(self):
        s=self.mod.status(self.root,self.package,"Admin_Command_Centre")
        self.assertTrue(s["ok"])
        self.assertTrue(s["selected"]["entrypoint_abs"].endswith("main.py"))

    def test_preserve_stopped_policy_never_launches(self):
        r=self.mod.ensure(self.root,self.package,"Admin_Command_Centre",False)
        self.assertTrue(r["ok"])
        self.assertEqual(r["method"],"preserve_stopped_policy")

    @unittest.skipIf(os.environ.get("VM_INTELLIGENCE_INSTALLED_RUNTIME","").lower() in {"1","true","yes"},
                     "package qualification-only legacy process fallback simulation")
    def test_direct_fallback_starts_validated_entrypoint_when_vm_core_is_unavailable(self):
        # Unit-test the direct fallback itself. Do not call ensure(), because that can
        # consult a real/shared VM Core imported elsewhere in the full test process.
        repair=self.mod.load_repair_tool(self.package)
        selected=repair.discover_runtime(self.root,"Admin_Command_Centre")["selected"]
        r=self.mod.direct_start(self.root,selected,"Admin_Command_Centre")
        self.assertTrue(r["ok"],r)
        self.assertEqual(r["method"],"direct_canonical_entrypoint")
        pid=r.get("pid")
        self.assertTrue(pid and self.mod.pid_alive(pid))
        self._stop_pid(pid)
        self.assertFalse(self.mod.pid_alive(pid))

if __name__=="__main__":unittest.main()
