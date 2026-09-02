import tempfile,unittest
from pathlib import Path
from shared.vm_core.services import start_service

class ServiceTests(unittest.TestCase):
    def test_start_defaults_to_dry_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); bot=root/"bots"/"Demo"; bot.mkdir(parents=True)
            (bot/"main.py").write_text("print('ok')\n")
            r=start_service("Demo",root,dry_run=True)
            self.assertTrue(r["ok"]); self.assertTrue(r["dry_run"])
