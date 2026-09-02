import tempfile
import time
import unittest
from pathlib import Path

from core import Store, utc_now
from marketplace import MarketplaceStore
from match_runtime import HardenedMatchEngine


class MatchOwnerSecurityTests(unittest.TestCase):
    def make_engine(self, directory):
        path = Path(directory) / "x.db"
        return Store(path), MarketplaceStore(path), HardenedMatchEngine(path)

    def add(self, core, market, *, chat_id, message_id, sender_id, text):
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

    def seed_new_match(self, core, market, engine):
        self.add(
            core,
            market,
            chat_id=-1001,
            message_id=1,
            sender_id=10,
            text="WTB iPhone 15 Pro budget $1000 pickup Marion",
        )
        engine.bootstrap(min_score=45)
        time.sleep(0.01)
        self.add(
            core,
            market,
            chat_id=-1002,
            message_id=2,
            sender_id=20,
            text="For sale iPhone 15 Pro $900 brand new pickup Marion",
        )
        engine.refresh_all(min_score=45)
        rows = engine.list_matches(min_score=0, statuses={"new"})
        self.assertEqual(len(rows), 1)
        return rows[0]

    def test_two_authorized_owners_get_distinct_duplicate_safe_queue_rows(self):
        with tempfile.TemporaryDirectory() as d:
            core, market, engine = self.make_engine(d)
            self.seed_new_match(core, market, engine)
            self.assertEqual(engine.enqueue_new_alerts_for_owners({100, 200}, min_score=0), 2)
            self.assertEqual(engine.enqueue_new_alerts_for_owners({100, 200}, min_score=0), 0)
            due = engine.due_alerts_for_owners({100, 200}, 20)
            self.assertEqual({int(row["owner_user_id"]) for row in due}, {100, 200})

    def test_first_owner_delivery_does_not_cancel_second_owner_copy(self):
        with tempfile.TemporaryDirectory() as d:
            core, market, engine = self.make_engine(d)
            match = self.seed_new_match(core, market, engine)
            engine.enqueue_new_alerts_for_owners({100, 200}, min_score=0)
            due = engine.due_alerts_for_owners({100, 200}, 20)
            first = next(row for row in due if int(row["owner_user_id"]) == 100)
            engine.mark_alert_sent(first["alert_id"], match["id"])
            self.assertEqual(engine.get_match(match["id"])["status"], "notified")
            self.assertEqual(engine.cancel_stale_alerts(match["id"]), 0)
            remaining = engine.due_alerts_for_owners({100, 200}, 20)
            self.assertEqual(len(remaining), 1)
            self.assertEqual(int(remaining[0]["owner_user_id"]), 200)

    def test_superseded_owner_is_cancelled_but_current_owners_survive(self):
        with tempfile.TemporaryDirectory() as d:
            core, market, engine = self.make_engine(d)
            self.seed_new_match(core, market, engine)
            engine.enqueue_new_alerts_for_owners({100, 200, 300}, min_score=0)
            self.assertEqual(engine.reconcile_alert_owners({100, 200}), 1)
            due = engine.due_alerts_for_owners({100, 200}, 20)
            self.assertEqual({int(row["owner_user_id"]) for row in due}, {100, 200})
            by_owner = engine.queue_status_by_owner()
            self.assertEqual(by_owner[300].get("cancelled"), 1)

    def test_empty_authorized_owner_set_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            core, market, engine = self.make_engine(d)
            self.seed_new_match(core, market, engine)
            engine.enqueue_new_alerts_for_owners({100, 200}, min_score=0)
            self.assertEqual(engine.reconcile_alert_owners(set()), 2)
            self.assertEqual(engine.due_alerts_for_owners(set(), 20), [])
            self.assertEqual(engine.queue_status().get("cancelled"), 2)

    def test_failed_second_owner_copy_can_retry_after_first_owner_notified(self):
        with tempfile.TemporaryDirectory() as d:
            core, market, engine = self.make_engine(d)
            match = self.seed_new_match(core, market, engine)
            engine.enqueue_new_alerts_for_owners({100, 200}, min_score=0)
            rows = engine.due_alerts_for_owners({100, 200}, 20)
            first = next(row for row in rows if int(row["owner_user_id"]) == 100)
            second = next(row for row in rows if int(row["owner_user_id"]) == 200)
            engine.mark_alert_sent(first["alert_id"], match["id"])
            attempts = 0
            for _ in range(5):
                status, _ = engine.mark_alert_retry(second["alert_id"], "network", attempts)
                attempts += 1
            self.assertEqual(status, "failed")
            self.assertEqual(engine.retry_failed_alerts(200), 1)
            by_owner = engine.queue_status_by_owner()
            self.assertEqual(by_owner[200].get("retry"), 1)

    def test_new_owner_is_not_backfilled_after_match_was_already_notified(self):
        with tempfile.TemporaryDirectory() as d:
            core, market, engine = self.make_engine(d)
            match = self.seed_new_match(core, market, engine)
            engine.enqueue_new_alerts_for_owners({100}, min_score=0)
            first = engine.due_alerts_for_owners({100}, 20)[0]
            engine.mark_alert_sent(first["alert_id"], match["id"])
            self.assertEqual(engine.enqueue_new_alerts_for_owners({200}, min_score=0), 0)
            self.assertEqual(engine.due_alerts_for_owners({200}, 20), [])


if __name__ == "__main__":
    unittest.main()
