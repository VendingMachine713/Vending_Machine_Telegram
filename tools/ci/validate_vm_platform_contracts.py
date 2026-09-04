from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from shared.vm_core.db import PlatformDB
from shared.vm_core.health_contract import HEALTH_CONTRACT_VERSION, service_health_record
from shared.vm_core.mission_control import MISSION_CONTROL_CONTRACT_VERSION, mission_control


def _write_demo_manifest(root: Path) -> None:
    bot = root / "bots" / "ContractDemo"
    bot.mkdir(parents=True)
    (bot / "main.py").write_text("print('ok')\n", encoding="utf-8")
    (bot / "BOT_MANIFEST.json").write_text(
        json.dumps(
            {
                "schema_version": 3,
                "name": "ContractDemo",
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
            }
        ),
        encoding="utf-8",
    )


def main() -> int:
    health = service_health_record("ContractDemo", "READY")
    assert health["contract_version"] == HEALTH_CONTRACT_VERSION
    assert health["ready"] is True

    with TemporaryDirectory() as td:
        root = Path(td)
        _write_demo_manifest(root)
        db = PlatformDB(root=root)
        db.init()
        db.set_health("ContractDemo", "READY", {"process_alive": False})
        db.upsert_incident(
            "contract:demo",
            "contract",
            "ci",
            "WARNING",
            "Contract smoke-test incident",
            subject_type="service",
            subject_id="ContractDemo",
        )
        db.upsert_signal(
            "contract:demo",
            "contract_signal",
            "Contract smoke-test signal",
            subject_type="service",
            subject_id="ContractDemo",
            score=50,
            confidence=0.5,
        )
        summary = mission_control(root)

    assert summary["contract_version"] == MISSION_CONTROL_CONTRACT_VERSION
    assert summary["platform"]["registry"]["service_count"] == 1
    assert summary["platform"]["health"]["ready_count"] == 1
    aggregation = summary["platform"]["incident_intelligence"]
    assert aggregation["open_incident_count"] == 1
    assert aggregation["active_signal_count"] == 1
    assert summary["automatic_execution"] is False
    assert summary["external_action_authority"] is False
    print("VM Platform Foundation v4 contracts: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
