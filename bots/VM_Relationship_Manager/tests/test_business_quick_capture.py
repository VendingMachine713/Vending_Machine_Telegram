from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from business_memory import BusinessMemory
from business_quick_capture import BusinessQuickCapture
from database import Database, utcnow


class BusinessQuickCaptureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "relationships.db")
        self.memory = BusinessMemory(self.db)
        self.quick = BusinessQuickCapture(self.db, self.memory)
        self._seed_contact(3001, "alpha", "Alpha")
        self._seed_contact(3002, "beta", "Beta")

    def tearDown(self):
        self.tmp.cleanup()

    def _seed_contact(self, telegram_id: int, username: str, display_name: str):
        stamp = utcnow()
        self.db.execute(
            """INSERT INTO contacts
               (telegram_id,username,display_name,first_seen,last_seen,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?)""",
            (telegram_id, username, display_name, stamp, stamp, stamp, stamp),
        )

    def test_suggestions_prefer_contact_history_then_global_products(self):
        now = datetime(2026, 9, 5, tzinfo=timezone.utc)
        self.memory.record(3001, "client", "Own Product", occurred_at=now - timedelta(days=5))
        self.memory.record(3001, "client", "Own Product", occurred_at=now - timedelta(days=1))
        self.memory.record(3002, "client", "Global Product", occurred_at=now)

        suggestions = self.quick.suggestions(3001, "client", limit=4)

        self.assertEqual(suggestions[0].name, "Own Product")
        self.assertEqual(suggestions[0].source, "contact_history")
        self.assertEqual(suggestions[0].transaction_count, 2)
        self.assertIn("Global Product", [item.name for item in suggestions])

    def test_new_product_capture_records_one_unit_without_inferred_value(self):
        tx_id = self.quick.record_product_name(
            3001,
            "client",
            "New Product",
            recorded_by=999,
        )
        tx = self.memory.transaction(tx_id)

        self.assertEqual(tx["role"], "client")
        self.assertEqual(tx["product_name"], "New Product")
        self.assertEqual(tx["quantity"], 1)
        self.assertIsNone(tx["total_minor_units"])
        self.assertEqual(tx["source"], "quick_capture_new_product")

    def test_product_button_capture_uses_existing_product_identity(self):
        first = self.memory.record(3002, "supplier", "Reusable Product")
        product_id = int(self.memory.transaction(first)["product_id"])

        tx_id = self.quick.record_product_id(
            3001,
            "client",
            product_id,
            recorded_by=999,
        )
        tx = self.memory.transaction(tx_id)

        self.assertEqual(tx["product_name"], "Reusable Product")
        self.assertEqual(tx["role"], "client")
        self.assertEqual(tx["source"], "quick_capture")

    def test_repeat_last_preserves_role_product_quantity_unit_but_not_old_value(self):
        self.memory.record(
            3001,
            "supplier",
            "Repeat Product",
            quantity=7,
            unit="box",
            total="350.00",
        )

        tx_id = self.quick.repeat_last(3001, recorded_by=999)
        tx = self.memory.transaction(tx_id)

        self.assertEqual(tx["role"], "supplier")
        self.assertEqual(tx["product_name"], "Repeat Product")
        self.assertEqual(tx["quantity"], 7)
        self.assertEqual(tx["unit"], "box")
        self.assertIsNone(tx["total_minor_units"])
        self.assertEqual(tx["source"], "quick_repeat")

    def test_unknown_contact_and_invalid_role_fail_closed(self):
        with self.assertRaises(ValueError):
            self.quick.suggestions(999999, "client")
        with self.assertRaises(ValueError):
            self.quick.record_product_name(3001, "friend", "X", recorded_by=1)

    def test_repeat_last_requires_previous_business_history(self):
        with self.assertRaises(ValueError):
            self.quick.repeat_last(3002, recorded_by=999)


if __name__ == "__main__":
    unittest.main()
