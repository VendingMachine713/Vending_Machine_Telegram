from __future__ import annotations

from shared.vm_core.fleet_heartbeat import fleet_heartbeat_snapshot

EXPECTED_SERVICES = {
    "Universal_Search",
    "VM_Guard",
    "Admin_Command_Centre",
    "VM_Relationship_Manager",
    "Smart_Auto_Poster_V2",
}


def main() -> int:
    snapshot = fleet_heartbeat_snapshot()
    services = {row["service"] for row in snapshot["services"]}

    missing = sorted(EXPECTED_SERVICES - services)
    if missing:
        raise SystemExit(f"fleet heartbeat coverage missing services: {missing}")
    if snapshot["integrated_service_count"] < len(EXPECTED_SERVICES):
        incomplete = [
            row["service"]
            for row in snapshot["services"]
            if row["service"] in EXPECTED_SERVICES and not row["standard_heartbeat_inherited"]
        ]
        raise SystemExit(f"fleet heartbeat integration incomplete: {incomplete}")
    if snapshot["integration_coverage_percent"] != 100.0:
        raise SystemExit(f"unexpected integration coverage: {snapshot['integration_coverage_percent']}")
    if not snapshot["read_only"]:
        raise SystemExit("fleet heartbeat snapshot must remain read-only")
    if snapshot["automatic_restart"] or snapshot["automatic_execution"] or snapshot["external_action_authority"]:
        raise SystemExit("fleet heartbeat layer must not grant action authority")

    print(
        "VM Platform v4.3 fleet heartbeat contracts: OK "
        f"integrated={snapshot['integrated_service_count']}/{snapshot['expected_service_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
