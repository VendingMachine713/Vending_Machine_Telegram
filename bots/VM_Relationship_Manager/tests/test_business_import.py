from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from business_import import BusinessHistoryImporter
from business_memory import BusinessMemory
from database import Database, utcnow


HEADER = "contact,role,product,quantity,unit,total,currency,occurred_at,note,external_id\n"


class BusinessHistoryImporterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "relationships.db")
        self.memory = BusinessMemory(self.db)
        self._seed_contact(1001, "alice", "Alice")
        self._seed_contact(1002, "bob", "Bob")
        self.importer = BusinessHistoryImporter(self.db)

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

    def test_preview_is_read_only_and_resolves_id_and_username(self):
        csv_text = HEADER + (
            "1001,client,Product A,2,unit,120.50,AUD,2026-08-01,old order,a1\n"
            "@bob,supplier,Product B,10,box,500,AUD,2026-08-02T09:30:00+09:30,old supply,b1\n"
        )
        preview = self.importer.preview_text(csv_text, source_file="history.csv")
        self.assertTrue(preview.can_apply)
        self.assertEqual(preview.new_count, 2)
        self.assertEqual(preview.duplicate_count, 0)
        self.assertEqual(
            self.db.one("SELECT COUNT(*) AS n FROM business_transactions")["n"],
            0,
        )
        self.assertEqual(preview.valid_rows[0].telegram_id, 1001)
        self.assertEqual(preview.valid_rows[1].telegram_id, 1002)
        self.assertEqual(preview.valid_rows[0].total_minor_units, 12050)

    def test_apply_is_idempotent_with_external_ids(self):
        csv_text = HEADER + (
            "1001,client,Product A,2,unit,120.50,AUD,2026-08-01,old order,legacy-001\n"
            "1001,client,Product A,1,unit,,AUD,2026-08-15,repeat,legacy-002\n"
        )
        first = self.importer.apply_text(csv_text, source_file="history.csv", recorded_by=999)
        self.assertEqual(first.inserted, 2)
        self.assertEqual(first.skipped_duplicates, 0)

        second = self.importer.apply_text(csv_text, source_file="history.csv", recorded_by=999)
        self.assertEqual(second.inserted, 0)
        self.assertEqual(second.skipped_duplicates, 2)
        self.assertEqual(
            self.db.one("SELECT COUNT(*) AS n FROM business_transactions")["n"],
            2,
        )
        self.assertEqual(
            self.db.one("SELECT COUNT(*) AS n FROM business_import_receipts")["n"],
            2,
        )
        self.assertEqual(
            self.db.one(
                "SELECT COUNT(*) AS n FROM admin_audit WHERE action='business_transaction_imported'"
            )["n"],
            2,
        )

    def test_hash_idempotency_handles_same_file_without_external_ids(self):
        csv_text = HEADER + (
            "@alice,client,Product A,2,unit,120.50,AUD,2026-08-01,old order,\n"
        )
        first = self.importer.apply_text(csv_text)
        second = self.importer.apply_text(csv_text)
        self.assertEqual(first.inserted, 1)
        self.assertEqual(second.inserted, 0)
        self.assertEqual(second.skipped_duplicates, 1)

    def test_duplicate_rows_inside_one_file_are_skipped(self):
        row = "1001,client,Product A,2,unit,120.50,AUD,2026-08-01,same,dup-1\n"
        preview = self.importer.preview_text(HEADER + row + row)
        self.assertEqual(preview.new_count, 1)
        self.assertEqual(preview.duplicate_count, 1)
        result = self.importer.apply_text(HEADER + row + row)
        self.assertEqual(result.inserted, 1)
        self.assertEqual(result.skipped_duplicates, 1)

    def test_validation_failure_writes_nothing(self):
        csv_text = HEADER + (
            "1001,client,Product A,2,unit,100,AUD,2026-08-01,good,g1\n"
            "9999,client,Product B,1,unit,20,AUD,2026-08-02,bad,g2\n"
        )
        preview = self.importer.preview_text(csv_text)
        self.assertFalse(preview.can_apply)
        self.assertEqual(len(preview.problems), 1)
        with self.assertRaises(ValueError):
            self.importer.apply_text(csv_text)
        self.assertEqual(
            self.db.one("SELECT COUNT(*) AS n FROM business_transactions")["n"],
            0,
        )

    def test_header_validation_is_fail_closed(self):
        preview = self.importer.preview_text("contact,role,unknown\n1001,client,x\n")
        self.assertFalse(preview.can_apply)
        messages = " ".join(problem.message for problem in preview.problems)
        self.assertIn("missing required", messages)
        self.assertIn("unknown column", messages)

    def test_naive_timestamp_is_rejected_but_date_only_is_allowed(self):
        bad = HEADER + "1001,client,A,1,unit,,AUD,2026-08-01T10:30:00,,,\n"
        preview = self.importer.preview_text(bad)
        self.assertFalse(preview.can_apply)
        self.assertIn("timezone", preview.problems[0].message)

        good = HEADER + "1001,client,A,1,unit,,AUD,2026-08-01,,,\n"
        preview = self.importer.preview_text(good)
        self.assertTrue(preview.can_apply)
        self.assertIn("T12:00:00+00:00", preview.valid_rows[0].occurred_at)

    def test_import_populates_existing_business_views(self):
        csv_text = HEADER + (
            "1001,client,Reload Product,1,unit,50,AUD,2026-07-01,,r1\n"
            "1001,client,Reload Product,2,unit,80,AUD,2026-08-01,,r2\n"
            "1002,supplier,Reload Product,10,unit,300,AUD,2026-08-02,,r3\n"
        )
        self.importer.apply_text(csv_text)
        clients = self.memory.reload_candidates("reload product")
        suppliers = self.memory.top_suppliers("reload product")
        self.assertEqual(clients[0]["telegram_id"], 1001)
        self.assertEqual(clients[0]["transaction_count"], 2)
        self.assertEqual(suppliers[0]["telegram_id"], 1002)


if __name__ == "__main__":
    unittest.main()
