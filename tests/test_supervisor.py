import json,tempfile,unittest
from pathlib import Path
from shared.vm_core.manifests import create_missing_bot_manifests
from shared.vm_core.supervisor import supervise_once

class SupervisorTests(unittest.TestCase):
    def test_supervisor_defaults_to_no_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); bot=root/'bots'/'Demo'; bot.mkdir(parents=True)
            (bot/'main.py').write_text("print('ok')\n")
            create_missing_bot_manifests(root,write=True)
            actions=supervise_once(root,apply=False)
            self.assertEqual(actions[0]['action'],'none')
