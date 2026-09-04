import tempfile
import unittest
from pathlib import Path

from core import Store


class DemandMatchingTests(unittest.TestCase):
    def test_live_demand_matches_supply_once(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(Path(d) / "demand.db")
            store.upsert(-100, "Market", "market", 7, "seller", "Seller", 1, "2026-09-01T00:00:00+00:00", "Selling iPhone 15 Pro $900 available", False)
            store.upsert(-101, "Wanted", "wanted", 8, "buyer", "Buyer", 2, "2026-09-01T00:01:00+00:00", "WTB iPhone 15 Pro wanted", False)
            matches = store.market_matches()
            self.assertEqual(len(matches), 1)
            self.assertEqual(matches[0]["demand_chat_id"], -101)
            store.upsert(-101, "Wanted", "wanted", 8, "buyer", "Buyer", 2, "2026-09-01T00:01:00+00:00", "WTB iPhone 15 Pro wanted", False)
            self.assertEqual(len(store.market_matches()), 1)

    def test_backfill_does_not_create_match(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(Path(d) / "demand.db")
            store.upsert(-100, "Market", "market", 7, "seller", "Seller", 1, "2026-09-01T00:00:00+00:00", "Selling iPhone 15 Pro $900 available", False, source="backfill")
            store.upsert(-101, "Wanted", "wanted", 8, "buyer", "Buyer", 2, "2026-09-01T00:01:00+00:00", "WTB iPhone 15 Pro wanted", False, source="backfill")
            self.assertEqual(store.market_matches(), [])

    def test_acknowledge_is_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(Path(d) / "demand.db")
            store.upsert(-100, "Market", "market", 7, "seller", "Seller", 1, "2026-09-01T00:00:00+00:00", "Selling iPhone 15 Pro $900 available", False)
            store.upsert(-101, "Wanted", "wanted", 8, "buyer", "Buyer", 2, "2026-09-01T00:01:00+00:00", "WTB iPhone 15 Pro wanted", False)
            row = store.market_matches()[0]
            self.assertEqual(store.acknowledge_market_match(row["demand_chat_id"], row["demand_message_id"], row["supply_chat_id"], row["supply_message_id"]), 1)
            self.assertEqual(store.market_matches(), [])

    def test_feedback_is_owner_scoped_and_deduplicated(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(Path(d) / "demand.db")
            self.assertTrue(store.record_match_feedback(1, 2, 3, 4, 9, "positive"))
            self.assertTrue(store.record_match_feedback(1, 2, 3, 4, 9, "negative"))
            self.assertEqual([(r["outcome"], r["count"]) for r in store.match_engine_stats()], [("negative", 1)])


if __name__ == "__main__":
    unittest.main()
