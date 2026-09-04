from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from business_memory import BusinessMemory
from business_product import ProductBusinessView
from database import Database, utcnow


class BusinessProductAndBackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = Database(self.root / "relationships.db")
        self.memory = BusinessMemory(self.db)
        self.view = ProductBusinessView(self.db, self.memory)
        self._seed_contact(1001, "alice", "Alice")
        self._seed_contact(1002, "bob", "Bob")
        self._seed_contact(1003, "supplier_one", "Supplier One")

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

    def test_product_summary_combines_clients_and_suppliers(self):
        now = datetime.now(timezone.utc)
        self.memory.record(1001, "client", "Widget", quantity=2, total="100.00", occurred_at=now - timedelta(days=5))
        self.memory.record(1001, "client", "Widget", quantity=3, total="150.00", occurred_at=now)
        self.memory.record(1002, "client", "Widget", quantity=10, occurred_at=now)
        self.memory.record(1003, "supplier", "Widget", quantity=25, total="500.00", occurred_at=now)

        summary = self.view.summary("  WIDGET  ")
        self.assertIsNotNone(summary)
        stats = summary["stats"]
        self.assertEqual(stats["transaction_count"], 4)
        self.assertEqual(stats["client_count"], 2)
        self.assertEqual(stats["supplier_count"], 1)
        self.assertEqual(stats["client_quantity"], 15)
        self.assertEqual(stats["supplier_quantity"], 25)
        self.assertEqual(stats["aud_minor"], 75000)
        self.assertEqual([row["telegram_id"] for row in summary["clients"]], [1001, 1002])
        self.assertEqual([row["telegram_id"] for row in summary["suppliers"]], [1003])

    def test_product_summary_missing_product_is_read_only(self):
        before = self.memory.overview()
        self.assertIsNone(self.view.summary("not recorded"))
        self.assertEqual(self.memory.overview(), before)

    def test_sqlite_backup_preserves_business_memory_tables_and_rows(self):
        self.memory.record(1001, "client", "Backup Product", quantity=2, total="42.00")
        target = self.root / "backups" / "relationships_backup.db"

        result = self.db.backup_to(target)
        self.assertEqual(result, target)
        self.assertTrue(target.exists())
        self.assertFalse(target.with_name(target.name + ".tmp").exists())

        con = sqlite3.connect(target)
        try:
            tables = {
                row[0]
                for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            self.assertIn("contacts", tables)
            self.assertIn("business_products", tables)
            self.assertIn("business_transactions", tables)
            self.assertIn("business_memory_meta", tables)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM business_transactions").fetchone()[0], 1)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM business_products").fetchone()[0], 1)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM contacts").fetchone()[0], 3)
            row = con.execute(
                """SELECT t.role, t.quantity, t.total_minor_units, p.name
                   FROM business_transactions t
                   JOIN business_products p ON p.id=t.product_id"""
            ).fetchone()
            self.assertEqual(row, ("client", 2.0, 4200, "Backup Product"))
        finally:
            con.close()


if __name__ == "__main__":
    unittest.main()
