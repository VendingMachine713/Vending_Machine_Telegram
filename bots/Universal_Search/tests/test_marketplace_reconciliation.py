import tempfile
import unittest
from pathlib import Path

from core import Store
from marketplace import MarketplaceStore


class MarketplaceReconciliationTests(unittest.TestCase):
    def test_caller_can_remove_listing_when_edited_message_is_no_longer_marketplace(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "x.db"
            core = Store(path)
            market = MarketplaceStore(path)
            core.upsert(
                -1001, "Group", None, 10, "seller", "Seller", 1,
                "2026-09-02T00:00:00+00:00", "For sale phone $500 available", False,
            )
            self.assertIsNotNone(
                market.ingest(-1001, 1, 10, "2026-09-02T00:00:00+00:00", "For sale phone $500 available")
            )
            core.upsert(
                -1001, "Group", None, 10, "seller", "Seller", 1,
                "2026-09-02T00:01:00+00:00", "Thanks everyone", False,
            )
            result = market.ingest(-1001, 1, 10, "2026-09-02T00:01:00+00:00", "Thanks everyone")
            self.assertIsNone(result)
            self.assertTrue(market.remove_for_message(-1001, 1))
            totals, _ = market.stats(-1001)
            self.assertEqual(totals["total"], 0)


if __name__ == "__main__":
    unittest.main()
