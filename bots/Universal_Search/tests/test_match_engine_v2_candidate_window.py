import tempfile
import unittest
from pathlib import Path

from core import Store, utc_now
from marketplace import MarketplaceStore
from match_engine_v2_runtime import HardenedMatchEngineV2


class MatchEngineV2CandidateWindowTests(unittest.TestCase):
    def add_listing(self, core, market, *, chat_id, message_id, sender_id, text):
        now = utc_now()
        core.upsert(
            chat_id,
            f"Chat {chat_id}",
            None,
            sender_id,
            f"u{sender_id}",
            f"User {sender_id}",
            message_id,
            now,
            text,
            False,
            source="live",
        )
        return market.ingest(chat_id, message_id, sender_id, now, text)

    def test_existing_valid_pair_survives_candidate_limit_truncation(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "x.db"
            core = Store(db)
            market = MarketplaceStore(db)
            engine = HardenedMatchEngineV2(db)

            demand = self.add_listing(
                core,
                market,
                chat_id=-1001,
                message_id=1,
                sender_id=10,
                text="WTB iPhone 15 Pro budget $1000 pickup Marion",
            )
            supply = self.add_listing(
                core,
                market,
                chat_id=-1002,
                message_id=2,
                sender_id=20,
                text="For sale iPhone 15 Pro $900 brand new pickup Marion",
            )
            engine.process_events(min_score=45, candidate_limit=10)
            match = engine.list_matches(min_score=0, limit=20)[0]
            self.assertNotEqual(match["status"], "inactive")

            self.add_listing(
                core,
                market,
                chat_id=-1003,
                message_id=3,
                sender_id=30,
                text="For sale Samsung TV $500 available pickup Marion",
            )
            engine.process_events(min_score=45, candidate_limit=1)

            # Force a demand-side change event while preserving its logical ID.
            with market.conn() as c:
                c.execute(
                    "UPDATE marketplace_listings SET condition='good' WHERE id=?",
                    (demand["id"],),
                )

            result = engine.process_events(min_score=45, candidate_limit=1)
            self.assertGreaterEqual(result["events"], 1)
            preserved = engine.get_match(match["id"])
            self.assertIsNotNone(preserved)
            self.assertNotEqual(preserved["status"], "inactive")
            self.assertEqual(preserved["supply_listing_id"], supply["id"])


if __name__ == "__main__":
    unittest.main()
