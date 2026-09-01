import unittest
from pathlib import Path

class ReleasePackageTests(unittest.TestCase):
    def test_integration_bundle_collector_exists(self):
        root=Path(__file__).resolve().parents[2]
        p=root/"tools"/"Intelligence"/"PREPARE_INTEGRATION_BUNDLE.ps1"
        self.assertTrue(p.exists())
        text=p.read_text(encoding="utf-8")
        for excluded in (".env","sessions","backups","data","logs"):
            self.assertIn(excluded,text)
        self.assertIn("<REDACTED>",text)
        self.assertIn("trailing comma",text)

if __name__=="__main__": unittest.main()
