from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Mapping
import json
import uuid


ALLOWED_LEVELS = {"debug", "info", "warning", "error", "critical"}
ALLOWED_OUTCOMES = {"unknown", "success", "failure", "partial", "skipped"}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class Event:
    source: str
    kind: str
    action: str
    outcome: str = "unknown"
    level: str = "info"
    duration_ms: float | None = None
    value: float | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    timestamp_utc: str = field(default_factory=utc_now_iso)
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def __post_init__(self) -> None:
        if not self.source.strip():
            raise ValueError("event source is required")
        if not self.kind.strip():
            raise ValueError("event kind is required")
        if not self.action.strip():
            raise ValueError("event action is required")
        if self.level not in ALLOWED_LEVELS:
            raise ValueError(f"invalid level: {self.level}")
        if self.outcome not in ALLOWED_OUTCOMES:
            raise ValueError(f"invalid outcome: {self.outcome}")
        if self.duration_ms is not None and self.duration_ms < 0:
            raise ValueError("duration_ms must be >= 0")

    def to_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["metadata_json"] = json.dumps(dict(self.metadata), sort_keys=True, default=str)
        record.pop("metadata", None)
        return record


class Telemetry:
    """Tiny bot-facing SDK. Failure to emit telemetry must never crash a bot."""

    def __init__(self, store, source: str):
        self.store = store
        self.source = source

    def emit(
        self,
        kind: str,
        action: str,
        *,
        outcome: str = "unknown",
        level: str = "info",
        duration_ms: float | None = None,
        value: float | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> bool:
        try:
            self.store.add_event(
                Event(
                    source=self.source,
                    kind=kind,
                    action=action,
                    outcome=outcome,
                    level=level,
                    duration_ms=duration_ms,
                    value=value,
                    metadata=metadata or {},
                )
            )
            return True
        except Exception:
            return False
