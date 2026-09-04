import json
import tempfile
import unittest
from pathlib import Path

from shared.vm_core.recovery_policy import load_recovery_policy, service_recovery_policy


class RecoveryPolicyTests(unittest.TestCase):
    def test_default_policy_is_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = load_recovery_policy(Path(tmp))
            self.assertFalse(p["enabled"])
            self.assertFalse(p["apply_safe"])

    def test_central_override_requires_managed_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config").mkdir()
            (root / "config" / "vm_recovery_policy.json").write_text(json.dumps({
                "enabled": True,
                "services": {"Demo": {"auto_restart": True}}
            }), encoding="utf-8")
            unmanaged = service_recovery_policy("Demo", {"managed_by_vm": False}, root)
            managed = service_recovery_policy("Demo", {"managed_by_vm": True}, root)
            self.assertFalse(unmanaged["auto_restart"])
            self.assertTrue(managed["auto_restart"])


if __name__ == "__main__":
    unittest.main()
