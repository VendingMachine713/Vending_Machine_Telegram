from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .db import Database, utcnow

VALID_QUEUE_STATUSES = {
    "pending", "retry", "sending", "deferred", "uncertain",
    "sent", "failed", "cancelled", "expired", "quarantined",
}
TERMINAL_QUEUE_STATUSES = {"sent", "failed", "cancelled", "expired", "quarantined"}


def integrity_report(db: Database, *, stale_sending_seconds: int = 300) -> dict:
    """Return a read-only health report for SQLite and queue-state invariants.

    This deliberately performs no repair. Stage 1 recovery must fail closed: a
    suspicious in-flight row is surfaced for recovery/reconciliation rather than
    silently rewritten while production may still be active.
    """
    stale_sending_seconds = max(30, int(stale_sending_seconds))
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=stale_sending_seconds)).isoformat(timespec="seconds")
    with db.connect() as con:
        quick = [str(r[0]) for r in con.execute("PRAGMA quick_check").fetchall()]
        foreign_keys = [dict(r) for r in con.execute("PRAGMA foreign_key_check").fetchall()]
        bad_status = [dict(r) for r in con.execute(
            "SELECT id,job_key,status FROM queue WHERE status NOT IN (?,?,?,?,?,?,?,?,?,?) ORDER BY id",
            tuple(sorted(VALID_QUEUE_STATUSES)),
        ).fetchall()]
        stale_sending = [dict(r) for r in con.execute(
            "SELECT id,job_key,campaign_id,group_id,updated_at FROM queue WHERE status='sending' AND updated_at<? ORDER BY id",
            (cutoff,),
        ).fetchall()]
        terminal_without_resolution = [dict(r) for r in con.execute(
            "SELECT id,job_key,status FROM queue WHERE status IN ('sent','failed','cancelled','expired','quarantined') AND resolved_at IS NULL ORDER BY id"
        ).fetchall()]
        uncertain_without_reason = [dict(r) for r in con.execute(
            "SELECT id,job_key FROM queue WHERE status='uncertain' AND (error_kind IS NULL OR error_kind='') ORDER BY id"
        ).fetchall()]
        impossible_attempts = [dict(r) for r in con.execute(
            "SELECT id,job_key,attempts,max_attempts FROM queue WHERE attempts<0 OR max_attempts<1 OR attempts>max_attempts ORDER BY id"
        ).fetchall()]

    issues = {
        "foreign_key_violations": foreign_keys,
        "invalid_queue_status": bad_status,
        "stale_sending": stale_sending,
        "terminal_without_resolution": terminal_without_resolution,
        "uncertain_without_reason": uncertain_without_reason,
        "invalid_attempt_counters": impossible_attempts,
    }
    counts = {key: len(value) for key, value in issues.items()}
    quick_ok = quick == ["ok"]
    return {
        "checked_at": utcnow(),
        "quick_check": quick,
        "quick_check_ok": quick_ok,
        "healthy": quick_ok and not any(counts.values()),
        "issue_counts": counts,
        "issues": issues,
        "stale_sending_seconds": stale_sending_seconds,
    }
