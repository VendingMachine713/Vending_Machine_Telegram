from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from business_integration import BusinessViewData, format_dashboard_section, format_profile_section
from business_memory import BusinessMemory
from database import Database, utcnow


class BusinessIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "relationships.db")
        self.memory = BusinessMemory(self.db)
        self.views = BusinessViewData(self.memory)
        self._seed_contact(2001, "repeat_client", "Repeat Client")
        self._seed_contact(2002, "oneoff", "One Off")
        self._seed_contact(2003, "supplier", "Supplier")

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

    def test_dashboard_snapshot_counts_repeat_and_reconnect_records(self):
        now = datetime(2026, 9, 5, 0, 0, tzinfo=timezone.utc)
        old = now - timedelta(days=45)
        recent = now - timedelta(days=3)

        self.memory.record(2001, "client", "Alpha", occurred_at=old)
        self.memory.record(2001, "client", "Alpha", occurred_at=old + timedelta(days=1))
        self.memory.record(2002, "client", "Beta", occurred_at=recent)
        self.memory.record(2003, "supplier", "Alpha", occurred_at=recent)
        self.memory.record(2003, "supplier", "Gamma", occurred_at=recent)

        snapshot = self.views.dashboard_snapshot(reconnect_days=30, now=now)

        self.assertEqual(snapshot.clients, 2)
        self.assertEqual(snapshot.suppliers, 1)
        self.assertEqual(snapshot.products, 3)
        self.assertEqual(snapshot.transactions, 5)
        self.assertEqual(snapshot.repeat_clients, 1)
        self.assertEqual(snapshot.repeat_suppliers, 1)
        self.assertEqual(snapshot.reconnect_candidates, 1)

        text = format_dashboard_section(snapshot)
        self.assertIn("Repeat clients: <b>1</b>", text)
        self.assertIn("Reconnect 30d+: <b>1</b>", text)
        self.assertIn("/business", text)

    def test_profile_snapshot_classifies_roles_without_using_value_as_trust(self):
        first = datetime(2026, 7, 1, 1, 0, tzinfo=timezone.utc)
        last = datetime(2026, 8, 20, 1, 0, tzinfo=timezone.utc)

        self.memory.record(2001, "client", "Alpha", total="100.00", occurred_at=first)
        self.memory.record(2001, "client", "Alpha", occurred_at=last)
        self.memory.record(2001, "supplier", "Beta", total="50.00", occurred_at=last)

        snapshot = self.views.profile_snapshot(2001)
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.roles, ("client", "supplier"))
        self.assertEqual(snapshot.role_patterns, ("Repeat client", "One-off supplier"))
        self.assertEqual(snapshot.transaction_count, 3)
        self.assertEqual(snapshot.product_count, 2)
        self.assertEqual(snapshot.aud_minor, 15000)
        self.assertEqual(snapshot.recorded_aud_values, 2)

        text = format_profile_section(snapshot, ZoneInfo("Australia/Adelaide"))
        self.assertIn("Repeat Client", text)
        self.assertIn("One-Off Supplier", text)
        self.assertIn("Transactions: <b>3</b>", text)
        self.assertIn("Recorded AUD value: <b>$150.00</b>", text)
        self.assertNotIn("Trust", text)

    def test_profile_snapshot_returns_none_for_contact_without_business_history(self):
        self.assertIsNone(self.views.profile_snapshot(2002))

    def test_naive_dashboard_clock_fails_closed(self):
        with self.assertRaises(ValueError):
            self.views.dashboard_snapshot(now=datetime(2026, 9, 5, 0, 0))


if __name__ == "__main__":
    unittest.main()
