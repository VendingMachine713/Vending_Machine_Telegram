import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

from backfill import clamp_args, sender_fields, status_text
from core import Store


class FakeSender:
    id = 123
    username = "bob"
    first_name = "Bob"
    last_name = "Smith"
    title = None


class BackfillHelpersTests(unittest.TestCase):
    def test_clamp_args(self):
        args = Namespace(limit=999999, batch_size=1, days=99999)
        clamp_args(args)
        self.assertEqual(args.limit, 100000)
        self.assertEqual(args.batch_size, 25)
        self.assertEqual(args.days, 3650)

    def test_sender_fields(self):
        self.assertEqual(sender_fields(FakeSender()), (123, "bob", "Bob Smith"))
        self.assertEqual(sender_fields(None), (None, None, None))

    def test_status_text(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d) / "x.db")
            self.assertIn("No historical", status_text(s))
            s.record_backfill_progress(-1001, "Test", None, status="running",
                                       oldest_message_id=20, scanned_delta=5)
            text = status_text(s)
            self.assertIn("-1001", text)
            self.assertIn("scanned=5", text)


if __name__ == "__main__":
    unittest.main()
