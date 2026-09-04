from __future__ import annotations

from pathlib import Path
from typing import Any

from .paths import project_root
from .service_adapters import adapter_registry
from .service_telemetry import service_telemetry_snapshot

FLEET_HEARTBEAT_CONTRACT_VERSION = 1


def _integration_evidence(root: Path, adapter: dict[str, Any]) -> dict[str, Any]:
    service = str(adapter["service"])
    entrypoint = adapter.get("preferred_entrypoint")
    path = root / "bots" / service / str(entrypoint or "")
    source = ""
    if entrypoint and path.is_file():
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            source = ""
    publisher_present = "BotEventPublisher" in source
    started_present = "publisher.started(" in source
    return {
        "service": service,
        "entrypoint": entrypoint,
        "publisher_present": publisher_present,
        "started_hook_present": started_present,
        "standard_heartbeat_inherited": publisher_present and started_present,
    }


def _incident_candidate(row: dict[str, Any], *, stale_seconds: int) -> dict[str, Any] | None:
    freshness = str(row.get("freshness") or "UNKNOWN")
    service = str(row.get("service") or "unknown")
    runtime_age = row.get("runtime_age_seconds")

    if freshness == "STALE":
        return {
            "incident_key": f"telemetry:heartbeat_stale:{service}",
            "incident_type": "service_heartbeat_stale",
            "source": "VM_Platform",
            "severity": "ERROR",
            "subject_type": "service",
            "subject_id": service,
            "summary": f"{service} is recorded RUNNING but its heartbeat is stale.",
            "evidence": {
                "freshness": freshness,
                "heartbeat_age_seconds": row.get("heartbeat_age_seconds"),
                "instance_id": row.get("instance_id"),
            },
        }
    if freshness == "INVALID":
        return {
            "incident_key": f"telemetry:heartbeat_invalid:{service}",
            "incident_type": "service_heartbeat_invalid",
            "source": "VM_Platform",
            "severity": "ERROR",
            "subject_type": "service",
            "subject_id": service,
            "summary": f"{service} has invalid heartbeat freshness evidence.",
            "evidence": {"freshness": freshness, "observed_at_utc": row.get("observed_at_utc")},
        }
    if freshness == "MISSING" and runtime_age is not None and int(runtime_age) > stale_seconds:
        return {
            "incident_key": f"telemetry:heartbeat_missing:{service}",
            "incident_type": "service_heartbeat_missing",
            "source": "VM_Platform",
            "severity": "WARNING",
            "subject_type": "service",
            "subject_id": service,
            "summary": f"{service} is recorded RUNNING without heartbeat evidence.",
            "evidence": {
                "freshness": freshness,
                "runtime_age_seconds": runtime_age,
                "sustained_seconds": stale_seconds,
            },
        }
    return None


def fleet_heartbeat_snapshot(root: Path | None = None, **telemetry_kwargs: Any) -> dict[str, Any]:
    """Return fleet heartbeat coverage and read-only incident candidates.

    Incident candidates are operator evidence only. This function never opens,
    resolves, executes, restarts, or otherwise mutates operational state.
    """
    root = root or project_root()
    telemetry = service_telemetry_snapshot(root, **telemetry_kwargs)
    adapters = adapter_registry(root)
    supported = [row for row in adapters["services"] if row.get("supported")]
    integration = [_integration_evidence(root, row) for row in supported]
    telemetry_by_service = {str(row["service"]): row for row in telemetry["services"]}

    rows: list[dict[str, Any]] = []
    for evidence in integration:
        service = evidence["service"]
        runtime = telemetry_by_service.get(service, {})
        rows.append({**evidence, "runtime": runtime})

    incident_candidates = [
        candidate
        for row in telemetry["services"]
        if (candidate := _incident_candidate(row, stale_seconds=int(telemetry["stale_seconds"]))) is not None
    ]
    integrated_count = sum(1 for row in integration if row["standard_heartbeat_inherited"])
    observed_count = sum(1 for row in rows if row["runtime"].get("heartbeat_present"))

    return {
        "contract_version": FLEET_HEARTBEAT_CONTRACT_VERSION,
        "status": "ATTENTION" if incident_candidates else telemetry["status"],
        "expected_service_count": len(supported),
        "integrated_service_count": integrated_count,
        "integration_coverage_percent": round((integrated_count / len(supported) * 100.0), 1) if supported else 100.0,
        "observed_heartbeat_count": observed_count,
        "observed_coverage_percent": round((observed_count / len(supported) * 100.0), 1) if supported else 100.0,
        "services": rows,
        "incident_candidate_count": len(incident_candidates),
        "incident_candidates": incident_candidates,
        "telemetry": telemetry,
        "read_only": True,
        "automatic_restart": False,
        "automatic_execution": False,
        "external_action_authority": False,
    }
