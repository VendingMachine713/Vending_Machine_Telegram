from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from shared.vm_core.progress_cli import main


class ProgressCliTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
