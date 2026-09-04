from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from .db import PlatformDB
from .paths import project_root
from .service_adapters import adapter_registry

TELEMETRY_CONTRACT_VERSION = 1
DEFAULT_FRESH_SECONDS = 120
DEFAULT_STALE_SECONDS = 600


def _utc(value: datetime | None = None) -> datetime:
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    try:
        decoded = json.loads(value or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _age_seconds(now: datetime, value: Any) -> int | None:
    parsed = _parse_time(value)
    if parsed is None:
        return None
    return max(0, int((now - parsed).total_seconds()))


def _freshness(
    *,
    running: bool,
    observed_at_utc: Any,
    now: datetime,
    fresh_seconds: int,
    stale_seconds: int,
) -> tuple[str, int | None]:
    if not observed_at_utc:
        return ("MISSING" if running else "NOT_EXPECTED", None)
    age = _age_seconds(now, observed_at_utc)
    if age is None:
        return ("INVALID" if running else "NOT_EXPECTED", None)
    if age <= fresh_seconds:
        return "FRESH", age
    if age <= stale_seconds:
        return "LATE", age
    return "STALE", age


def service_telemetry_snapshot(
    root: Path | None = None,
    *,
    now: datetime | None = None,
    fresh_seconds: int = DEFAULT_FRESH_SECONDS,
    stale_seconds: int = DEFAULT_STALE_SECONDS,
) -> dict[str, Any]:
    """Return passive per-service runtime/heartbeat telemetry.

    The read model never starts, stops, restarts, or writes to a service. Heartbeat
    absence is attention-worthy only for services already recorded as RUNNING.
    """
    root = root or project_root()
    fresh_seconds = max(1, int(fresh_seconds))
    stale_seconds = max(fresh_seconds, int(stale_seconds))
    observed_now = _utc(now)

    db = PlatformDB(root=root)
    db.init()
    runtime_rows = {str(row["name"]): row for row in db.services()}
    heartbeat_rows = {str(row["service"]): row for row in db.latest_heartbeats()}
    adapters = adapter_registry(root)
    adapter_rows = {str(row["service"]): row for row in adapters["services"]}

    service_names = sorted(
        set(runtime_rows) | set(heartbeat_rows) | set(adapter_rows),
        key=str.lower,
    )
    rows: list[dict[str, Any]] = []
    freshness_counts: dict[str, int] = {}

    for service in service_names:
        runtime = runtime_rows.get(service, {})
        heartbeat = heartbeat_rows.get(service, {})
        adapter = adapter_rows.get(service, {})
        runtime_status = str(runtime.get("runtime_status") or "UNKNOWN").upper()
        running = runtime_status == "RUNNING"
        freshness, age_seconds = _freshness(
            running=running,
            observed_at_utc=heartbeat.get("observed_at_utc"),
            now=observed_now,
            fresh_seconds=fresh_seconds,
            stale_seconds=stale_seconds,
        )
        freshness_counts[freshness] = freshness_counts.get(freshness, 0) + 1
        last_success_age = _age_seconds(observed_now, heartbeat.get("last_success_utc"))
        rows.append(
            {
                "service": service,
                "runtime_status": runtime_status,
                "pid_known": runtime.get("pid") is not None,
                "adapter_supported": bool(adapter.get("supported", False)),
                "adapter_id": adapter.get("adapter_id"),
                "heartbeat_expected": running,
                "heartbeat_present": bool(heartbeat),
                "heartbeat_status": (
                    str(heartbeat.get("status") or "UNKNOWN").upper() if heartbeat else None
                ),
                "instance_id": heartbeat.get("instance_id"),
                "freshness": freshness,
                "heartbeat_age_seconds": age_seconds,
                "observed_at_utc": heartbeat.get("observed_at_utc"),
                "last_success_utc": heartbeat.get("last_success_utc"),
                "last_success_age_seconds": last_success_age,
                "active_task": heartbeat.get("active_task"),
                "recovery_state": heartbeat.get("recovery_state"),
                "last_error": heartbeat.get("last_error"),
                "counters": _json_object(heartbeat.get("counters_json")),
            }
        )

    running_rows = [row for row in rows if row["heartbeat_expected"]]
    attention_rows = [
        row for row in running_rows if row["freshness"] in {"MISSING", "STALE", "INVALID"}
    ]
    late_rows = [row for row in running_rows if row["freshness"] == "LATE"]
    fresh_rows = [row for row in running_rows if row["freshness"] == "FRESH"]

    if attention_rows:
        status = "ATTENTION"
    elif late_rows:
        status = "DEGRADED"
    elif running_rows:
        status = "HEALTHY"
    else:
        status = "IDLE"

    return {
        "contract_version": TELEMETRY_CONTRACT_VERSION,
        "status": status,
        "observed_at_utc": observed_now.isoformat(),
        "fresh_seconds": fresh_seconds,
        "stale_seconds": stale_seconds,
        "service_count": len(rows),
        "running_count": len(running_rows),
        "fresh_running_count": len(fresh_rows),
        "late_running_count": len(late_rows),
        "attention_running_count": len(attention_rows),
        "missing_running_heartbeat_count": sum(
            1 for row in running_rows if row["freshness"] == "MISSING"
        ),
        "stale_running_heartbeat_count": sum(
            1 for row in running_rows if row["freshness"] == "STALE"
        ),
        "freshness_counts": freshness_counts,
        "attention_services": attention_rows,
        "late_services": late_rows,
        "services": rows,
        "read_only": True,
        "automatic_execution": False,
        "external_action_authority": False,
    }
