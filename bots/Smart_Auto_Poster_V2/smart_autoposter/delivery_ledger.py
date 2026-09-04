from __future__ import annotations

import json
from datetime import datetime
from typing import Iterable

from .db import Database, utcnow
from .redaction import redact_text

OPEN_OUTCOMES = {"started", "acknowledged"}
FINAL_OUTCOMES = {"sent", "failed", "uncertain"}
ALL_OUTCOMES = OPEN_OUTCOMES | FINAL_OUTCOMES


def _columns(con, table: str) -> set[str]:
    return {
        str(r["name"])
        for r in con.execute(f"PRAGMA table_info({table})").fetchall()
    }


def _legacy_attempt_schema(columns: set[str]) -> bool:
    return {"queue_id", "attempt_number", "created_at"}.issubset(columns)


def _modern_attempt_schema(columns: set[str]) -> bool:
    return {"queue_job_id", "attempt_no", "started_at"}.issubset(columns)


def _ensure_run_seals(con) -> None:
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS queue_run_seals (
            campaign_id TEXT NOT NULL
                REFERENCES campaigns(campaign_id) ON DELETE CASCADE,
            run_key TEXT NOT NULL,
            sealed_at TEXT NOT NULL,
            job_count INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(campaign_id, run_key)
        );

        CREATE INDEX IF NOT EXISTS idx_queue_run_seals_time
            ON queue_run_seals(sealed_at);

        INSERT OR IGNORE INTO
            queue_run_seals(campaign_id,run_key,sealed_at,job_count)
        SELECT campaign_id,run_key,MAX(created_at),COUNT(*)
        FROM queue
        WHERE run_key IS NOT NULL
          AND run_key<>''
        GROUP BY campaign_id,run_key;

        CREATE TRIGGER IF NOT EXISTS trg_queue_block_sealed_run
        BEFORE INSERT ON queue
        WHEN NEW.run_key IS NOT NULL
         AND NEW.run_key<>''
         AND EXISTS(
             SELECT 1
             FROM queue_run_seals rs
             WHERE rs.campaign_id=NEW.campaign_id
               AND rs.run_key=NEW.run_key
         )
        BEGIN
            SELECT RAISE(ABORT, 'UNIQUE sealed campaign run');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_campaign_seal_completed_run
        AFTER UPDATE OF completed_cycles ON campaigns
        WHEN NEW.completed_cycles > OLD.completed_cycles
        BEGIN
            INSERT OR IGNORE INTO
                queue_run_seals(campaign_id,run_key,sealed_at,job_count)
            SELECT NEW.campaign_id,q.run_key,MAX(q.created_at),COUNT(*)
            FROM queue q
            WHERE q.campaign_id=NEW.campaign_id
              AND q.run_key IS NOT NULL
              AND q.run_key<>''
            GROUP BY q.run_key;
        END;
        """
    )


def ensure_delivery_ledger(db: Database) -> None:
    """
    Preserve either historical Smart Auto Poster delivery_attempts schema.

    Existing production databases use queue_id / attempt_number.
    Newer source uses queue_job_id / attempt_no.

    Never destructively migrate a live attempt journal here.
    """
    with db.connect() as con:
        cols = _columns(con, "delivery_attempts")

        if not cols:
            con.executescript(
                """
                CREATE TABLE delivery_attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    queue_job_id INTEGER NOT NULL
                        REFERENCES queue(id) ON DELETE CASCADE,
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

        elif _legacy_attempt_schema(cols):
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_delivery_attempts_queue
                ON delivery_attempts(queue_id,created_at)
                """
            )

        elif _modern_attempt_schema(cols):
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_delivery_attempts_job
                ON delivery_attempts(queue_job_id,attempt_no)
                """
            )
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_delivery_attempts_outcome
                ON delivery_attempts(outcome,started_at)
                """
            )

        else:
            raise RuntimeError(
                "Unsupported delivery_attempts schema; refusing automatic migration"
            )

        _ensure_run_seals(con)


def start_attempt(
    db: Database,
    queue_job_id: int,
    account_key: str | None,
) -> dict:

    ensure_delivery_ledger(db)
    now = utcnow()

    with db.connect() as con:
        con.execute("BEGIN IMMEDIATE")

        job = con.execute(
            """
            SELECT id,run_key,campaign_id,group_id,status
            FROM queue
            WHERE id=?
            """,
            (int(queue_job_id),),
        ).fetchone()

        if not job:
            raise RuntimeError(f"Unknown queue job: {queue_job_id}")

        if job["status"] != "sending":
            raise RuntimeError(
                f"Queue job {queue_job_id} is {job['status']}; "
                "delivery attempt requires sending state"
            )

        cols = _columns(con, "delivery_attempts")

        if _legacy_attempt_schema(cols):
            attempt_no = int(
                con.execute(
                    """
                    SELECT COALESCE(MAX(attempt_number),0)+1
                    FROM delivery_attempts
                    WHERE queue_id=?
                    """,
                    (int(queue_job_id),),
                ).fetchone()[0]
            )

            cur = con.execute(
                """
                INSERT INTO delivery_attempts(
                    created_at,
                    queue_id,
                    run_key,
                    campaign_id,
                    group_id,
                    account_key,
                    attempt_number,
                    outcome
                )
                VALUES(?,?,?,?,?,?,?,'started')
                """,
                (
                    now,
                    int(queue_job_id),
                    job["run_key"],
                    job["campaign_id"],
                    int(job["group_id"]),
                    account_key,
                    attempt_no,
                ),
            )

        else:
            attempt_no = int(
                con.execute(
                    """
                    SELECT COALESCE(MAX(attempt_no),0)+1
                    FROM delivery_attempts
                    WHERE queue_job_id=?
                    """,
                    (int(queue_job_id),),
                ).fetchone()[0]
            )

            cur = con.execute(
                """
                INSERT INTO delivery_attempts(
                    queue_job_id,
                    attempt_no,
                    account_key,
                    started_at,
                    outcome
                )
                VALUES(?,?,?,?,'started')
                """,
                (
                    int(queue_job_id),
                    attempt_no,
                    account_key,
                    now,
                ),
            )

        return {
            "id": int(cur.lastrowid),
            "attempt_no": attempt_no,
            "started_at": now,
        }


def mark_acknowledged(
    db: Database,
    attempt_id: int,
    message_ids,
) -> None:

    ensure_delivery_ledger(db)

    now = utcnow()
    encoded = json.dumps(message_ids)

    with db.connect() as con:
        cols = _columns(con, "delivery_attempts")

        if _legacy_attempt_schema(cols):
            cur = con.execute(
                """
                UPDATE delivery_attempts
                SET outcome='acknowledged',
                    telegram_message_ids=?,
                    details=COALESCE(
                        details,
                        'Telegram acknowledged delivery'
                    )
                WHERE id=?
                  AND outcome='started'
                """,
                (
                    encoded,
                    int(attempt_id),
                ),
            )

        else:
            cur = con.execute(
                """
                UPDATE delivery_attempts
                SET outcome='acknowledged',
                    acknowledged_at=?,
                    telegram_message_ids=?
                WHERE id=?
                  AND outcome='started'
                """,
                (
                    now,
                    encoded,
                    int(attempt_id),
                ),
            )

        if cur.rowcount != 1:
            row = con.execute(
                """
                SELECT outcome
                FROM delivery_attempts
                WHERE id=?
                """,
                (int(attempt_id),),
            ).fetchone()

            state = row["outcome"] if row else "missing"

            raise RuntimeError(
                f"Delivery attempt {attempt_id} "
                f"cannot be acknowledged from state {state}"
            )


def _duration_ms(
    started_at: str | None,
    finished_at: str,
) -> int | None:

    if not started_at:
        return None

    try:
        start = datetime.fromisoformat(
            started_at.replace("Z", "+00:00")
        )
        end = datetime.fromisoformat(
            finished_at.replace("Z", "+00:00")
        )

        return max(
            0,
            int((end - start).total_seconds() * 1000),
        )

    except Exception:
        return None


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
        raise ValueError(
            f"Invalid final delivery outcome: {outcome}"
        )

    ensure_delivery_ledger(db)

    now = utcnow()
    encoded = (
        json.dumps(message_ids)
        if message_ids is not None
        else None
    )

    safe_error = (
        (redact_text(error_text) or "")[:1000]
        or None
    )

    with db.connect() as con:
        cols = _columns(con, "delivery_attempts")

        if _legacy_attempt_schema(cols):

            row = con.execute(
                """
                SELECT outcome,created_at
                FROM delivery_attempts
                WHERE id=?
                """,
                (int(attempt_id),),
            ).fetchone()

            if row and row["outcome"] == outcome:
                return

            duration = _duration_ms(
                row["created_at"] if row else None,
                now,
            )

            cur = con.execute(
                """
                UPDATE delivery_attempts
                SET outcome=?,
                    error_kind=?,
                    details=?,
                    telegram_message_ids=
                        COALESCE(?,telegram_message_ids),
                    duration_ms=
                        COALESCE(?,duration_ms)
                WHERE id=?
                  AND outcome IN (
                      'started',
                      'acknowledged'
                  )
                """,
                (
                    outcome,
                    error_kind,
                    safe_error,
                    encoded,
                    duration,
                    int(attempt_id),
                ),
            )

        else:
            cur = con.execute(
                """
                UPDATE delivery_attempts
                SET outcome=?,
                    finished_at=?,
                    error_kind=?,
                    error_text=?,
                    telegram_message_ids=
                        COALESCE(?,telegram_message_ids)
                WHERE id=?
                  AND outcome IN (
                      'started',
                      'acknowledged'
                  )
                """,
                (
                    outcome,
                    now,
                    error_kind,
                    safe_error,
                    encoded,
                    int(attempt_id),
                ),
            )

        if cur.rowcount != 1:
            row = con.execute(
                """
                SELECT outcome
                FROM delivery_attempts
                WHERE id=?
                """,
                (int(attempt_id),),
            ).fetchone()

            if row and row["outcome"] == outcome:
                return

            state = row["outcome"] if row else "missing"

            raise RuntimeError(
                f"Delivery attempt {attempt_id} "
                f"cannot finish as {outcome} "
                f"from state {state}"
            )


def reconcile_open_attempts_from_queue(
    db: Database,
    queue_job_ids: Iterable[int] | None = None,
) -> dict[str, int]:

    ensure_delivery_ledger(db)

    ids = [
        int(x)
        for x in (queue_job_ids or [])
    ]

    now = utcnow()

    counts = {
        "sent": 0,
        "failed": 0,
        "uncertain": 0,
    }

    with db.connect() as con:
        cols = _columns(
            con,
            "delivery_attempts",
        )

        legacy = _legacy_attempt_schema(cols)

        link_col = (
            "queue_id"
            if legacy
            else "queue_job_id"
        )

        where = ""
        params: list[object] = []

        if ids:
            placeholders = ",".join(
                "?"
                for _ in ids
            )

            where = (
                f" AND da.{link_col} "
                f"IN ({placeholders})"
            )

            params.extend(ids)

        rows = con.execute(
            f"""
            SELECT
                da.id,
                q.status,
                q.error_kind,
                q.last_error,
                q.telegram_message_ids
            FROM delivery_attempts da
            JOIN queue q
              ON q.id=da.{link_col}
            WHERE da.outcome
              IN ('started','acknowledged')
              {where}
            """,
            params,
        ).fetchall()

        for row in rows:

            qstatus = row["status"]

            if qstatus == "sent":
                result = "sent"

            elif qstatus in {
                "failed",
                "quarantined",
                "cancelled",
                "expired",
            }:
                result = "failed"

            elif qstatus == "uncertain":
                result = "uncertain"

            else:
                continue

            safe_error = (
                (redact_text(row["last_error"]) or "")[:1000]
                or None
            )

            if legacy:
                con.execute(
                    """
                    UPDATE delivery_attempts
                    SET outcome=?,
                        error_kind=
                            COALESCE(error_kind,?),
                        details=
                            COALESCE(details,?),
                        telegram_message_ids=
                            COALESCE(
                                telegram_message_ids,
                                ?
                            )
                    WHERE id=?
                      AND outcome IN (
                          'started',
                          'acknowledged'
                      )
                    """,
                    (
                        result,
                        row["error_kind"],
                        safe_error,
                        row["telegram_message_ids"],
                        row["id"],
                    ),
                )

            else:
                con.execute(
                    """
                    UPDATE delivery_attempts
                    SET outcome=?,
                        finished_at=?,
                        error_kind=
                            COALESCE(error_kind,?),
                        error_text=
                            COALESCE(error_text,?),
                        telegram_message_ids=
                            COALESCE(
                                telegram_message_ids,
                                ?
                            )
                    WHERE id=?
                      AND outcome IN (
                          'started',
                          'acknowledged'
                      )
                    """,
                    (
                        result,
                        now,
                        row["error_kind"],
                        safe_error,
                        row["telegram_message_ids"],
                        row["id"],
                    ),
                )

            counts[result] += 1

    return counts


def attempts_for_job(
    db: Database,
    queue_job_id: int,
) -> list[dict]:

    ensure_delivery_ledger(db)

    with db.connect() as con:
        cols = _columns(
            con,
            "delivery_attempts",
        )

        if _legacy_attempt_schema(cols):
            rows = con.execute(
                """
                SELECT *
                FROM delivery_attempts
                WHERE queue_id=?
                ORDER BY attempt_number,id
                """,
                (int(queue_job_id),),
            ).fetchall()

        else:
            rows = con.execute(
                """
                SELECT *
                FROM delivery_attempts
                WHERE queue_job_id=?
                ORDER BY attempt_no,id
                """,
                (int(queue_job_id),),
            ).fetchall()

    return [
        dict(r)
        for r in rows
    ]
