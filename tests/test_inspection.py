import tempfile,unittest
from pathlib import Path
from shared.vm_core.inspect import build_structure_report

class InspectionTests(unittest.TestCase):
    def test_env_is_not_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); bot=root/"bots"/"Demo"; bot.mkdir(parents=True)
            (bot/"main.py").write_text("print('ok')\n")
            (bot/".env").write_text("SECRET=do-not-read\n")
            report=build_structure_report(root)
            tree=report["bots"][0]["tree"]
            self.assertIn(".env [REDACTED FILE]",tree)
            self.assertFalse(any("do-not-read" in x for x in tree))
