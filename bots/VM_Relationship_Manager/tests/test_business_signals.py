from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from business_memory import BusinessMemory
from business_signals import BusinessSignals
from database import Database, utcnow


class BusinessSignalsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "relationships.db")
        self.memory = BusinessMemory(self.db)
        self.signals = BusinessSignals(self.db)
        self._seed_contact(1001, "alice", "Alice")
        self._seed_contact(1002, "bob", "Bob")

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

    def test_availability_is_explicit_audited_and_reversible(self):
        self.memory.record(1001, "client", "Product Alpha", recorded_by=999)

        status = self.signals.mark_available(
            "product alpha",
            available=True,
            updated_by=999,
            note="reload landed",
        )
        self.assertTrue(status["is_available"])
        self.assertEqual(len(self.signals.available_products()), 1)
        audit = self.db.one(
            """SELECT * FROM admin_audit
               WHERE admin_id=? AND action='business_product_availability_changed'
               ORDER BY id DESC LIMIT 1""",
            (999,),
        )
        self.assertIsNotNone(audit)

        status = self.signals.mark_available(
            "Product Alpha",
            available=False,
            updated_by=999,
        )
        self.assertFalse(status["is_available"])
        self.assertEqual(self.signals.available_products(), [])

    def test_unknown_product_fails_closed(self):
        with self.assertRaises(ValueError):
            self.signals.mark_available("Unknown Product", available=True, updated_by=999)

    def test_operator_brief_ranks_reload_and_dormant_history(self):
        now = datetime.now(timezone.utc)
        old = now - timedelta(days=60)
        recent = now - timedelta(days=3)

        self.memory.record(1001, "client", "Reload Item", occurred_at=old)
        self.memory.record(1001, "client", "Reload Item", occurred_at=old)
        self.memory.record(1002, "client", "Reload Item", occurred_at=recent)
        self.signals.mark_available("Reload Item", available=True, updated_by=999)

        brief = self.signals.operator_brief(inactive_days=30, limit=3, now=now)
        self.assertEqual(brief.available_products, 1)
        self.assertEqual(brief.reload_candidates, 2)
        self.assertEqual(brief.dormant_clients, 1)
        self.assertEqual(brief.repeat_dormant_clients, 1)
        self.assertEqual(brief.top_reload[0]["telegram_id"], 1001)
        self.assertEqual(brief.top_dormant[0]["telegram_id"], 1001)


if __name__ == "__main__":
    unittest.main()
