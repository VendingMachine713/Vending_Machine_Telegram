from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from shared.vm_core.db import PlatformDB
from shared.vm_core.health_contract import (
    HEALTH_CONTRACT_VERSION,
    health_snapshot,
    normalize_health_status,
    service_health_record,
)


class HealthContractTests(unittest.TestCase):
    def test_status_normalization_and_semantics(self) -> None:
        self.assertEqual(normalize_health_status("alive"), "ALIVE")
        self.assertEqual(normalize_health_status("unexpected"), "UNKNOWN")

        alive = service_health_record("demo", "ALIVE", detail={"process_alive": True})
        self.assertEqual(alive["contract_version"], HEALTH_CONTRACT_VERSION)
        self.assertTrue(alive["healthy"])
        self.assertTrue(alive["ready"])
        self.assertEqual(alive["detail"]["process_alive"], True)

        planned = service_health_record("future", "PLANNED")
        self.assertTrue(planned["healthy"])
        self.assertFalse(planned["ready"])

        degraded = service_health_record("broken", "DEGRADED")
        self.assertFalse(degraded["healthy"])
        self.assertFalse(degraded["ready"])

    def test_snapshot_reports_unhealthy_and_not_ready_services(self) -> None:
        snapshot = health_snapshot([
            {"service": "a", "status": "ALIVE", "detail": {}},
            {"service": "b", "status": "CONFIG_REQUIRED", "detail": {}},
            {"service": "c", "status": "PLANNED", "detail": {}},
        ])
        self.assertEqual(snapshot["service_count"], 3)
        self.assertEqual(snapshot["healthy_count"], 2)
        self.assertEqual(snapshot["ready_count"], 1)
        self.assertEqual(snapshot["unhealthy_services"], ["b"])
        self.assertEqual(snapshot["not_ready_count"], 2)
        self.assertEqual(snapshot["status_counts"]["CONFIG_REQUIRED"], 1)

    def test_persisted_health_round_trips_as_structured_detail(self) -> None:
        with TemporaryDirectory() as td:
            db = PlatformDB(root=Path(td))
            db.init()
            db.set_health("demo", "READY", {"configuration": {"configured": True}})
            rows = db.health_records()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["service"], "demo")
        self.assertEqual(rows[0]["status"], "READY")
        self.assertTrue(rows[0]["detail"]["configuration"]["configured"])
        self.assertTrue(rows[0]["checked_at_utc"])


if __name__ == "__main__":
    unittest.main()
