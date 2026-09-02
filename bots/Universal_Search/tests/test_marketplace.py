import tempfile
import unittest
from pathlib import Path

from core import Store
from marketplace import (
    MarketplaceStore,
    detect_category,
    detect_condition,
    detect_listing_type,
    detect_status,
    extract_listing,
    extract_location_hint,
    extract_price,
    parse_market_query,
)


class MarketplaceTests(unittest.TestCase):
    def make_stores(self, directory):
        path = Path(directory) / "x.db"
        core = Store(path)
        market = MarketplaceStore(path)
        return core, market

    def seed(self, core, *, chat_id=-1001, message_id=1, sender_id=10, username="seller",
             text="For sale iPhone 15 Pro $900 brand new pickup from Marion", date="2026-09-02T00:00:00+00:00"):
        core.upsert(
            chat_id, "Marketplace SA", "marketplacesa", sender_id, username, "Seller",
            message_id, date, text, False, source="live"
        )

    def test_price_parsing_aud_formats(self):
        self.assertEqual(extract_price("$1,250 ono"), (125000, "AUD"))
        self.assertEqual(extract_price("AUD 850 firm"), (85000, "AUD"))
        self.assertEqual(extract_price("asking 1.5k"), (150000, "AUD"))

    def test_listing_type_priority(self):
        self.assertEqual(detect_listing_type("WTB iphone budget $500"), "wanted")
        self.assertEqual(detect_listing_type("WTT wheels swap for tyres"), "trade")
        self.assertEqual(detect_listing_type("Offering services available - mobile mechanic $100"), "service")
        self.assertEqual(detect_listing_type("For sale laptop $700"), "sale")

    def test_status_condition_category_and_location(self):
        text = "For sale iPhone 15 Pro $900 brand new pickup from Marion"
        self.assertEqual(detect_status(text, "sale"), "available")
        self.assertEqual(detect_condition(text), "new")
        self.assertEqual(detect_category(text, "sale"), "electronics")
        self.assertEqual(extract_location_hint(text), "Marion")
        self.assertEqual(detect_status("SOLD - iPhone", "sale"), "sold")
        self.assertEqual(detect_status("pending pickup", "sale"), "pending")

    def test_extract_listing_is_conservative_and_structured(self):
        row = extract_listing(
            "For sale iPhone 15 Pro $900 brand new pickup from Marion", sender_id=10
        )
        self.assertEqual(row.listing_type, "sale")
        self.assertEqual(row.price_cents, 90000)
        self.assertEqual(row.currency, "AUD")
        self.assertEqual(row.category, "electronics")
        self.assertEqual(row.status, "available")
        self.assertGreater(row.confidence, 0.5)
        self.assertEqual(len(row.logical_listing_id), 24)

    def test_ingest_and_structured_search(self):
        with tempfile.TemporaryDirectory() as d:
            core, market = self.make_stores(d)
            self.seed(core, message_id=1, text="For sale iPhone 15 Pro $900 brand new pickup from Marion")
            self.seed(core, message_id=2, text="For sale Samsung Galaxy $650 used pickup from Glenelg")
            self.seed(core, message_id=3, text="WTB iPhone 14 budget $500", username="buyer")
            for message_id in (1, 2, 3):
                with core.conn() as c:
                    row = c.execute(
                        "SELECT chat_id,message_id,sender_id,date_utc,text FROM indexed_messages WHERE message_id=?",
                        (message_id,),
                    ).fetchone()
                market.ingest(row["chat_id"], row["message_id"], row["sender_id"], row["date_utc"], row["text"])

            q = parse_market_query("iphone --type sale --min 800 --max 1000 --category electronics")
            rows, more = market.search(q, -1001)
            self.assertEqual(len(rows), 1)
            self.assertFalse(more)
            self.assertEqual(rows[0]["message_id"], 1)

            wanted, _ = market.search(parse_market_query("iphone --type wanted"), -1001)
            self.assertEqual([r["message_id"] for r in wanted], [3])

    def test_price_sorting_and_pagination(self):
        with tempfile.TemporaryDirectory() as d:
            core, market = self.make_stores(d)
            for message_id, price in ((1, 900), (2, 500), (3, 1200)):
                text = f"For sale iPhone ${price} available"
                self.seed(core, message_id=message_id, text=text)
                market.ingest(-1001, message_id, 10, "2026-09-02T00:00:00+00:00", text)
            page1, more = market.search(parse_market_query("iphone --sort price-asc --limit 2 --page 1"), -1001)
            page2, more2 = market.search(parse_market_query("iphone --sort price-asc --limit 2 --page 2"), -1001)
            self.assertEqual([r["price_cents"] for r in page1], [50000, 90000])
            self.assertTrue(more)
            self.assertEqual([r["price_cents"] for r in page2], [120000])
            self.assertFalse(more2)

    def test_same_listing_price_change_builds_history(self):
        with tempfile.TemporaryDirectory() as d:
            core, market = self.make_stores(d)
            original = "For sale iPhone 15 Pro $900 available"
            reduced = "For sale iPhone 15 Pro $850 available"
            self.seed(core, text=original)
            first = market.ingest(-1001, 1, 10, "2026-09-01T00:00:00+00:00", original)
            self.seed(core, text=reduced, date="2026-09-02T00:00:00+00:00")
            second = market.ingest(-1001, 1, 10, "2026-09-02T00:00:00+00:00", reduced)
            self.assertEqual(first["logical_listing_id"], second["logical_listing_id"])
            listing, history = market.price_history_for_listing(second["id"])
            self.assertEqual(listing["price_cents"], 85000)
            self.assertEqual([r["price_cents"] for r in history], [90000, 85000])

    def test_exact_repost_groups_logically_across_chats(self):
        with tempfile.TemporaryDirectory() as d:
            core, market = self.make_stores(d)
            text1 = "For sale Hilux wheels $800 pickup from Marion"
            text2 = "For sale Hilux wheels $750 pickup from Marion"
            self.seed(core, chat_id=-1001, message_id=1, text=text1)
            self.seed(core, chat_id=-1002, message_id=2, text=text2)
            one = market.ingest(-1001, 1, 10, "2026-09-01T00:00:00+00:00", text1)
            two = market.ingest(-1002, 2, 10, "2026-09-02T00:00:00+00:00", text2)
            self.assertEqual(one["logical_listing_id"], two["logical_listing_id"])
            row = market.get_listing(two["id"])
            self.assertEqual(row["repost_count"], 2)

    def test_rebuild_from_existing_index(self):
        with tempfile.TemporaryDirectory() as d:
            core, market = self.make_stores(d)
            self.seed(core, message_id=1)
            self.seed(core, message_id=2, text="ordinary conversation with no listing cues")
            self.assertEqual(market.rebuild_from_index(), 1)
            totals, categories = market.stats(-1001)
            self.assertEqual(totals["total"], 1)
            self.assertEqual(categories[0]["category"], "electronics")


if __name__ == "__main__":
    unittest.main()
