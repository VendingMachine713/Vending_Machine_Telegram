import tempfile
import unittest
from pathlib import Path

from core import Store
from marketplace import extract_listing


class MarketplaceTests(unittest.TestCase):
    def test_conservative_extraction_and_status(self):
        row = extract_listing(-100, 1, "Selling Toyota wheels, $450, excellent condition, pickup in Adelaide")
        self.assertIsNotNone(row)
        self.assertEqual(row.kind, "sale")
        self.assertEqual(row.price_cents, 45000)
        self.assertEqual(row.status, "active")
        self.assertEqual(row.location, "Adelaide")
        self.assertIsNone(extract_listing(-100, 2, "Just a nice day"))

    def test_lifecycle_and_price_history_survive_edit(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(Path(d) / "market.db")
            store.upsert(-100, "Cars", "cars", 7, "seller", "Seller", 1, "2026-09-01T00:00:00+00:00", "Selling ute $12000 available", False)
            first = store.market_listing(-100, 1)
            self.assertEqual(first["price_cents"], 1200000)
            store.upsert(-100, "Cars", "cars", 7, "seller", "Seller", 1, "2026-09-02T00:00:00+00:00", "Selling ute $11000 sold", False)
            current = store.market_listing(-100, 1)
            self.assertEqual(current["status"], "sold")
            history = store.market_price_history(current["group_key"])
            self.assertEqual({r["price_cents"] for r in history}, {1200000, 1100000})

    def test_market_filters(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(Path(d) / "market.db")
            store.upsert(-100, "Cars", "cars", 7, "seller", "Seller", 1, "2026-09-01T00:00:00+00:00", "Selling ute $12000 available", False)
            store.upsert(-100, "Cars", "cars", 8, "buyer", "Buyer", 2, "2026-09-01T00:00:00+00:00", "WTB ute wanted", False)
            self.assertEqual(len(store.market_search(kind="wanted")), 1)
            self.assertEqual(len(store.market_search(min_price=10000, max_price=13000)), 1)


if __name__ == "__main__":
    unittest.main()
