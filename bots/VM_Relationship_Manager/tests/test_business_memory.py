from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from business_memory import BusinessMemory, parse_money
from database import Database, utcnow


class BusinessMemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "relationships.db")
        self.memory = BusinessMemory(self.db)
        self._seed_contact(1001, "alice", "Alice")
        self._seed_contact(1002, "bob", "Bob")
        self._seed_contact(1003, "charlie", "Charlie")

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

    def test_money_parsing_uses_minor_units(self):
        money = parse_money("120.505")
        self.assertEqual(money.minor_units, 12051)
        self.assertEqual(money.currency, "AUD")
        with self.assertRaises(ValueError):
            parse_money("-1")

    def test_record_creates_product_history_tags_and_audit(self):
        tx_id = self.memory.record(
            1001,
            "client",
            "Product Alpha",
            quantity=2,
            total="120.50",
            recorded_by=999,
            note="first order",
        )
        tx = self.memory.transaction(tx_id)
        self.assertEqual(tx["telegram_id"], 1001)
        self.assertEqual(tx["role"], "client")
        self.assertEqual(tx["product_name"], "Product Alpha")
        self.assertEqual(tx["total_minor_units"], 12050)

        # Product identity is normalized so capitalization/spacing variants do
        # not fragment the client's history.
        self.memory.record(1001, "client", "  product   alpha ", quantity=1)
        self.assertEqual(
            self.db.one("SELECT COUNT(*) AS n FROM business_products")["n"],
            1,
        )
        self.assertIsNotNone(
            self.db.one(
                "SELECT 1 FROM tags WHERE telegram_id=? AND tag='client'",
                (1001,),
            )
        )
        self.assertIsNotNone(
            self.db.one(
                """SELECT 1 FROM relationship_events
                   WHERE telegram_id=? AND event_type='business_transaction_recorded'""",
                (1001,),
            )
        )
        self.assertIsNotNone(
            self.db.one(
                """SELECT 1 FROM admin_audit
                   WHERE admin_id=? AND telegram_id=? AND action='business_transaction_recorded'""",
                (999, 1001),
            )
        )

        summary = self.memory.contact_summary(1001)
        self.assertEqual(summary["roles"]["client"]["transaction_count"], 2)
        self.assertEqual(summary["roles"]["client"]["total_quantity"], 3)
        self.assertEqual(summary["roles"]["client"]["aud_minor"], 12050)

    def test_contact_can_be_both_client_and_supplier(self):
        self.memory.record(1002, "client", "Product A")
        self.memory.record(1002, "supplier", "Product B", quantity=5)
        tags = {
            row["tag"]
            for row in self.db.all("SELECT tag FROM tags WHERE telegram_id=?", (1002,))
        }
        self.assertEqual(tags, {"client", "supplier"})
        summary = self.memory.contact_summary(1002)
        self.assertIn("client", summary["roles"])
        self.assertIn("supplier", summary["roles"])

    def test_top_clients_and_reload_candidates_rank_repeat_history(self):
        now = datetime.now(timezone.utc)
        self.memory.record(1001, "client", "Reload Item", quantity=2, occurred_at=now)
        self.memory.record(1001, "client", "Reload Item", quantity=3, occurred_at=now)
        self.memory.record(1002, "client", "Reload Item", quantity=10, occurred_at=now)
        self.memory.record(1003, "client", "Other Item", quantity=100, occurred_at=now)

        top = self.memory.top_clients(product="reload item")
        self.assertEqual([row["telegram_id"] for row in top[:2]], [1001, 1002])
        reload_rows = self.memory.reload_candidates("RELOAD ITEM")
        self.assertEqual([row["telegram_id"] for row in reload_rows], [1001, 1002])
        self.assertEqual(reload_rows[0]["transaction_count"], 2)

    def test_touchbase_candidates_only_include_inactive_clients(self):
        old = datetime.now(timezone.utc) - timedelta(days=45)
        recent = datetime.now(timezone.utc) - timedelta(days=5)
        self.memory.record(1001, "client", "A", occurred_at=old)
        self.memory.record(1002, "client", "A", occurred_at=recent)
        self.memory.record(1003, "supplier", "A", occurred_at=old)

        rows = self.memory.touchbase_candidates(inactive_days=30)
        self.assertEqual([row["telegram_id"] for row in rows], [1001])

    def test_invalid_records_fail_closed(self):
        with self.assertRaises(ValueError):
            self.memory.record(9999, "client", "A")
        with self.assertRaises(ValueError):
            self.memory.record(1001, "other", "A")
        with self.assertRaises(ValueError):
            self.memory.record(1001, "client", "A", quantity=0)
        with self.assertRaises(ValueError):
            self.memory.record(1001, "client", "A", total="not-money")

    def test_overview_counts_unique_people_and_transactions(self):
        self.memory.record(1001, "client", "A")
        self.memory.record(1001, "client", "A")
        self.memory.record(1002, "supplier", "B")
        self.memory.record(1002, "client", "B")
        overview = self.memory.overview()
        self.assertEqual(overview["clients"], 2)
        self.assertEqual(overview["suppliers"], 1)
        self.assertEqual(overview["products"], 2)
        self.assertEqual(overview["transactions"], 4)


if __name__ == "__main__":
    unittest.main()
