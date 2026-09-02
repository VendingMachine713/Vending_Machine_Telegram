import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core import Store
from marketplace import MarketplaceStore
from match_engine_v2_runtime import HardenedMatchEngineV2


class MatchEngineV2BackfillTests(unittest.TestCase):
    def test_old_wtb_imported_after_baseline_is_not_reminder_alertable(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "x.db"
            core = Store(db)
            market = MarketplaceStore(db)
            engine = HardenedMatchEngineV2(db)

            baseline = engine.bootstrap_v2(ttl_days=30, reminder_lead_days=7)
            self.assertTrue(baseline["v2_bootstrapped"])

            historical_date = (
                datetime.now(timezone.utc) - timedelta(days=40)
            ).isoformat()
            core.upsert(
                -1001,
                "Historical group",
                None,
                10,
                "buyer",
                "Buyer",
                1,
                historical_date,
                "WTB iPhone 15 Pro budget $1000 pickup Marion",
                False,
                source="backfill",
            )
            demand = market.ingest(
                -1001,
                1,
                10,
                historical_date,
                "WTB iPhone 15 Pro budget $1000 pickup Marion",
            )

            result = engine.process_events(min_score=45)
            self.assertEqual(result["events"], 1)

            with engine.conn() as c:
                expiry = c.execute(
                    """SELECT status,remind_utc,expires_utc
                       FROM marketplace_wtb_expiry
                       WHERE demand_logical_id=?""",
                    (demand["logical_listing_id"],),
                ).fetchone()

            self.assertIsNotNone(expiry)
            self.assertEqual(expiry["status"], "baseline")
            self.assertEqual(engine.enqueue_due_wtb_expiry_alerts(999), 0)
            self.assertEqual(engine.due_wtb_expiry_alerts(), [])


if __name__ == "__main__":
    unittest.main()
