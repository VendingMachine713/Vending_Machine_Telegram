from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .db import Database, utcnow


@dataclass(frozen=True)
class SafetyState:
    paused: bool
    reason: str | None
    until: str | None
    manual: bool
    successes: int = 0
    failures: int = 0


class SafetyController:
    """Outbound circuit breaker and manual pause controller."""

    def __init__(
        self,
        db: Database,
        *,
        failure_threshold: int = 10,
        window_minutes: int = 10,
        pause_minutes: int = 30,
        failure_ratio: float = 0.80,
    ):
        self.db = db
        self.failure_threshold = max(1, int(failure_threshold))
        self.window_minutes = max(1, int(window_minutes))
        self.pause_minutes = max(1, int(pause_minutes))
        self.failure_ratio = min(1.0, max(0.0, float(failure_ratio)))

    @staticmethod
    def _parse(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            dt = datetime.fromisoformat(value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            return None

    def _meta(self) -> dict[str, str]:
        with self.db.connect() as con:
            return {r["key"]: r["value"] for r in con.execute(
                "SELECT key,value FROM meta WHERE key LIKE 'safety_%'"
            ).fetchall()}

    def _set_meta(self, **items):
        with self.db.connect() as con:
            for key, value in items.items():
                full = f"safety_{key}"
                if value is None:
                    con.execute("DELETE FROM meta WHERE key=?", (full,))
                else:
                    con.execute(
                        "INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (full, str(value)),
                    )

    def counts(self) -> tuple[int, int]:
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=self.window_minutes)).isoformat(timespec="seconds")
        with self.db.connect() as con:
            rows = con.execute(
                """SELECT event_type,COUNT(*) AS n FROM events
                   WHERE created_at>=? AND event_type IN ('send_success','send_failure')
                   GROUP BY event_type""",
                (cutoff,),
            ).fetchall()
        counts = {r["event_type"]: int(r["n"]) for r in rows}
        return counts.get("send_success", 0), counts.get("send_failure", 0)

    def status(self) -> SafetyState:
        meta = self._meta()
        manual = meta.get("safety_manual_pause") == "1"
        until_raw = meta.get("safety_paused_until")
        reason = meta.get("safety_reason")
        until = self._parse(until_raw)
        paused = manual or bool(until and until > datetime.now(timezone.utc))
        successes, failures = self.counts()
        if not paused and until_raw:
            # Expired automatic pause: clear stale pause metadata.
            self._set_meta(paused_until=None, reason=None)
            until_raw = None
            reason = None
        return SafetyState(paused, reason, until_raw if paused else None, manual, successes, failures)

    def pause(self, reason: str, minutes: int | None = None, *, manual: bool = False) -> SafetyState:
        reason = (reason or "outbound paused").strip()[:500]
        if manual and minutes is None:
            self._set_meta(manual_pause="1", paused_until=None, reason=reason)
        else:
            duration = max(1, int(minutes or self.pause_minutes))
            until = (datetime.now(timezone.utc) + timedelta(minutes=duration)).isoformat(timespec="seconds")
            self._set_meta(manual_pause="0", paused_until=until, reason=reason)
        self.db.event("WARNING", "safety_pause", reason)
        return self.status()

    def resume(self, reason: str = "manual resume") -> SafetyState:
        self._set_meta(manual_pause=None, paused_until=None, reason=None)
        self.db.event("INFO", "safety_resume", reason[:500])
        return self.status()

    def evaluate(self) -> SafetyState:
        current = self.status()
        if current.paused:
            return current
        successes, failures = current.successes, current.failures
        total = successes + failures
        if failures < self.failure_threshold or total <= 0:
            return current
        ratio = failures / total
        if ratio < self.failure_ratio:
            return current
        reason = (
            f"Circuit breaker: {failures}/{total} sends failed in the last "
            f"{self.window_minutes} minute(s) ({ratio:.0%} failure rate)"
        )
        return self.pause(reason, self.pause_minutes, manual=False)
