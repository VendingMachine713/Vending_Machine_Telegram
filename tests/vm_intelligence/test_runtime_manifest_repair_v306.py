from __future__ import annotations
import importlib.util,json,tempfile,unittest,sys,subprocess,os
from pathlib import Path

class RuntimeManifestRepairTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)/"project";self.root.mkdir()
        self.package=Path(__file__).resolve().parents[2]
        tool=self.package/"tools"/"Intelligence"/"REPAIR_RUNTIME_MANIFESTS.py"
        spec=importlib.util.spec_from_file_location("runtime_repair",tool)
        self.mod=importlib.util.module_from_spec(spec);sys.modules[spec.name]=self.mod;spec.loader.exec_module(self.mod)

    def tearDown(self):self.tmp.cleanup()

    def make_bot(self,name,depth=3,auto=True):
        outer=self.root/"bots"/name;outer.mkdir(parents=True)
        (outer/"BOT_MANIFEST.json").write_text(json.dumps({
            "name":name,"classification":"CANONICAL","entrypoint":None,
            "lifecycle":{"auto_start":auto,"auto_restart":auto}
        }),encoding="utf-8")
        runtime=outer
        for _ in range(depth-1):runtime=runtime/name
        runtime.mkdir(parents=True,exist_ok=True)
        (runtime/"main.py").write_text("print('ok')\n",encoding="utf-8")
        (runtime/"BOT_MANIFEST.json").write_text(json.dumps({
            "name":name,"classification":"CANONICAL","entrypoint":"main.py",
            "entrypoint_confidence":"high","lifecycle":{"auto_start":auto,"auto_restart":auto}
        }),encoding="utf-8")
        return outer,runtime

    def test_repairs_null_outer_entrypoint_to_nested_canonical(self):
        outer,runtime=self.make_bot("Admin_Command_Centre")
        backup=self.root/"backup"
        r=self.mod.repair_outer_manifest(self.root,"Admin_Command_Centre",backup,apply=True)
        self.assertTrue(r["changed"]);self.assertTrue(r["applied"])
        data=json.loads((outer/"BOT_MANIFEST.json").read_text(encoding="utf-8"))
        self.assertEqual((outer/Path(data["entrypoint"])).resolve(),(runtime/"main.py").resolve())
        self.assertEqual(data["classification"],"CANONICAL")
        self.assertTrue((backup/"runtime_manifests"/"Admin_Command_Centre"/"BOT_MANIFEST.json").is_file())

    def test_preserves_already_valid_outer_entrypoint(self):
        outer,runtime=self.make_bot("Universal_Search",depth=1)
        data=json.loads((outer/"BOT_MANIFEST.json").read_text(encoding="utf-8"))
        data["entrypoint"]="main.py"
        (outer/"BOT_MANIFEST.json").write_text(json.dumps(data),encoding="utf-8")
        r=self.mod.repair_outer_manifest(self.root,"Universal_Search",None,apply=False)
        self.assertFalse(r["changed"])

    def test_prefers_canonical_manifest_with_existing_entrypoint(self):
        outer,runtime=self.make_bot("VM_Guard",depth=3)
        bad=outer/"old_copy";bad.mkdir()
        (bad/"BOT_MANIFEST.json").write_text(json.dumps({
            "name":"VM_Guard","classification":"CANONICAL","entrypoint":"missing.py","entrypoint_confidence":"high"
        }),encoding="utf-8")
        r=self.mod.discover_runtime(self.root,"VM_Guard")
        self.assertTrue(r["ok"])
        self.assertEqual(Path(r["selected"]["entrypoint_abs"]).resolve(),(runtime/"main.py").resolve())

    def test_copies_lifecycle_without_forcing_autostart(self):
        outer,runtime=self.make_bot("VM_Relationship_Manager",depth=2,auto=False)
        # Remove lifecycle from outer; selected canonical lifecycle should be copied exactly.
        d=json.loads((outer/"BOT_MANIFEST.json").read_text(encoding="utf-8"));d.pop("lifecycle")
        (outer/"BOT_MANIFEST.json").write_text(json.dumps(d),encoding="utf-8")
        r=self.mod.repair_outer_manifest(self.root,"VM_Relationship_Manager",None,apply=False)
        self.assertFalse(r["auto_start"]);self.assertFalse(r["auto_restart"])

    @unittest.skipIf(os.environ.get("VM_INTELLIGENCE_INSTALLED_RUNTIME") == "1",
                     "legacy v3.0.6 manifest-rewrite acceptance path; superseded by runtime bridge in live installs")
    def test_cli_repairs_three_managed_nested_bots_and_vm_core_accepts_them(self):
        for name in ("Admin_Command_Centre","Universal_Search","VM_Guard"):
            self.make_bot(name,depth=3,auto=True)
        shared=self.root/"shared";core=shared/"vm_core";core.mkdir(parents=True)
        (shared/"__init__.py").write_text("",encoding="utf-8")
        (core/"__init__.py").write_text("",encoding="utf-8")
        (core/"services.py").write_text(
            "import json\n"
            "from pathlib import Path\n"
            "def service_status(root):\n"
            " out=[]\n"
            " for b in ('Admin_Command_Centre','Universal_Search','VM_Guard'):\n"
            "  p=Path(root)/'bots'/b/'BOT_MANIFEST.json'; d=json.loads(p.read_text())\n"
            "  out.append({'name':b,'entrypoint':d.get('entrypoint'),'launcher':d.get('launcher'),'process_alive':False})\n"
            " return out\n"
            "def restart_service(name,root,dry_run=False,background=True):\n"
            " row=next((x for x in service_status(root) if x['name']==name),None)\n"
            " if not row or not (row.get('entrypoint') or row.get('launcher')):\n"
            "  return {'ok':True,'start':{'ok':False,'reason':'No runnable entrypoint or launcher detected.'}}\n"
            " return {'ok':True,'start':{'ok':True,'dry_run':dry_run}}\n",
            encoding="utf-8")
        report=self.root/"diagnostics"/"runtime_repair.json"
        backup=self.root/"backup"
        env=os.environ.copy()
        # Isolate the subprocess from the release workspace so the synthetic VM Core
        # stub is authoritative. This legacy compatibility test must never import the
        # real package's shared.vm_core through inherited PYTHONPATH.
        env["PYTHONPATH"]=str(self.root)
        r=subprocess.run([sys.executable,str(self.package/"tools"/"Intelligence"/"REPAIR_RUNTIME_MANIFESTS.py"),
                          "--root",str(self.root),"--backup-dir",str(backup),"--report",str(report),
                          "--apply","--verify-services"],capture_output=True,text=True,env=env,timeout=20)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        data=json.loads(report.read_text(encoding="utf-8"))
        self.assertTrue(data["ok"])
        self.assertTrue(data["vm_core_verification"]["ok"])
        for row in data["bots"]:
            self.assertTrue(row["applied"])
            self.assertTrue(Path(row["selected"]["entrypoint_abs"]).is_file())

if __name__=="__main__":unittest.main()
