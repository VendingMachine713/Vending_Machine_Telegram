from __future__ import annotations

from pathlib import Path
from threading import Event, Thread
from typing import Any

from .events import emit, correlation_id
from .heartbeat import record_heartbeat
from .intelligence_contracts import IntelligenceRecord


HEARTBEAT_INTERVAL_SECONDS = 45.0


class BotEventPublisher:
    """Small, failure-isolated integration surface for every VM bot.

    Publishing telemetry must never be allowed to crash the bot that is doing
    useful work. Callers may inspect ``last_error`` for diagnostics, while
    normal application control flow continues unchanged.

    ``started()`` also establishes a lightweight durable heartbeat lease. The
    lease is intentionally implemented inside VM Core so every integrated bot
    gets the same cadence and failure isolation without bot-specific timers.
    """

    def __init__(self, source: str, root: Path, *, instance_id: str | None = None):
        self.source = source
        self.root = root
        self.instance_id = instance_id or correlation_id(source.lower().replace("_", "-"))
        self.last_error: str | None = None
        self._heartbeat_stop: Event | None = None
        self._heartbeat_thread: Thread | None = None

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

    def _record_durable_heartbeat(self, *, status: str = "healthy") -> None:
        try:
            record_heartbeat(
                self.source,
                self.instance_id,
                status=status,
                root=self.root,
            )
            self.last_error = None
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"

    def _heartbeat_worker(self, stop: Event, interval_seconds: float) -> None:
        while not stop.wait(interval_seconds):
            if not self.root.exists():
                return
            self._record_durable_heartbeat()

    def start_heartbeat_loop(self, *, interval_seconds: float = HEARTBEAT_INTERVAL_SECONDS) -> None:
        """Start one failure-isolated durable heartbeat loop for this publisher.

        Repeated calls are idempotent. The periodic loop updates only the
        heartbeat registry; it does not emit a telemetry event every interval,
        avoiding event-store noise while preserving freshness evidence.
        """
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        if self._heartbeat_thread is not None and self._heartbeat_thread.is_alive():
            return

        self._record_durable_heartbeat()
        stop = Event()
        thread = Thread(
            target=self._heartbeat_worker,
            args=(stop, float(interval_seconds)),
            name=f"vm-heartbeat-{self.source}",
            daemon=True,
        )
        self._heartbeat_stop = stop
        self._heartbeat_thread = thread
        thread.start()

    def stop_heartbeat_loop(self) -> None:
        stop = self._heartbeat_stop
        if stop is not None:
            stop.set()
        self._heartbeat_stop = None
        self._heartbeat_thread = None

    def started(self, **details: Any) -> int | None:
        self.start_heartbeat_loop()
        return self._publish(
            "service.started",
            details,
            subject_type="service",
            subject_id=self.source,
        )

    def heartbeat(self, status: str = "ok", **details: Any) -> int | None:
        counters = details.pop("counters", None)
        active_task = details.pop("active_task", None)
        last_success_utc = details.pop("last_success_utc", None)
        last_error = details.pop("last_error", None)
        recovery_state = details.pop("recovery_state", None)
        try:
            record_heartbeat(
                self.source,
                self.instance_id,
                status=status,
                active_task=active_task,
                counters=counters if isinstance(counters, dict) else {},
                last_success_utc=last_success_utc,
                last_error=last_error,
                recovery_state=recovery_state,
                root=self.root,
            )
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
        return self._publish(
            "service.heartbeat",
            {
                "status": status,
                "active_task": active_task,
                "counters": counters if isinstance(counters, dict) else {},
                "last_success_utc": last_success_utc,
                "last_error": last_error,
                "recovery_state": recovery_state,
                **details,
            },
            subject_type="service",
            subject_id=self.source,
            severity="WARNING" if status.lower() not in {"ok", "online", "idle", "healthy"} else "INFO",
        )

    def stopped(self, reason: str = "normal", **details: Any) -> int | None:
        self.stop_heartbeat_loop()
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

    def intelligence(self, record: IntelligenceRecord) -> int | None:
        """Publish one canonical VM Brain trust-layer record.

        Record confidence/freshness are calculated by the trust contract before
        publishing, keeping bot producers from inventing unexplained scores.
        The publisher remains failure-isolated just like all other telemetry.
        """
        if record.source != self.source:
            self.last_error = (
                "IntelligenceContractError: record source does not match publisher source"
            )
            return None
        return self._publish(
            record.event_type,
            record.event_payload(),
            subject_type=record.subject_type,
            subject_id=record.subject_id,
            evidence=record.event_evidence(),
            correlation_id=f"brain:{record.kind.value}:{record.subject_type}:{record.subject_id}",
        )

    def action(self, action_type: str, *, actor_id: str | int | None = None,
               target_type: str | None = None, target_id: str | int | None = None,
               mutating: bool = False, outcome: str = "accepted", **details: Any) -> int | None:
        """Publish a compact audit event for an administrative action.

        Raw command text is intentionally not recorded because future commands
        may carry sensitive arguments. Store only normalized action/target data.
        """
        return self._publish(
            f"admin.{action_type}",
            {
                "actor_id": str(actor_id) if actor_id is not None else None,
                "mutating": bool(mutating),
                "outcome": outcome,
                **details,
            },
            subject_type=target_type or "service",
            subject_id=target_id if target_id is not None else self.source,
        )
