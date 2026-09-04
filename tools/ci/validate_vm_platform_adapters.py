from __future__ import annotations

from shared.vm_core.mission_control import mission_control
from shared.vm_core.platform_registry import service_registry
from shared.vm_core.service_adapters import adapter_registry

EXPECTED = {
    "Universal_Search": "universal-search-v1",
    "VM_Guard": "vm-guard-v1",
    "Admin_Command_Centre": "admin-command-centre-v1",
    "VM_Relationship_Manager": "relationship-manager-v1",
    "Smart_Auto_Poster_V2": "smart-auto-poster-v1",
}


def main() -> int:
    adapters = adapter_registry()
    by_service = {row["service"]: row for row in adapters["services"]}

    missing = sorted(set(EXPECTED) - set(by_service))
    if missing:
        raise SystemExit(f"missing adapter services: {missing}")

    for service, adapter_id in EXPECTED.items():
        row = by_service[service]
        if row["adapter_id"] != adapter_id:
            raise SystemExit(f"unexpected adapter id for {service}: {row['adapter_id']}")
        if row["status"] != "READY":
            raise SystemExit(f"adapter not ready for {service}: {row['status']} missing={row['missing']}")
        if row["safe_operations"] != ["status", "health", "inspect"]:
            raise SystemExit(f"unsafe adapter operations for {service}: {row['safe_operations']}")

    if adapters["automatic_execution"] or adapters["external_action_authority"]:
        raise SystemExit("adapter registry must not grant action authority")

    registry = service_registry()
    if registry["schema_version"] < 2:
        raise SystemExit("service registry schema did not advance for adapter metadata")
    if registry["adapter_ready_count"] < len(EXPECTED):
        raise SystemExit("service registry does not report all active adapters ready")

    control = mission_control(limit=5)
    if control["contract_version"] != 4 or control["platform"]["revision"] != 1:
        raise SystemExit("Mission Control adapter revision is not exposed")
    if control["automatic_acceptance"] or control["automatic_execution"] or control["external_action_authority"]:
        raise SystemExit("Mission Control safety authority changed unexpectedly")

    print(
        "VM Platform v4.1 adapters validated: "
        f"supported={adapters['supported_count']} ready={adapters['ready_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
