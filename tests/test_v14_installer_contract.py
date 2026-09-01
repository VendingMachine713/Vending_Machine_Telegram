import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

class V14InstallerContractTests(unittest.TestCase):
    def test_installer_is_relationship_preview_only(self):
        text=(ROOT/'INSTALL_VM_ECOSYSTEM.ps1').read_text(encoding='utf-8')
        self.assertIn('py .\\vm.py relationship-cleanup',text)
        self.assertNotIn('relationship-cleanup --apply',text)

    def test_installer_has_snapshot_rollback_runtime_and_readable_support(self):
        text=(ROOT/'INSTALL_VM_ECOSYSTEM.ps1').read_text(encoding='utf-8')
        for required in (
            'VM_PREINSTALL_SNAPSHOT','Restore-VM14Preinstall','validate-all',
            'runtime-check --require-autostart --require-legacy-components',
            'support-text','VM_SUPPORT_READABLE.txt'
        ):
            self.assertIn(required,text)

    def test_cmd_wrapper_creates_pre_v14_snapshot_before_extract(self):
        text=(ROOT/'INSTALL_VM_ECOSYSTEM_v1.4_FROM_CMD.bat').read_text(encoding='utf-8')
        self.assertIn('pre_v1_4_ecosystem_',text)
        self.assertIn('Expand-Archive',text)
        self.assertLess(text.index('pre_v1_4_ecosystem_'),text.index('Expand-Archive'))

    def test_manual_rollback_helper_exists(self):
        self.assertTrue((ROOT/'ROLLBACK_VM_v1.4.bat').is_file())
        self.assertTrue((ROOT/'ROLLBACK_VM_v1.4.ps1').is_file())

if __name__=='__main__':
    unittest.main()
