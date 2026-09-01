from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4
from .paths import project_root
from .db import PlatformDB
from .logging_setup import log_event

EVENT_VERSION = 2
VALID_SEVERITIES = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


@dataclass(slots=True)
class EventEnvelope:
    event_type: str
    source: str
    payload: dict[str, Any] = field(default_factory=dict)
    severity: str = "INFO"
    subject_type: str | None = None
    subject_id: str | None = None
    correlation_id: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    event_version: int = EVENT_VERSION

    def normalized(self) -> "EventEnvelope":
        severity = (self.severity or "INFO").upper()
        if severity not in VALID_SEVERITIES:
            severity = "INFO"
        event_type = (self.event_type or "unknown").strip().lower().replace(" ", "_")
        source = (self.source or "unknown").strip()
        return EventEnvelope(
            event_type=event_type,
            source=source,
            payload=dict(self.payload or {}),
            severity=severity,
            subject_type=(self.subject_type or None),
            subject_id=(str(self.subject_id) if self.subject_id is not None else None),
            correlation_id=(self.correlation_id or None),
            evidence=dict(self.evidence or {}),
            event_version=max(1, int(self.event_version or EVENT_VERSION)),
        )


def correlation_id(prefix: str = "vm") -> str:
    return f"{prefix}-{uuid4().hex}"


def publish(event: EventEnvelope, root: Path | None = None) -> int:
    root = root or project_root()
    item = event.normalized()
    db = PlatformDB(root=root)
    db.init()
    eid = db.add_event(
        item.event_type,
        item.source,
        item.payload,
        event_version=item.event_version,
        severity=item.severity,
        subject_type=item.subject_type,
        subject_id=item.subject_id,
        correlation_id=item.correlation_id,
        evidence=item.evidence,
    )
    log_event(
        "event_emitted",
        data={
            "event_id": eid,
            "event_type": item.event_type,
            "source": item.source,
            "severity": item.severity,
            "subject_type": item.subject_type,
            "subject_id": item.subject_id,
            "correlation_id": item.correlation_id,
        },
        root=root,
    )
    return eid


def emit(event_type: str, source: str = "manual", payload: dict[str, Any] | None = None,
         root: Path | None = None, *, severity: str = "INFO",
         subject_type: str | None = None, subject_id: str | int | None = None,
         correlation_id: str | None = None, evidence: dict[str, Any] | None = None) -> int:
    """Backward-compatible event publisher with structured metadata support."""
    return publish(
        EventEnvelope(
            event_type=event_type,
            source=source,
            payload=payload or {},
            severity=severity,
            subject_type=subject_type,
            subject_id=str(subject_id) if subject_id is not None else None,
            correlation_id=correlation_id,
            evidence=evidence or {},
        ),
        root=root,
    )
