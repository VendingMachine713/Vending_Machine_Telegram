import json,tempfile,unittest
from pathlib import Path
from shared.vm_core.runtime_requirements import runtime_configuration_status
from shared.vm_core.health import run_health
class V12RuntimeTests(unittest.TestCase):
    def test_config_required_health(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); bot=root/'bots'/'ConfiguredBot'; bot.mkdir(parents=True); (bot/'main.py').write_text('x=1'); (bot/'BOT_MANIFEST.json').write_text(json.dumps({'runtime_requirements':{'env':['NEEDED_KEY']}})); self.assertEqual(run_health(root)[0]['status'],'CONFIG_REQUIRED')
    def test_dotenv_value_not_exposed(self):
        with tempfile.TemporaryDirectory() as tmp:
            bot=Path(tmp); (bot/'BOT_MANIFEST.json').write_text(json.dumps({'runtime_requirements':{'env':['SECRET_KEY']}})); (bot/'.env').write_text('SECRET_KEY=supersecret\n'); st=runtime_configuration_status(bot); self.assertTrue(st['configured']); self.assertNotIn('supersecret',json.dumps(st))
