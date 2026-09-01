from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Mapping

from .progress import clamp_percent, plain_stage, text_bar


TERMINAL_STATUSES = {"sent", "failed", "quarantined", "cancelled", "expired", "uncertain"}
ATTENTION_STATUSES = {"failed", "quarantined", "uncertain"}

_STATUS_WEIGHT = {
    "pending": 0,
    "deferred": 10,
    "retry": 15,
    "sending": 70,
    "sent": 100,
    "failed": 100,
    "quarantined": 100,
    "cancelled": 100,
    "expired": 100,
    "uncertain": 100,
}

_STAGE_FOR_STATUS = {
    "pending": "queued",
    "deferred": "deferred",
    "retry": "retry",
    "sending": "uploading",
    "sent": "sent",
    "failed": "failed",
    "quarantined": "failed",
    "cancelled": "failed",
    "expired": "failed",
    "uncertain": "uncertain",
}


@dataclass(frozen=True, slots=True)
class QueueSnapshot:
    total: int
    complete: int
    successful: int
    attention: int
    active: int
    waiting: int
    percent: int
    counts: dict[str, int]

    @property
    def healthy(self) -> bool:
        return self.attention == 0


def _status(row: Mapping[str, object]) -> str:
    return str(row.get("status") or "unknown").strip().lower()


def job_percent(status: str) -> int:
    return _STATUS_WEIGHT.get(status.strip().lower(), 0)


def summarise_queue(rows: Iterable[Mapping[str, object]]) -> QueueSnapshot:
    materialized = list(rows)
    counts = Counter(_status(row) for row in materialized)
    total = len(materialized)
    if total == 0:
        return QueueSnapshot(0, 0, 0, 0, 0, 0, 0, {})

    complete = sum(counts[s] for s in TERMINAL_STATUSES)
    successful = counts["sent"]
    attention = sum(counts[s] for s in ATTENTION_STATUSES)
    active = counts["sending"]
    waiting = total - complete - active
    percent = clamp_percent(sum(job_percent(_status(row)) for row in materialized) / total)

    return QueueSnapshot(
        total=total,
        complete=complete,
        successful=successful,
        attention=attention,
        active=active,
        waiting=waiting,
        percent=percent,
        counts=dict(sorted(counts.items())),
    )


def render_snapshot(snapshot: QueueSnapshot) -> str:
    if snapshot.total == 0:
        return "No delivery jobs found."

    health = "OK - no action needed" if snapshot.healthy else f"ATTENTION - {snapshot.attention} job(s) need review"
    lines = [
        "SMART AUTO POSTER - DELIVERY PROGRESS",
        text_bar(snapshot.percent),
        f"Complete: {snapshot.complete}/{snapshot.total}",
        f"Successful: {snapshot.successful}",
        f"Currently posting: {snapshot.active}",
        f"Waiting / deferred / retrying: {snapshot.waiting}",
        f"Status: {health}",
    ]

    if snapshot.counts:
        detail = ", ".join(f"{name}={count}" for name, count in snapshot.counts.items())
        lines.append(f"Queue: {detail}")
    return "\n".join(lines)


def render_job(row: Mapping[str, object]) -> str:
    status = _status(row)
    stage = _STAGE_FOR_STATUS.get(status, status)
    percent = job_percent(status)
    group_name = str(row.get("group_name") or row.get("group_id") or "Unknown destination")
    account = row.get("account_key") or "auto"
    error = str(row.get("last_error") or "").strip()

    lines = [
        f"{group_name}",
        text_bar(percent),
        f"{plain_stage(stage)} | account={account}",
    ]
    if error and status in ATTENTION_STATUSES | {"retry", "deferred"}:
        lines.append(f"Detail: {error[:300]}")
    return "\n".join(lines)
