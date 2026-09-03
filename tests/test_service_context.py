import json
import tempfile
import unittest
from pathlib import Path

from shared.vm_core.service_context import service_context


class ServiceContextTests(unittest.TestCase):
    def _root(self, tmp: str) -> Path:
        root = Path(tmp)
        bot = root / "bots" / "Demo"
        bot.mkdir(parents=True)
        (bot / "main.py").write_text("print('ok')\n", encoding="utf-8")
        (bot / "BOT_MANIFEST.json").write_text(json.dumps({
            "schema_version": 3,
            "name": "Demo",
            "version": "2.0.0",
            "classification": "CANONICAL",
            "entrypoint": "main.py",
            "launchers": [],
            "capabilities": ["status", "search"],
            "runtime_requirements": {"env": ["BOT_TOKEN"]},
            "vm_core": {"compatible": True},
            "lifecycle": {"managed_by_vm": True, "auto_start": False, "auto_restart": False},
        }), encoding="utf-8")
        return root

    def test_context_resolves_identity_paths_and_capabilities(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            ctx = service_context("demo", root)
            self.assertEqual(ctx.name, "Demo")
            self.assertEqual(ctx.version, "2.0.0")
            self.assertEqual(ctx.capabilities, ("search", "status"))
            self.assertEqual(ctx.runtime_required_env, ("BOT_TOKEN",))
            self.assertEqual(ctx.bot_path("main.py"), root / "bots" / "Demo" / "main.py")
            self.assertEqual(ctx.state_path("runtime.json"), root / "state" / "Demo" / "runtime.json")

    def test_context_shared_log_redacts_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            ctx = service_context("Demo", root)
            path = ctx.log("test", data={"bot_token": "do-not-store"})
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("do-not-store", text)
            self.assertIn("[REDACTED]", text)

    def test_unknown_service_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            with self.assertRaises(KeyError):
                service_context("missing", root)


if __name__ == "__main__":
    unittest.main()
