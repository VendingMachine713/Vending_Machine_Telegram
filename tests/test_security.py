from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shared.vm_core.security import (
    central_owner_ids,
    group_safe_preflight,
    owner_authorized,
    parse_user_ids,
    write_central_owner_ids,
)


class SecurityIdentityTests(unittest.TestCase):
    def test_parse_user_ids_filters_invalid_and_nonpositive(self):
        self.assertEqual(parse_user_ids("22,11;22,-1,nope,0"), (11, 22))

    def test_missing_identity_fails_closed(self):
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, {}, clear=True):
            root = Path(td)
            self.assertEqual(central_owner_ids(root), ())
            self.assertFalse(owner_authorized(123, root))

    def test_local_identity_authorizes_only_configured_owner(self):
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, {}, clear=True):
            root = Path(td)
            write_central_owner_ids([12345], root)
            self.assertTrue(owner_authorized(12345, root))
            self.assertFalse(owner_authorized(54321, root))

    def test_environment_identity_is_authoritative(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_central_owner_ids([111], root)
            with patch.dict(os.environ, {"VM_OWNER_USER_IDS": "222,333"}, clear=True):
                self.assertEqual(central_owner_ids(root), (222, 333))
                self.assertFalse(owner_authorized(111, root))
                self.assertTrue(owner_authorized(333, root))


class GroupSafePreflightTests(unittest.TestCase):
    def _write(self, root: Path, relative: str, text: str):
        p = root / relative
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def test_preflight_detects_broken_guard_gate(self):
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, {}, clear=True):
            root = Path(td)
            self._write(root, "bots/VM_Guard/main.py", "CommandHandler(\"claim\",claim)\n")
            report = group_safe_preflight(root)
            self.assertFalse(report["group_safe"])
            self.assertGreaterEqual(report["failures"], 1)

    def test_preflight_warns_not_fails_when_central_identity_missing(self):
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, {}, clear=True):
            root = Path(td)
            report = group_safe_preflight(root)
            self.assertTrue(report["group_safe"])
            self.assertEqual(report["failures"], 0)
            self.assertEqual(report["warnings"], 1)


if __name__ == "__main__":
    unittest.main()
