from __future__ import annotations
from pathlib import Path
from typing import Any

from .events import emit, correlation_id


class BotEventPublisher:
    """Small, failure-isolated integration surface for every VM bot.

    Publishing telemetry must never be allowed to crash the bot that is doing
    useful work. Callers may inspect ``last_error`` for diagnostics, while
    normal application control flow continues unchanged.
    """

    def __init__(self, source: str, root: Path, *, instance_id: str | None = None):
        self.source = source
        self.root = root
        self.instance_id = instance_id or correlation_id(source.lower().replace("_", "-"))
        self.last_error: str | None = None

    def _publish(self, event_type: str, payload: dict[str, Any] | None = None, **meta: Any) -> int | None:
        body = dict(payload or {})
        body.setdefault("instance_id", self.instance_id)
        try:
            event_id = emit(
                event_type,
                self.source,
                body,
                self.root,
                correlation_id=meta.pop("correlation_id", self.instance_id),
                **meta,
            )
            self.last_error = None
            return event_id
        except Exception as exc:  # telemetry must not take down a production bot
            self.last_error = f"{type(exc).__name__}: {exc}"
            return None

    def started(self, **details: Any) -> int | None:
        return self._publish(
            "service.started",
            details,
            subject_type="service",
            subject_id=self.source,
        )

    def heartbeat(self, status: str = "ok", **details: Any) -> int | None:
        return self._publish(
            "service.heartbeat",
            {"status": status, **details},
            subject_type="service",
            subject_id=self.source,
            severity="WARNING" if status.lower() not in {"ok", "online", "idle", "healthy"} else "INFO",
        )

    def stopped(self, reason: str = "normal", **details: Any) -> int | None:
        return self._publish(
            "service.stopped",
            {"reason": reason, **details},
            subject_type="service",
            subject_id=self.source,
        )

    def incident(self, incident_type: str, summary: str, *, severity: str = "ERROR",
                 subject_type: str = "service", subject_id: str | int | None = None,
                 evidence: dict[str, Any] | None = None, **details: Any) -> int | None:
        return self._publish(
            f"incident.{incident_type}",
            {"summary": summary, **details},
            severity=severity,
            subject_type=subject_type,
            subject_id=subject_id if subject_id is not None else self.source,
            evidence=evidence or {},
        )

    def signal(self, signal_type: str, *, subject_type: str, subject_id: str | int,
               score: float, confidence: float, rationale: str,
               evidence: dict[str, Any] | None = None, **details: Any) -> int | None:
        return self._publish(
            f"signal.{signal_type}",
            {
                "score": float(score),
                "confidence": float(confidence),
                "rationale": rationale,
                **details,
            },
            subject_type=subject_type,
            subject_id=subject_id,
            evidence=evidence or {},
        )
