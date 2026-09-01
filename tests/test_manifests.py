import json,tempfile,unittest
from pathlib import Path
from shared.vm_core.manifests import discover_bots,create_missing_bot_manifests

class ManifestTests(unittest.TestCase):
    def test_discovery_and_preservation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); bot=root/"bots"/"Example"; bot.mkdir(parents=True)
            (bot/"main.py").write_text("print('ok')\n",encoding="utf-8")
            found=discover_bots(root)
            self.assertEqual(found[0].entrypoint,"main.py")
            create_missing_bot_manifests(root,write=True)
            mf=bot/"BOT_MANIFEST.json"
            data=json.loads(mf.read_text(encoding="utf-8")); data["sentinel"]="keep"
            mf.write_text(json.dumps(data),encoding="utf-8")
            create_missing_bot_manifests(root,write=True)
            self.assertEqual(json.loads(mf.read_text(encoding="utf-8"))["sentinel"],"keep")
