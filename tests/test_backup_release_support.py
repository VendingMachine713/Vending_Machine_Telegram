import tempfile,unittest,zipfile,json
from pathlib import Path
from shared.vm_core.backup import create_backup,rollback_preview
from shared.vm_core.support import _redact_text
from shared.vm_core.release import set_baseline,build_delta

class BackupReleaseTests(unittest.TestCase):
    def make_root(self,tmp):
        root=Path(tmp); (root/"bots"/"Demo").mkdir(parents=True); (root/"shared").mkdir()
        (root/"vm.py").write_text("x=1\n"); (root/"VM_PROJECT.json").write_text("{}")
        (root/"bots"/"Demo"/"main.py").write_text("print(1)\n")
        (root/"bots"/"Demo"/".env").write_text("BOT_TOKEN=secret\n")
        (root/"bots"/"Demo"/"primary.session").write_text("private")
        return root
    def test_backup_excludes_env_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=self.make_root(tmp)
            b=create_backup(root)
            with zipfile.ZipFile(b) as z:
                names=z.namelist()
            self.assertFalse(any(n.endswith(".env") for n in names))
            self.assertFalse(any(n.endswith(".session") for n in names))
            self.assertTrue(rollback_preview(b,root)["dry_run"])
    def test_release_delta(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=self.make_root(tmp)
            set_baseline("Demo",root)
            (root/"bots"/"Demo"/"main.py").write_text("print(2)\n")
            result=build_delta("Demo",root)
            self.assertTrue(result["ok"]); self.assertEqual(result["changed_or_new"],1)
    def test_redaction(self):
        self.assertNotIn("abcdef",_redact_text("bot_token=abcdef"))
