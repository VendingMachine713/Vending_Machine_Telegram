import tempfile
import time
import unittest
from pathlib import Path

from core import Store, utc_now
from marketplace import MarketplaceStore
from match_engine import MatchEngine, score_marketplace_pair


class MatchEngineTests(unittest.TestCase):
    def make_stores(self, directory):
        path = Path(directory) / "x.db"
        return Store(path), MarketplaceStore(path), MatchEngine(path)

    def add_listing(
        self,
        core,
        market,
        *,
        chat_id,
        message_id,
        sender_id,
        username,
        text,
        date_utc=None,
    ):
        date_utc = date_utc or utc_now()
        core.upsert(
            chat_id,
            f"Chat {chat_id}",
            None,
            sender_id,
            username,
            username.title(),
            message_id,
            date_utc,
            text,
            False,
            source="live",
        )
        return market.ingest(chat_id, message_id, sender_id, date_utc, text)

    def demand_and_supply(self, core, market, *, supply_price=900, same_sender=False):
        demand = self.add_listing(
            core,
            market,
            chat_id=-1001,
            message_id=1,
            sender_id=10,
            username="buyer",
            text="WTB iPhone 15 Pro budget $1000 pickup Marion",
        )
        supply = self.add_listing(
            core,
            market,
            chat_id=-1002,
            message_id=2,
            sender_id=10 if same_sender else 20,
            username="seller",
            text=f"For sale iPhone 15 Pro ${supply_price} brand new pickup Marion",
        )
        return demand, supply

    def test_strong_pair_scores_above_notification_threshold(self):
        with tempfile.TemporaryDirectory() as d:
            core, market, engine = self.make_stores(d)
            demand, supply = self.demand_and_supply(core, market)
            demand_row = market.get_listing(demand["id"])
            supply_row = market.get_listing(supply["id"])
            result = score_marketplace_pair(demand_row, supply_row)
            self.assertTrue(result.eligible)
            self.assertGreaterEqual(result.score, 65)
            self.assertGreater(result.confidence, 0)
            codes = {reason["code"] for reason in result.reasons}
            self.assertIn("terms", codes)
            self.assertIn("within_budget", codes)
            self.assertIn("location", codes)

    def test_over_budget_supply_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            core, market, engine = self.make_stores(d)
            demand, supply = self.demand_and_supply(core, market, supply_price=1200)
            result = score_marketplace_pair(
                market.get_listing(demand["id"]), market.get_listing(supply["id"])
            )
            self.assertFalse(result.eligible)
            self.assertEqual(result.reject_reason, "over_budget")

    def test_same_sender_is_never_matched(self):
        with tempfile.TemporaryDirectory() as d:
            core, market, engine = self.make_stores(d)
            demand, supply = self.demand_and_supply(core, market, same_sender=True)
            result = score_marketplace_pair(
                market.get_listing(demand["id"]), market.get_listing(supply["id"])
            )
            self.assertFalse(result.eligible)
            self.assertEqual(result.reject_reason, "self_match")

    def test_concrete_category_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            core, market, engine = self.make_stores(d)
            demand = self.add_listing(
                core, market, chat_id=-1001, message_id=1, sender_id=10, username="buyer",
                text="WTB iPhone 15 Pro budget $1000",
            )
            supply = self.add_listing(
                core, market, chat_id=-1002, message_id=2, sender_id=20, username="seller",
                text="For sale Hilux wheels $800 available",
            )
            result = score_marketplace_pair(
                market.get_listing(demand["id"]), market.get_listing(supply["id"])
            )
            self.assertFalse(result.eligible)
            self.assertEqual(result.reject_reason, "category_mismatch")

    def test_refresh_is_logical_listing_duplicate_safe(self):
        with tempfile.TemporaryDirectory() as d:
            core, market, engine = self.make_stores(d)
            self.demand_and_supply(core, market)
            # Exact seller repost: same logical supply identity, different chat/message.
            self.add_listing(
                core,
                market,
                chat_id=-1003,
                message_id=3,
                sender_id=20,
                username="seller",
                text="For sale iPhone 15 Pro $900 brand new pickup Marion",
            )
            result = engine.refresh_all(min_score=45)
            self.assertEqual(result["active_pairs"], 1)
            rows = engine.list_matches(min_score=0, limit=20)
            self.assertEqual(len(rows), 1)

    def test_bootstrap_baselines_existing_matches_without_alerting(self):
        with tempfile.TemporaryDirectory() as d:
            core, market, engine = self.make_stores(d)
            self.demand_and_supply(core, market)
            result = engine.bootstrap(min_score=45)
            self.assertTrue(result["bootstrapped"])
            rows = engine.list_matches(min_score=0, limit=20)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["status"], "baseline")
            self.assertEqual(engine.enqueue_new_alerts(999, min_score=0), 0)

    def test_new_post_after_bootstrap_creates_new_alertable_match(self):
        with tempfile.TemporaryDirectory() as d:
            core, market, engine = self.make_stores(d)
            self.add_listing(
                core, market, chat_id=-1001, message_id=1, sender_id=10, username="buyer",
                text="WTB iPhone 15 Pro budget $1000 pickup Marion",
            )
            engine.bootstrap(min_score=45)
            time.sleep(0.01)
            self.add_listing(
                core, market, chat_id=-1002, message_id=2, sender_id=20, username="seller",
                text="For sale iPhone 15 Pro $900 brand new pickup Marion",
            )
            result = engine.refresh_all(min_score=45)
            self.assertEqual(result["created"], 1)
            rows = engine.list_matches(min_score=0, limit=20)
            self.assertEqual(rows[0]["status"], "new")
            self.assertEqual(engine.enqueue_new_alerts(999, min_score=0), 1)
            self.assertEqual(engine.enqueue_new_alerts(999, min_score=0), 0)
            due = engine.due_alerts()
            self.assertEqual(len(due), 1)
            self.assertEqual(due[0]["owner_user_id"], 999)

    def test_alert_send_transitions_match_to_notified(self):
        with tempfile.TemporaryDirectory() as d:
            core, market, engine = self.make_stores(d)
            self.add_listing(
                core, market, chat_id=-1001, message_id=1, sender_id=10, username="buyer",
                text="WTB iPhone 15 Pro budget $1000",
            )
            engine.bootstrap(min_score=45)
            time.sleep(0.01)
            self.add_listing(
                core, market, chat_id=-1002, message_id=2, sender_id=20, username="seller",
                text="For sale iPhone 15 Pro $900 available",
            )
            engine.refresh_all(min_score=45)
            engine.enqueue_new_alerts(999, min_score=0)
            alert = engine.due_alerts()[0]
            engine.mark_alert_sent(alert["alert_id"], alert["id"])
            row = engine.get_match(alert["id"])
            self.assertEqual(row["status"], "notified")
            self.assertTrue(row["notified_utc"])

    def test_feedback_accept_and_dismiss_are_persistent(self):
        with tempfile.TemporaryDirectory() as d:
            core, market, engine = self.make_stores(d)
            self.demand_and_supply(core, market)
            engine.refresh_all(min_score=45)
            match = engine.list_matches(min_score=0, limit=20)[0]
            self.assertTrue(engine.record_feedback(match["id"], 999, "accepted", "good lead"))
            self.assertEqual(engine.get_match(match["id"])["status"], "accepted")
            self.assertTrue(engine.record_feedback(match["id"], 999, "not_relevant", "wrong variant"))
            self.assertEqual(engine.get_match(match["id"])["status"], "dismissed")

    def test_sold_supply_inactivates_unresolved_match(self):
        with tempfile.TemporaryDirectory() as d:
            core, market, engine = self.make_stores(d)
            demand, supply = self.demand_and_supply(core, market)
            engine.refresh_all(min_score=45)
            match = engine.list_matches(min_score=0, limit=20)[0]
            with market.conn() as c:
                c.execute("UPDATE marketplace_listings SET status='sold' WHERE id=?", (supply["id"],))
            result = engine.refresh_all(min_score=45)
            self.assertEqual(result["inactivated"], 1)
            self.assertEqual(engine.get_match(match["id"])["status"], "inactive")

    def test_retry_becomes_failed_after_five_attempts(self):
        with tempfile.TemporaryDirectory() as d:
            core, market, engine = self.make_stores(d)
            self.add_listing(
                core, market, chat_id=-1001, message_id=1, sender_id=10, username="buyer",
                text="WTB iPhone 15 Pro budget $1000",
            )
            engine.bootstrap(min_score=45)
            time.sleep(0.01)
            self.add_listing(
                core, market, chat_id=-1002, message_id=2, sender_id=20, username="seller",
                text="For sale iPhone 15 Pro $900 available",
            )
            engine.refresh_all(min_score=45)
            engine.enqueue_new_alerts(999, min_score=0)
            alert = engine.due_alerts()[0]
            attempts = 0
            status = None
            for _ in range(5):
                status, _ = engine.mark_alert_retry(alert["alert_id"], "network", attempts)
                attempts += 1
            self.assertEqual(status, "failed")


if __name__ == "__main__":
    unittest.main()
