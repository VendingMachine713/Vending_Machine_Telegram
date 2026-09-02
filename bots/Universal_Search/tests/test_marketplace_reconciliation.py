import tempfile
import unittest
from pathlib import Path

from core import Store
from marketplace import MarketplaceStore
from marketplace_reconcile import reconcile_marketplace_message, rebuild_marketplace_index


class MarketplaceReconciliationTests(unittest.TestCase):
    def make_stores(self, directory):
        path = Path(directory) / "x.db"
        return Store(path), MarketplaceStore(path)

    def test_non_marketplace_edit_removes_stale_structured_record(self):
        with tempfile.TemporaryDirectory() as d:
            core, market = self.make_stores(d)
            core.upsert(
                -1001, "Group", None, 10, "seller", "Seller", 1,
                "2026-09-02T00:00:00+00:00", "For sale phone $500 available", False,
            )
            self.assertIsNotNone(
                reconcile_marketplace_message(
                    market, -1001, 1, 10,
                    "2026-09-02T00:00:00+00:00", "For sale phone $500 available"
                )
            )
            core.upsert(
                -1001, "Group", None, 10, "seller", "Seller", 1,
                "2026-09-02T00:01:00+00:00", "Thanks everyone", False,
            )
            self.assertIsNone(
                reconcile_marketplace_message(
                    market, -1001, 1, 10,
                    "2026-09-02T00:01:00+00:00", "Thanks everyone"
                )
            )
            totals, _ = market.stats(-1001)
            self.assertEqual(totals["total"], 0)

    def test_sold_only_edit_preserves_listing_metadata(self):
        with tempfile.TemporaryDirectory() as d:
            core, market = self.make_stores(d)
            original = "For sale iPhone 15 Pro $900 brand new pickup from Marion"
            core.upsert(-1001, "Group", None, 10, "seller", "Seller", 1,
                        "2026-09-02T00:00:00+00:00", original, False)
            first = reconcile_marketplace_message(
                market, -1001, 1, 10, "2026-09-02T00:00:00+00:00", original
            )
            core.upsert(-1001, "Group", None, 10, "seller", "Seller", 1,
                        "2026-09-02T01:00:00+00:00", "SOLD", False)
            sold = reconcile_marketplace_message(
                market, -1001, 1, 10, "2026-09-02T01:00:00+00:00", "SOLD"
            )
            self.assertEqual(sold["status"], "sold")
            self.assertEqual(sold["title"], first["title"])
            self.assertEqual(sold["price_cents"], 90000)
            self.assertEqual(sold["logical_listing_id"], first["logical_listing_id"])

    def test_pending_and_back_available_edits_preserve_identity(self):
        with tempfile.TemporaryDirectory() as d:
            _, market = self.make_stores(d)
            original = "For sale Hilux wheels $800 pickup from Marion"
            first = reconcile_marketplace_message(
                market, -1001, 1, 10, "2026-09-02T00:00:00+00:00", original
            )
            pending = reconcile_marketplace_message(
                market, -1001, 1, 10, "2026-09-02T01:00:00+00:00", "pending pickup"
            )
            available = reconcile_marketplace_message(
                market, -1001, 1, 10, "2026-09-02T02:00:00+00:00", "back available"
            )
            self.assertEqual(pending["status"], "pending")
            self.assertEqual(available["status"], "available")
            self.assertEqual(available["logical_listing_id"], first["logical_listing_id"])

    def test_full_price_edit_with_available_updates_price_and_history(self):
        with tempfile.TemporaryDirectory() as d:
            core, market = self.make_stores(d)
            original = "For sale iPhone 15 Pro $900 available"
            edited = "For sale iPhone 15 Pro $850 available"
            core.upsert(
                -1001, "Group", None, 10, "seller", "Seller", 1,
                "2026-09-02T00:00:00+00:00", original, False,
            )
            first = reconcile_marketplace_message(
                market,
                -1001,
                1,
                10,
                "2026-09-02T00:00:00+00:00",
                original,
            )
            core.upsert(
                -1001, "Group", None, 10, "seller", "Seller", 1,
                "2026-09-02T01:00:00+00:00", edited, False,
            )
            second = reconcile_marketplace_message(
                market,
                -1001,
                1,
                10,
                "2026-09-02T01:00:00+00:00",
                edited,
            )
            self.assertEqual(second["price_cents"], 85000)
            self.assertEqual(second["logical_listing_id"], first["logical_listing_id"])
            listing, history = market.price_history_for_listing(second["id"])
            self.assertEqual(listing["price_cents"], 85000)
            self.assertEqual([row["price_cents"] for row in history], [90000, 85000])

    def test_short_explicit_relisting_is_reparsed_not_status_only(self):
        with tempfile.TemporaryDirectory() as d:
            _, market = self.make_stores(d)
            first = reconcile_marketplace_message(
                market, -1001, 1, 10, "2026-09-02T00:00:00+00:00",
                "For sale phone $500 available",
            )
            relisted = reconcile_marketplace_message(
                market, -1001, 1, 10, "2026-09-02T01:00:00+00:00",
                "For sale phone available pickup Marion",
            )
            self.assertEqual(relisted["listing_type"], "sale")
            self.assertEqual(relisted["status"], "available")
            self.assertIsNone(relisted["price_cents"])
            self.assertNotEqual(relisted["fingerprint"], first["fingerprint"])

    def test_rebuild_reconciles_current_raw_index(self):
        with tempfile.TemporaryDirectory() as d:
            core, market = self.make_stores(d)
            core.upsert(-1001, "Group", None, 10, "seller", "Seller", 1,
                        "2026-09-02T00:00:00+00:00", "For sale laptop $700 available", False)
            core.upsert(-1001, "Group", None, 10, "seller", "Seller", 2,
                        "2026-09-02T00:00:00+00:00", "ordinary chat", False)
            self.assertEqual(rebuild_marketplace_index(core, market), 1)
            totals, _ = market.stats(-1001)
            self.assertEqual(totals["total"], 1)


if __name__ == "__main__":
    unittest.main()
