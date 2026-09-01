import importlib.util
import tempfile
import unittest
from pathlib import Path

TOOL=Path(__file__).resolve().parents[1]/'tools'/'restore_vm_snapshot.py'
spec=importlib.util.spec_from_file_location('vm_restore_snapshot',TOOL)
mod=importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)

class SnapshotRestoreTests(unittest.TestCase):
    def test_verified_restore_and_safety_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'project'; root.mkdir()
            snap=root/'backups'/'pre_v1_4_ecosystem_20260901_010101'; snap.mkdir(parents=True)
            for rel,text in {
                'vm.py':'old\n',
                'shared/a.py':'old shared\n',
                'bots/Universal_Search/main.py':'old search\n',
            }.items():
                p=snap/rel; p.parent.mkdir(parents=True,exist_ok=True); p.write_text(text)
            for rel,text in {
                'vm.py':'new\n',
                'shared/a.py':'new shared\n',
                'bots/Universal_Search/main.py':'new search\n',
                'VM_CONTROL.bat':'new-only\n',
            }.items():
                p=root/rel; p.parent.mkdir(parents=True,exist_ok=True); p.write_text(text)
            result=mod.restore(root,snap,apply=True,make_safety_backup=True)
            self.assertTrue(result['ok'],result)
            self.assertEqual((root/'vm.py').read_text(),'old\n')
            self.assertFalse((root/'VM_CONTROL.bat').exists())
            self.assertTrue(Path(result['safety_backup']).is_dir())
            self.assertTrue(all(x['matches_snapshot'] for x in result['verification']))

    def test_refuses_unexpected_snapshot_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'project'; root.mkdir()
            snap=root/'backups'/'random_folder'; snap.mkdir(parents=True)
            result=mod.restore(root,snap,apply=True)
            self.assertFalse(result['ok'])
            self.assertFalse(result['applied'])

if __name__=='__main__': unittest.main()
