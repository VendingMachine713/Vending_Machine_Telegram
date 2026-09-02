from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .db import Database, utcnow

VALID_QUEUE_STATUSES = {
    "pending", "retry", "sending", "deferred", "uncertain",
    "sent", "failed", "cancelled", "expired", "quarantined",
}
TERMINAL_QUEUE_STATUSES = {"sent", "failed", "cancelled", "expired", "quarantined"}


def _table_exists(con, name: str) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone() is not None


def integrity_report(db: Database, *, stale_sending_seconds: int = 300) -> dict:
    """Return a read-only health report for SQLite and durable queue invariants.

    This deliberately performs no repair. Stage 1 recovery must fail closed: a
    suspicious in-flight row, delivery-attempt mismatch, or run-seal mismatch is
    surfaced for recovery/reconciliation rather than silently rewritten while
    production may still be active.
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

        delivery_open_on_resolved_queue = []
        acknowledged_without_message_ids = []
        final_attempt_without_finished_at = []
        if _table_exists(con, "delivery_attempts"):
            delivery_open_on_resolved_queue = [dict(r) for r in con.execute(
                """SELECT da.id AS attempt_id,da.queue_job_id,da.outcome,q.status AS queue_status
                   FROM delivery_attempts da JOIN queue q ON q.id=da.queue_job_id
                   WHERE da.outcome IN ('started','acknowledged')
                     AND q.status IN ('sent','failed','cancelled','expired','quarantined','uncertain')
                   ORDER BY da.id"""
            ).fetchall()]
            acknowledged_without_message_ids = [dict(r) for r in con.execute(
                """SELECT id AS attempt_id,queue_job_id
                   FROM delivery_attempts
                   WHERE outcome='acknowledged'
                     AND (telegram_message_ids IS NULL OR telegram_message_ids='' OR telegram_message_ids='[]')
                   ORDER BY id"""
            ).fetchall()]
            final_attempt_without_finished_at = [dict(r) for r in con.execute(
                """SELECT id AS attempt_id,queue_job_id,outcome
                   FROM delivery_attempts
                   WHERE outcome IN ('sent','failed','uncertain') AND finished_at IS NULL
                   ORDER BY id"""
            ).fetchall()]

        unsealed_queue_runs = []
        sealed_run_count_mismatch = []
        if _table_exists(con, "queue_run_seals"):
            unsealed_queue_runs = [dict(r) for r in con.execute(
                """SELECT q.campaign_id,q.run_key,COUNT(*) AS queue_jobs
                   FROM queue q
                   LEFT JOIN queue_run_seals rs
                     ON rs.campaign_id=q.campaign_id AND rs.run_key=q.run_key
                   WHERE q.run_key IS NOT NULL AND q.run_key<>'' AND rs.run_key IS NULL
                   GROUP BY q.campaign_id,q.run_key
                   ORDER BY q.campaign_id,q.run_key"""
            ).fetchall()]
            sealed_run_count_mismatch = [dict(r) for r in con.execute(
                """SELECT rs.campaign_id,rs.run_key,rs.job_count,COUNT(q.id) AS queue_jobs
                   FROM queue_run_seals rs
                   LEFT JOIN queue q
                     ON q.campaign_id=rs.campaign_id AND q.run_key=rs.run_key
                   GROUP BY rs.campaign_id,rs.run_key,rs.job_count
                   HAVING rs.job_count<>COUNT(q.id)
                   ORDER BY rs.campaign_id,rs.run_key"""
            ).fetchall()]

    issues = {
        "foreign_key_violations": foreign_keys,
        "invalid_queue_status": bad_status,
        "stale_sending": stale_sending,
        "terminal_without_resolution": terminal_without_resolution,
        "uncertain_without_reason": uncertain_without_reason,
        "invalid_attempt_counters": impossible_attempts,
        "delivery_open_on_resolved_queue": delivery_open_on_resolved_queue,
        "acknowledged_without_message_ids": acknowledged_without_message_ids,
        "final_attempt_without_finished_at": final_attempt_without_finished_at,
        "unsealed_queue_runs": unsealed_queue_runs,
        "sealed_run_count_mismatch": sealed_run_count_mismatch,
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
