import tempfile
import unittest
from pathlib import Path

from core import Store
from marketplace import MarketplaceStore, parse_market_query
from marketplace_ui import MarketplaceSessionStore, money, original_message_link, render_market_page


class MarketplaceUiTests(unittest.TestCase):
    def make_listing(self, directory):
        path = Path(directory) / "x.db"
        core = Store(path)
        market = MarketplaceStore(path)
        sessions = MarketplaceSessionStore(path)
        core.upsert(
            -1001234567890,
            "Marketplace SA",
            "marketplacesa",
            10,
            "seller",
            "Seller",
            1,
            "2026-09-02T00:00:00+00:00",
            "For sale iPhone 15 Pro $900 brand new pickup from Marion",
            False,
            source="live",
        )
        market.ingest(
            -1001234567890,
            1,
            10,
            "2026-09-02T00:00:00+00:00",
            "For sale iPhone 15 Pro $900 brand new pickup from Marion",
        )
        rows, _ = market.search(parse_market_query("iphone"), -1001234567890)
        return path, sessions, rows[0]

    def test_money(self):
        self.assertEqual(money(90000, "AUD"), "$900.00")
        self.assertEqual(money(None, "AUD"), "Price not listed")

    def test_original_message_link_prefers_public_username(self):
        with tempfile.TemporaryDirectory() as d:
            _, _, row = self.make_listing(d)
            self.assertEqual(original_message_link(row), "https://t.me/marketplacesa/1")

    def test_marketplace_session_is_user_bound_data_and_persists(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "x.db"
            Store(path)
            MarketplaceStore(path)
            sessions = MarketplaceSessionStore(path)
            token = sessions.create(42, -1001, "iphone --max 1000", False)
            row = sessions.get(token)
            self.assertEqual(row["user_id"], 42)
            self.assertEqual(row["chat_scope"], -1001)
            self.assertEqual(row["raw_query"], "iphone --max 1000")
            self.assertEqual(row["global_search"], 0)

    def test_render_page_contains_listing_metadata(self):
        with tempfile.TemporaryDirectory() as d:
            _, _, row = self.make_listing(d)
            text = render_market_page([row], 1)
            self.assertIn("Marketplace results", text)
            self.assertIn("$900.00", text)
            self.assertIn("electronics", text)
            self.assertIn("Open original message", text)


if __name__ == "__main__":
    unittest.main()
