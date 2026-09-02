import tempfile
import unittest
from pathlib import Path

from core import Store
from watches import WatchStore


class WatchSecurityTests(unittest.TestCase):
    def make_stores(self, directory):
        path = Path(directory) / "x.db"
        return Store(path), WatchStore(path)

    def seed_message(self, core):
        core.upsert(
            -1001,
            "Phones",
            "phones",
            2,
            "seller",
            "Seller",
            1,
            "2026-09-02T00:00:00+00:00",
            "iphone 15 pro available $900",
            False,
            source="live",
        )

    def test_multiple_authorized_owners_are_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            core, watches = self.make_stores(d)
            first = watches.save(10, "owner-a", "iphone", None)
            second = watches.save(20, "owner-b", "iphone", None)
            stale = watches.save(30, "stale", "iphone", None)
            self.seed_message(core)
            watches.enqueue_matches(watches.get_message(-1001, 1))

            result = watches.reconcile_owners({10, 20})
            self.assertEqual(result["disabled_watches"], 1)
            self.assertEqual(result["cancelled_alerts"], 1)
            self.assertEqual(result["authorized_owners"], (10, 20))
            self.assertEqual(watches.list_for_owner(10)[0]["enabled"], 1)
            self.assertEqual(watches.list_for_owner(20)[0]["enabled"], 1)
            self.assertEqual(watches.list_for_owner(30)[0]["enabled"], 0)
            due = watches.due_alerts(10)
            self.assertEqual({row["watch_id"] for row in due}, {first["id"], second["id"]})
            stale_queue = {row["status"]: row["count"] for row in watches.queue_status_for_owner(30)}
            self.assertEqual(stale_queue.get("cancelled"), 1)
            self.assertEqual(stale["owner_user_id"], 30)

    def test_empty_authorized_owner_set_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            core, watches = self.make_stores(d)
            watches.save(10, "owner-a", "iphone", None)
            self.seed_message(core)
            watches.enqueue_matches(watches.get_message(-1001, 1))
            result = watches.reconcile_owners(set())
            self.assertEqual(result["disabled_watches"], 1)
            self.assertEqual(result["cancelled_alerts"], 1)
            self.assertEqual(watches.due_alerts(10), [])


if __name__ == "__main__":
    unittest.main()
