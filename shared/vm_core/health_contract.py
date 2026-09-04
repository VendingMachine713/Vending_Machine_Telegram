from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any, Iterable

HEALTH_CONTRACT_VERSION = 1
HEALTH_STATUSES = frozenset({
    "ALIVE",
    "READY",
    "DEGRADED",
    "CONFIG_REQUIRED",
    "PLANNED",
    "UNKNOWN",
})
HEALTHY_STATUSES = frozenset({"ALIVE", "READY", "PLANNED"})
READY_STATUSES = frozenset({"ALIVE", "READY"})


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_health_status(status: Any) -> str:
    normalized = str(status or "UNKNOWN").strip().upper()
    return normalized if normalized in HEALTH_STATUSES else "UNKNOWN"


def service_health_record(
    service: str,
    status: Any,
    *,
    detail: dict[str, Any] | None = None,
    checked_at_utc: str | None = None,
) -> dict[str, Any]:
    """Return the stable, serialisable VM Platform service-health contract."""
    normalized = normalize_health_status(status)
    return {
        "contract_version": HEALTH_CONTRACT_VERSION,
        "service": str(service),
        "status": normalized,
        "healthy": normalized in HEALTHY_STATUSES,
        "ready": normalized in READY_STATUSES,
        "checked_at_utc": checked_at_utc or _utcnow(),
        "detail": dict(detail or {}),
    }


def health_snapshot(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Normalize service-health rows and summarize them without changing source state."""
    normalized: list[dict[str, Any]] = []
    for row in records:
        normalized.append(
            service_health_record(
                str(row.get("service") or "unknown"),
                row.get("status"),
                detail=row.get("detail") if isinstance(row.get("detail"), dict) else {},
                checked_at_utc=str(row.get("checked_at_utc") or "") or None,
            )
        )

    counts = Counter(item["status"] for item in normalized)
    unhealthy = [item for item in normalized if not item["healthy"]]
    not_ready = [item for item in normalized if not item["ready"]]
    return {
        "contract_version": HEALTH_CONTRACT_VERSION,
        "service_count": len(normalized),
        "healthy_count": sum(1 for item in normalized if item["healthy"]),
        "ready_count": sum(1 for item in normalized if item["ready"]),
        "status_counts": dict(sorted(counts.items())),
        "unhealthy_count": len(unhealthy),
        "not_ready_count": len(not_ready),
        "unhealthy_services": [item["service"] for item in unhealthy],
        "services": normalized,
    }
