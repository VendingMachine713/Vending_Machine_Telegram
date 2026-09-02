from __future__ import annotations

import json
from typing import Iterable

from .db import Database, utcnow

OPEN_OUTCOMES = {"started", "acknowledged"}
FINAL_OUTCOMES = {"sent", "failed", "uncertain"}
ALL_OUTCOMES = OPEN_OUTCOMES | FINAL_OUTCOMES


def ensure_delivery_ledger(db: Database) -> None:
    """Create the additive delivery-attempt journal without changing queue semantics."""
    with db.connect() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS delivery_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                queue_job_id INTEGER NOT NULL REFERENCES queue(id) ON DELETE CASCADE,
                attempt_no INTEGER NOT NULL,
                account_key TEXT,
                started_at TEXT NOT NULL,
                acknowledged_at TEXT,
                finished_at TEXT,
                outcome TEXT NOT NULL DEFAULT 'started',
                telegram_message_ids TEXT,
                error_kind TEXT,
                error_text TEXT,
                UNIQUE(queue_job_id, attempt_no)
            );
            CREATE INDEX IF NOT EXISTS idx_delivery_attempts_job
                ON delivery_attempts(queue_job_id, attempt_no);
            CREATE INDEX IF NOT EXISTS idx_delivery_attempts_outcome
                ON delivery_attempts(outcome, started_at);
            """
        )


def start_attempt(db: Database, queue_job_id: int, account_key: str | None) -> dict:
    """Persist intent to contact Telegram before any outbound send occurs."""
    ensure_delivery_ledger(db)
    now = utcnow()
    with db.connect() as con:
        con.execute("BEGIN IMMEDIATE")
        job = con.execute("SELECT status FROM queue WHERE id=?", (int(queue_job_id),)).fetchone()
        if not job:
            raise RuntimeError(f"Unknown queue job: {queue_job_id}")
        if job["status"] != "sending":
            raise RuntimeError(f"Queue job {queue_job_id} is {job['status']}; delivery attempt requires sending state")
        attempt_no = int(con.execute(
            "SELECT COALESCE(MAX(attempt_no),0)+1 FROM delivery_attempts WHERE queue_job_id=?",
            (int(queue_job_id),),
        ).fetchone()[0])
        cur = con.execute(
            """INSERT INTO delivery_attempts(queue_job_id,attempt_no,account_key,started_at,outcome)
               VALUES(?,?,?,?, 'started')""",
            (int(queue_job_id), attempt_no, account_key, now),
        )
        return {"id": int(cur.lastrowid), "attempt_no": attempt_no, "started_at": now}


def mark_acknowledged(db: Database, attempt_id: int, message_ids) -> None:
    """Persist Telegram acknowledgement immediately after send() returns."""
    ensure_delivery_ledger(db)
    now = utcnow()
    encoded = json.dumps(message_ids)
    with db.connect() as con:
        cur = con.execute(
            """UPDATE delivery_attempts
               SET outcome='acknowledged',acknowledged_at=?,telegram_message_ids=?
               WHERE id=? AND outcome='started'""",
            (now, encoded, int(attempt_id)),
        )
        if cur.rowcount != 1:
            row = con.execute("SELECT outcome FROM delivery_attempts WHERE id=?", (int(attempt_id),)).fetchone()
            state = row["outcome"] if row else "missing"
            raise RuntimeError(f"Delivery attempt {attempt_id} cannot be acknowledged from state {state}")


def finish_attempt(
    db: Database,
    attempt_id: int,
    outcome: str,
    *,
    error_kind: str | None = None,
    error_text: str | None = None,
    message_ids=None,
) -> None:
    outcome = outcome.strip().lower()
    if outcome not in FINAL_OUTCOMES:
        raise ValueError(f"Invalid final delivery outcome: {outcome}")
    ensure_delivery_ledger(db)
    now = utcnow()
    encoded = json.dumps(message_ids) if message_ids is not None else None
    with db.connect() as con:
        cur = con.execute(
            """UPDATE delivery_attempts
               SET outcome=?,finished_at=?,error_kind=?,error_text=?,
                   telegram_message_ids=COALESCE(?,telegram_message_ids)
               WHERE id=? AND outcome IN ('started','acknowledged')""",
            (outcome, now, error_kind, (error_text or "")[:1000] or None, encoded, int(attempt_id)),
        )
        if cur.rowcount != 1:
            row = con.execute("SELECT outcome FROM delivery_attempts WHERE id=?", (int(attempt_id),)).fetchone()
            if row and row["outcome"] == outcome:
                return
            state = row["outcome"] if row else "missing"
            raise RuntimeError(f"Delivery attempt {attempt_id} cannot finish as {outcome} from state {state}")


def reconcile_open_attempts_from_queue(db: Database, queue_job_ids: Iterable[int] | None = None) -> dict[str, int]:
    """Close open journal rows when durable queue state already proves the outcome.

    This never converts an uncertain queue job into a retry. It only mirrors durable
    queue truth into the attempt journal, making restart recovery idempotent.
    """
    ensure_delivery_ledger(db)
    ids = [int(x) for x in (queue_job_ids or [])]
    where = ""
    params: list[object] = []
    if ids:
        placeholders = ",".join("?" for _ in ids)
        where = f" AND da.queue_job_id IN ({placeholders})"
        params.extend(ids)

    now = utcnow()
    counts = {"sent": 0, "failed": 0, "uncertain": 0}
    with db.connect() as con:
        rows = con.execute(
            f"""SELECT da.id,q.status,q.error_kind,q.last_error,q.telegram_message_ids
                FROM delivery_attempts da JOIN queue q ON q.id=da.queue_job_id
                WHERE da.outcome IN ('started','acknowledged'){where}""",
            params,
        ).fetchall()
        for row in rows:
            qstatus = row["status"]
            if qstatus == "sent":
                outcome = "sent"
            elif qstatus in {"failed", "quarantined", "cancelled", "expired"}:
                outcome = "failed"
            elif qstatus == "uncertain":
                outcome = "uncertain"
            else:
                continue
            con.execute(
                """UPDATE delivery_attempts
                   SET outcome=?,finished_at=?,error_kind=COALESCE(error_kind,?),
                       error_text=COALESCE(error_text,?),
                       telegram_message_ids=COALESCE(telegram_message_ids,?)
                   WHERE id=? AND outcome IN ('started','acknowledged')""",
                (outcome, now, row["error_kind"], row["last_error"], row["telegram_message_ids"], row["id"]),
            )
            counts[outcome] += 1
    return counts


def attempts_for_job(db: Database, queue_job_id: int) -> list[dict]:
    ensure_delivery_ledger(db)
    with db.connect() as con:
        rows = con.execute(
            "SELECT * FROM delivery_attempts WHERE queue_job_id=? ORDER BY attempt_no",
            (int(queue_job_id),),
        ).fetchall()
    return [dict(r) for r in rows]
