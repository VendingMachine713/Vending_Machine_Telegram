import json
import tempfile
import unittest
from pathlib import Path

from shared.vm_core.config import load_config, validate_config


class ConfigContractTests(unittest.TestCase):
    def test_nested_defaults_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config").mkdir()
            (root / "config" / "vm_platform.json").write_text(
                json.dumps({"platform": {"timezone": "Australia/Adelaide"}}),
                encoding="utf-8",
            )
            cfg = load_config(root)
            self.assertEqual(cfg["platform"]["timezone"], "Australia/Adelaide")
            self.assertTrue(cfg["platform"]["default_dry_run"])
            self.assertIn("name", cfg["platform"])

    def test_support_bundle_secret_exposure_is_rejected(self):
        cfg = load_config(Path("/path/that/does/not/exist"))
        cfg["support_bundle"]["include_env_files"] = True
        issues = validate_config(cfg)
        self.assertIn(
            "CONFIG_SUPPORT_SECRET_EXPOSURE",
            {issue["code"] for issue in issues},
        )


if __name__ == "__main__":
    unittest.main()
