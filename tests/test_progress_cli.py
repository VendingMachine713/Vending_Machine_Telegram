from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from shared.vm_core.progress_cli import main
from shared.vm_core.progress_registry import platform_progress_summary, provider_names


class ProgressCliTests(unittest.TestCase):
    def test_registry_exposes_initial_cross_bot_providers(self):
        self.assertIn("autoposter", provider_names())
        self.assertIn("guard", provider_names())

    def test_text_mode_is_safe_when_autoposter_database_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = io.StringIO()
            with redirect_stdout(output):
                rc = main(["autoposter", "--root", str(root)])
            self.assertEqual(rc, 0)
            text = output.getvalue()
            self.assertIn("SMART AUTO POSTER", text)
            self.assertIn("Queue unavailable", text)
            self.assertIn("RECOVERY / NEXT ACTION", text)

    def test_default_all_mode_renders_platform_header_and_registered_surfaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = io.StringIO()
            with redirect_stdout(output):
                rc = main(["--root", tmp])
            self.assertEqual(rc, 0)
            text = output.getvalue()
            self.assertIn("UNIVERSAL PROGRESS ENGINE", text)
            self.assertIn("SMART AUTO POSTER", text)
            self.assertIn("VM GUARD", text)

    def test_json_mode_emits_structured_progress_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = io.StringIO()
            with redirect_stdout(output):
                rc = main(["autoposter", "--json", "--root", str(root)])
            self.assertEqual(rc, 0)
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["headline"], "SMART AUTO POSTER")
            self.assertIn("overall", payload)
            self.assertIn("recovery_messages", payload)

    def test_all_json_mode_emits_summary_and_surfaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = io.StringIO()
            with redirect_stdout(output):
                rc = main(["all", "--json", "--root", tmp])
            self.assertEqual(rc, 0)
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["surface_count"], 2)
            self.assertIn("autoposter", payload["surfaces"])
            self.assertIn("guard", payload["surfaces"])
            direct = platform_progress_summary(Path(tmp))
            self.assertEqual(payload["attention_count"], direct["attention_count"])


if __name__ == "__main__":
    unittest.main()
