import tempfile
import unittest
from pathlib import Path

from core import Store
from watches import WatchStore, message_matches


class WatchTests(unittest.TestCase):
    def make_stores(self, directory):
        path = Path(directory) / "x.db"
        core = Store(path)
        watches = WatchStore(path)
        return core, watches

    def seed_message(self, core, *, chat_id=-1001, message_id=1, text="iphone 15 pro available $900 dm me",
                     username="bob", has_media=False):
        core.upsert(
            chat_id,
            "Phones",
            "phones",
            2,
            username,
            "Bob",
            message_id,
            "2026-09-02T00:00:00+00:00",
            text,
            has_media,
            source="live",
        )

    def test_message_matching_advanced_filters(self):
        with tempfile.TemporaryDirectory() as d:
            core, watches = self.make_stores(d)
            self.seed_message(core, has_media=True)
            row = watches.get_message(-1001, 1)
            self.assertTrue(message_matches('"iphone 15" --user @bob --media', row))
            self.assertFalse(message_matches('"iphone 15" -pro', row))
            self.assertTrue(message_matches('samsung OR iphone', row))
            self.assertTrue(message_matches('--available', row))

    def test_save_is_idempotent_by_owner_and_name(self):
        with tempfile.TemporaryDirectory() as d:
            _, watches = self.make_stores(d)
            first = watches.save(10, "phones", "iphone", -1001)
            second = watches.save(10, "phones", "samsung", None)
            self.assertEqual(first["id"], second["id"])
            self.assertEqual(watches.count_for_owner(10), 1)
            self.assertEqual(second["raw_query"], "samsung")
            self.assertIsNone(second["chat_scope"])
            self.assertEqual(second["enabled"], 1)

    def test_scope_pause_resume_and_delete(self):
        with tempfile.TemporaryDirectory() as d:
            _, watches = self.make_stores(d)
            local = watches.save(10, "local", "iphone", -1001)
            global_watch = watches.save(10, "global", "iphone", None)
            candidates = watches.candidate_watches(-1001)
            self.assertEqual({r["id"] for r in candidates}, {local["id"], global_watch["id"]})
            self.assertTrue(watches.set_enabled(10, local["id"], False))
            candidates = watches.candidate_watches(-1001)
            self.assertEqual({r["id"] for r in candidates}, {global_watch["id"]})
            self.assertTrue(watches.set_enabled(10, local["id"], True))
            self.assertTrue(watches.delete(10, local["id"]))
            self.assertFalse(watches.delete(999, global_watch["id"]))

    def test_matching_messages_enqueue_once(self):
        with tempfile.TemporaryDirectory() as d:
            core, watches = self.make_stores(d)
            watches.save(10, "iphone", "iphone -case", -1001)
            self.seed_message(core)
            row = watches.get_message(-1001, 1)
            self.assertEqual(watches.enqueue_matches(row), 1)
            self.assertEqual(watches.enqueue_matches(row), 0)
            due = watches.due_alerts()
            self.assertEqual(len(due), 1)
            self.assertEqual(due[0]["owner_user_id"], 10)
            self.assertEqual(due[0]["watch_name"], "iphone")

    def test_non_matching_scope_or_query_does_not_enqueue(self):
        with tempfile.TemporaryDirectory() as d:
            core, watches = self.make_stores(d)
            watches.save(10, "other-chat", "iphone", -1002)
            watches.save(10, "wrong-query", "samsung", -1001)
            self.seed_message(core)
            row = watches.get_message(-1001, 1)
            self.assertEqual(watches.enqueue_matches(row), 0)

    def test_mark_sent_resets_watch_failure_state(self):
        with tempfile.TemporaryDirectory() as d:
            core, watches = self.make_stores(d)
            watch = watches.save(10, "iphone", "iphone", -1001)
            self.seed_message(core)
            row = watches.get_message(-1001, 1)
            watches.enqueue_matches(row)
            alert = watches.due_alerts()[0]
            with watches.conn() as c:
                c.execute(
                    "UPDATE saved_searches SET failure_count=2,last_error='old' WHERE id=?",
                    (watch["id"],),
                )
            watches.mark_sent(alert["alert_id"], watch["id"])
            status = {r["status"]: r["count"] for r in watches.queue_status_for_owner(10)}
            self.assertEqual(status.get("sent"), 1)
            current = watches.list_for_owner(10)[0]
            self.assertEqual(current["failure_count"], 0)
            self.assertIsNone(current["last_error"])
            self.assertTrue(current["last_match_utc"])

    def test_retry_backoff_becomes_terminal_after_five_attempts(self):
        with tempfile.TemporaryDirectory() as d:
            core, watches = self.make_stores(d)
            watch = watches.save(10, "iphone", "iphone", -1001)
            self.seed_message(core)
            watches.enqueue_matches(watches.get_message(-1001, 1))
            alert = watches.due_alerts()[0]
            status = None
            attempts = 0
            for _ in range(5):
                status, _ = watches.mark_retry(alert["alert_id"], "network", attempts)
                attempts += 1
            self.assertEqual(status, "failed")
            queue = {r["status"]: r["count"] for r in watches.queue_status_for_owner(10)}
            self.assertEqual(queue.get("failed"), 1)
            current = watches.list_for_owner(10)[0]
            self.assertEqual(current["failure_count"], 1)
            self.assertEqual(current["enabled"], 1)


if __name__ == "__main__":
    unittest.main()
