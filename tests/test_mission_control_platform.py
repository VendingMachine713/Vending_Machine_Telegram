from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

from shared.vm_core.db import PlatformDB
from shared.vm_core.mission_control import MISSION_CONTROL_CONTRACT_VERSION, mission_control


class MissionControlPlatformTests(unittest.TestCase):
    def test_v4_platform_envelope_is_additive_and_passive(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            bot = root / "bots" / "Demo"
            bot.mkdir(parents=True)
            (bot / "main.py").write_text("print('ok')\n", encoding="utf-8")
            (bot / "BOT_MANIFEST.json").write_text(
                json.dumps({
                    "schema_version": 3,
                    "name": "Demo",
                    "version": "1.0.0",
                    "classification": "CANONICAL",
                    "entrypoint": "main.py",
                    "entrypoint_confidence": "high",
                    "launchers": [],
                    "capabilities": ["status"],
                    "runtime_requirements": {"env": [], "optional_env": []},
                    "lifecycle": {
                        "managed_by_vm": True,
                        "auto_start": False,
                        "auto_restart": False,
                    },
                }),
                encoding="utf-8",
            )
            db = PlatformDB(root=root)
            db.init()
            db.set_health("Demo", "READY", {"process_alive": False})
            db.upsert_incident(
                "incident:demo",
                "runtime",
                "test",
                "WARNING",
                "Demo attention",
                subject_type="service",
                subject_id="Demo",
            )
            db.upsert_signal(
                "signal:demo",
                "runtime_risk",
                "Demo attention signal",
                subject_type="service",
                subject_id="Demo",
                score=60,
                confidence=0.7,
            )

            summary = mission_control(root)

        self.assertEqual(summary["contract_version"], MISSION_CONTROL_CONTRACT_VERSION)
        self.assertIn("platform", summary)
        self.assertEqual(summary["platform"]["registry"]["service_count"], 1)
        self.assertEqual(summary["platform"]["health"]["service_count"], 1)
        self.assertEqual(summary["platform"]["health"]["ready_count"], 1)
        self.assertEqual(summary["platform"]["incident_intelligence"]["open_incident_count"], 1)
        self.assertEqual(summary["platform"]["incident_intelligence"]["active_signal_count"], 1)
        self.assertEqual(summary["headline"]["registered_services"], 1)
        self.assertFalse(summary["automatic_acceptance"])
        self.assertFalse(summary["automatic_execution"])
        self.assertFalse(summary["external_action_authority"])


if __name__ == "__main__":
    unittest.main()
