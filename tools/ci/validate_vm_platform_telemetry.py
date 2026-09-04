from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from shared.vm_core.db import PlatformDB
from shared.vm_core.service_telemetry import service_telemetry_snapshot


def main() -> int:
    with TemporaryDirectory() as td:
        root = Path(td)
        bot = root / "bots" / "VM_Guard"
        bot.mkdir(parents=True)
        (bot / "main.py").write_text("print('ok')\n", encoding="utf-8")
        (bot / "START.ps1").write_text("python main.py\n", encoding="utf-8")
        (bot / "BOT_MANIFEST.json").write_text(
            json.dumps(
                {
                    "schema_version": 3,
                    "name": "VM_Guard",
                    "version": "1.0.0",
                    "classification": "CANONICAL",
                    "entrypoint": "main.py",
                    "entrypoint_confidence": "high",
                    "launchers": ["START.ps1"],
                    "lifecycle": {
                        "managed_by_vm": True,
                        "auto_start": False,
                        "auto_restart": False,
                    },
                }
            ),
            encoding="utf-8",
        )
        db = PlatformDB(root=root)
        db.init()
        db.upsert_service("VM_Guard", "VM_Guard", "main.py", "START.ps1")
        db.set_service_runtime("VM_Guard", "RUNNING", 123)
        db.record_heartbeat(
            "VM_Guard",
            "ci-guard",
            "RUNNING",
            counters={"ticks": 1},
            observed_at_utc="2026-09-05T00:09:30+00:00",
        )
        snapshot = service_telemetry_snapshot(
            root,
            now=datetime(2026, 9, 5, 0, 10, tzinfo=timezone.utc),
        )

        assert snapshot["contract_version"] == 1
        assert snapshot["status"] == "HEALTHY"
        assert snapshot["running_count"] == 1
        assert snapshot["fresh_running_count"] == 1
        assert snapshot["services"][0]["freshness"] == "FRESH"
        assert snapshot["services"][0]["counters"] == {"ticks": 1}
        assert snapshot["read_only"] is True
        assert snapshot["automatic_execution"] is False
        assert snapshot["external_action_authority"] is False

    print("VM Platform passive telemetry contracts: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
