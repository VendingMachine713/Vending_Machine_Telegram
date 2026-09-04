import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from shared.vm_core.heartbeat import heartbeat_snapshot, record_heartbeat


class HeartbeatTests(unittest.TestCase):
    def test_fresh_stale_and_expired(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            now = datetime(2026, 9, 4, tzinfo=timezone.utc)
            record_heartbeat("A", "a1", observed_at_utc=(now - timedelta(seconds=30)).isoformat(), root=root)
            record_heartbeat("B", "b1", observed_at_utc=(now - timedelta(seconds=90)).isoformat(), root=root)
            record_heartbeat("C", "c1", observed_at_utc=(now - timedelta(seconds=300)).isoformat(), root=root)
            snap = heartbeat_snapshot(root, now=now)
            states = {item["service"]: item["freshness"] for item in snap["heartbeats"]}
            self.assertEqual(states, {"A": "FRESH", "B": "STALE", "C": "EXPIRED"})

    def test_record_heartbeat_preserves_operational_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            record_heartbeat(
                "Demo", "instance-1", status="busy", active_task="scan",
                counters={"queued": 4}, last_error=None, recovery_state="NONE", root=root
            )
            item = heartbeat_snapshot(root)["heartbeats"][0]
            self.assertEqual(item["active_task"], "scan")
            self.assertEqual(item["counters"]["queued"], 4)
            self.assertEqual(item["recovery_state"], "NONE")


if __name__ == "__main__":
    unittest.main()
