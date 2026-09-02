import tempfile
import time
import unittest
from pathlib import Path

from core import Store, utc_now
from marketplace import MarketplaceStore
from match_runtime import HardenedMatchEngine


class MatchRuntimeTests(unittest.TestCase):
    def make_stores(self, directory):
        path = Path(directory) / "x.db"
        return Store(path), MarketplaceStore(path), HardenedMatchEngine(path)

    def add(self, core, market, *, chat_id, message_id, sender_id, text):
        now = utc_now()
        core.upsert(
            chat_id, f"Chat {chat_id}", None, sender_id, f"u{sender_id}", f"User {sender_id}",
            message_id, now, text, False, source="live"
        )
        return market.ingest(chat_id, message_id, sender_id, now, text)

    def seed_new_alert(self, core, market, engine):
        self.add(
            core, market, chat_id=-1001, message_id=1, sender_id=10,
            text="WTB iPhone 15 Pro budget $1000 pickup Marion",
        )
        engine.bootstrap(min_score=45)
        time.sleep(0.01)
        supply = self.add(
            core, market, chat_id=-1002, message_id=2, sender_id=20,
            text="For sale iPhone 15 Pro $900 brand new pickup Marion",
        )
        engine.refresh_all(min_score=45)
        self.assertEqual(engine.enqueue_new_alerts(999, min_score=0), 1)
        return supply, engine.due_alerts()[0]

    def test_refresh_cancels_pending_alert_when_supply_becomes_inactive(self):
        with tempfile.TemporaryDirectory() as d:
            core, market, engine = self.make_stores(d)
            supply, alert = self.seed_new_alert(core, market, engine)
            with market.conn() as c:
                c.execute("UPDATE marketplace_listings SET status='sold' WHERE id=?", (supply["id"],))
            result = engine.refresh_all(min_score=45)
            self.assertEqual(result["cancelled_alerts"], 1)
            self.assertEqual(engine.queue_status().get("cancelled"), 1)
            self.assertEqual(engine.due_alerts(), [])
            self.assertEqual(engine.get_match(alert["id"])["status"], "inactive")

    def test_dismiss_feedback_cancels_pending_alert_immediately(self):
        with tempfile.TemporaryDirectory() as d:
            core, market, engine = self.make_stores(d)
            _, alert = self.seed_new_alert(core, market, engine)
            self.assertTrue(engine.record_feedback(alert["id"], 999, "not_relevant", "wrong model"))
            self.assertEqual(engine.get_match(alert["id"])["status"], "dismissed")
            self.assertEqual(engine.queue_status().get("cancelled"), 1)
            self.assertEqual(engine.due_alerts(), [])

    def test_failed_alert_can_be_requeued_only_while_match_is_new(self):
        with tempfile.TemporaryDirectory() as d:
            core, market, engine = self.make_stores(d)
            _, alert = self.seed_new_alert(core, market, engine)
            attempts = 0
            for _ in range(5):
                status, _ = engine.mark_alert_retry(alert["alert_id"], "network", attempts)
                attempts += 1
            self.assertEqual(status, "failed")
            self.assertEqual(engine.retry_failed_alerts(999), 1)
            self.assertEqual(engine.queue_status().get("retry"), 1)

            engine.record_feedback(alert["id"], 999, "accepted")
            # Once the match is resolved, a failed delivery is never resurrected.
            with engine.conn() as c:
                c.execute(
                    "UPDATE marketplace_match_alert_queue SET status='failed' WHERE id=?",
                    (alert["alert_id"],),
                )
            self.assertEqual(engine.retry_failed_alerts(999), 0)

    def test_queue_status_reports_all_states(self):
        with tempfile.TemporaryDirectory() as d:
            core, market, engine = self.make_stores(d)
            _, alert = self.seed_new_alert(core, market, engine)
            self.assertEqual(engine.queue_status().get("pending"), 1)
            engine.mark_alert_sent(alert["alert_id"], alert["id"])
            self.assertEqual(engine.queue_status().get("sent"), 1)


if __name__ == "__main__":
    unittest.main()
