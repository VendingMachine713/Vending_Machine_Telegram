import tempfile
import threading
import unittest
from pathlib import Path

from smart_autoposter.core import create_campaign, create_content, enqueue_campaign
from smart_autoposter.db import Database, utcnow
from smart_autoposter.delivery_ledger import ensure_delivery_ledger


class QueueCapacityAtomicityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "db.sqlite3")
        self.db.init()
        ensure_delivery_ledger(self.db)
        now = utcnow()
        with self.db.connect() as con:
            for gid in (-1001, -1002):
                con.execute(
                    "INSERT INTO destinations(group_id,group_name,primary_access,secondary_access,preferred_account,mode,enabled,needs_review,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (gid, f"G{abs(gid)}", 1, 0, "primary", "text", 1, 0, now),
                )
                con.execute("INSERT INTO destination_tags(group_id,tag) VALUES(?,?)", (gid, "main"))
        create_content(self.db, "content", "hello", [])
        create_campaign(self.db, "camp", "Campaign", "content", tags="main")
        with self.db.connect() as con:
            con.execute(
                "UPDATE campaigns SET enabled=1,lifecycle_state='active',last_preview_at=? WHERE campaign_id='camp'",
                (utcnow(),),
            )

    def tearDown(self):
        self.tmp.cleanup()

    def _limits(self, **overrides):
        values = {
            "max_queue_size": 100,
            "max_pending_per_campaign": 100,
            "max_pending_per_destination": 100,
        }
        values.update(overrides)
        return values

    def test_capacity_failure_leaves_no_partial_batch_or_cycle_increment(self):
        with self.assertRaisesRegex(RuntimeError, "MAX_QUEUE_SIZE"):
            enqueue_campaign(self.db, "camp", run_key="too-large", limits=self._limits(max_queue_size=1))
        with self.db.connect() as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM queue").fetchone()[0], 0)
            self.assertEqual(con.execute("SELECT completed_cycles FROM campaigns WHERE campaign_id='camp'").fetchone()[0], 0)
            self.assertIsNone(con.execute("SELECT 1 FROM queue_run_seals WHERE campaign_id='camp' AND run_key='too-large'").fetchone())

    def test_concurrent_enqueues_cannot_overshoot_total_capacity(self):
        barrier = threading.Barrier(2)
        results = []
        errors = []

        def run(key):
            try:
                barrier.wait(timeout=5)
                results.append(enqueue_campaign(self.db, "camp", run_key=key, limits=self._limits(max_queue_size=2)))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=run, args=(f"run-{i}",)) for i in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        self.assertFalse(any(t.is_alive() for t in threads))
        self.assertEqual(len(results), 1)
        self.assertEqual(len(errors), 1)
        self.assertIn("MAX_QUEUE_SIZE", str(errors[0]))
        with self.db.connect() as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM queue WHERE status='pending'").fetchone()[0], 2)
            self.assertEqual(con.execute("SELECT completed_cycles FROM campaigns WHERE campaign_id='camp'").fetchone()[0], 1)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM queue_run_seals WHERE campaign_id='camp'").fetchone()[0], 1)

    def test_concurrent_enqueues_cannot_overshoot_destination_capacity(self):
        with self.db.connect() as con:
            con.execute("UPDATE destinations SET enabled=0 WHERE group_id=-1002")
        barrier = threading.Barrier(2)
        results = []
        errors = []

        def run(key):
            try:
                barrier.wait(timeout=5)
                results.append(enqueue_campaign(self.db, "camp", run_key=key, limits=self._limits(max_pending_per_destination=1)))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=run, args=(f"dest-{i}",)) for i in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        self.assertEqual(len(results), 1)
        self.assertEqual(len(errors), 1)
        self.assertIn("MAX_PENDING_PER_DESTINATION", str(errors[0]))
        with self.db.connect() as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM queue WHERE group_id=-1001 AND status='pending'").fetchone()[0], 1)
            self.assertEqual(con.execute("SELECT completed_cycles FROM campaigns WHERE campaign_id='camp'").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
