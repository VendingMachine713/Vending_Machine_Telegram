import importlib.util,tempfile,unittest
from pathlib import Path

class AdminPatchTests(unittest.TestCase):
    def _module(self):
        root=Path(__file__).resolve().parents[2]
        p=root/"tools"/"Intelligence"/"PATCH_ADMIN_INTELLIGENCE.py"
        spec=importlib.util.spec_from_file_location("patch_admin_intel",p)
        mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
        return mod

    def fixture(self):
        return """from shared.vm_core.manifests import discover_bots

def is_admin(user_id,cfg):
    return True

def help_text(cfg):
    return (
        "/whoami - show your Telegram user ID\\n\\n"
        "Controlled lifecycle:\\n"
    )

def handle_command(user_id:int,text:str,cfg=None):
    cmd,args=("brain",[])
    if not is_admin(user_id,cfg):
        return "Access denied."

    if cmd in {"vm","help",""}: return help_text(cfg)
    return "old"
"""

    def test_patch_is_idempotent_and_after_auth(self):
        mod=self._module()
        patched,changed=mod.patch_text(self.fixture())
        self.assertTrue(changed)
        self.assertIn("VM_INTELLIGENCE_V3_DISPATCH_BEGIN",patched)
        self.assertLess(patched.index('return "Access denied."'),patched.index("is_intelligence_command(cmd)"))
        again,changed2=mod.patch_text(patched)
        self.assertFalse(changed2);self.assertEqual(again,patched)


    def test_main_refuses_invalid_original_source_before_write(self):
        import tempfile
        mod=self._module()
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            target=root/"bots"/"Admin_Command_Centre"/"admin_core.py"
            target.parent.mkdir(parents=True)
            invalid='from shared.vm_core.manifests import discover_bots\n\ndef handle_command(user_id,text,cfg=None):\n    return {\n        "token":"x"\n        "admin_ids":set(),\n    }\n'
            target.write_text(invalid,encoding="utf-8")
            backup=root/"backup"
            with self.assertRaises(SystemExit):
                mod.main(["--root",str(root),"--backup-dir",str(backup),"--apply"])
            self.assertEqual(target.read_text(encoding="utf-8"),invalid)

    def test_patch_refuses_unknown_structure(self):
        mod=self._module()
        with self.assertRaises(RuntimeError):
            mod.patch_text("def handle_command(): pass\n")

if __name__=="__main__":
    unittest.main()
