import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core import Store
from match_daemon import DaemonLease
from match_engine import MatchEngine


class MatchDaemonLeaseTests(unittest.TestCase):
    def make_db(self, directory):
        path = Path(directory) / "x.db"
        Store(path)
        MatchEngine(path)
        return path

    def test_second_daemon_is_blocked_while_lease_is_live(self):
        with tempfile.TemporaryDirectory() as d:
            path = self.make_db(d)
            first = DaemonLease(path, ttl_seconds=60)
            second = DaemonLease(path, ttl_seconds=60)
            acquired, _ = first.acquire()
            self.assertTrue(acquired)
            acquired2, owner = second.acquire()
            self.assertFalse(acquired2)
            self.assertEqual(owner["owner"], first.owner)
            first.release()

    def test_expired_lease_can_be_recovered(self):
        with tempfile.TemporaryDirectory() as d:
            path = self.make_db(d)
            first = DaemonLease(path, ttl_seconds=60)
            self.assertTrue(first.acquire()[0])
            expired = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
            # sqlite3.Connection.__exit__ does not close the OS handle. Use
            # closing() so this regression test exercises Windows file cleanup.
            with closing(sqlite3.connect(path)) as c:
                c.execute(
                    "UPDATE marketplace_match_daemon_lease SET expires_utc=? WHERE singleton=1",
                    (expired,),
                )
                c.commit()
            second = DaemonLease(path, ttl_seconds=60)
            self.assertTrue(second.acquire()[0])
            second.release()

    def test_lease_can_be_renewed_and_released(self):
        with tempfile.TemporaryDirectory() as d:
            path = self.make_db(d)
            lease = DaemonLease(path, ttl_seconds=60)
            self.assertTrue(lease.acquire()[0])
            self.assertTrue(lease.renew())
            lease.release()
            replacement = DaemonLease(path, ttl_seconds=60)
            self.assertTrue(replacement.acquire()[0])
            replacement.release()


if __name__ == "__main__":
    unittest.main()
