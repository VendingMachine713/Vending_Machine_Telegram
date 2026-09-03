from __future__ import annotations

from .db import Database, utcnow
from .redaction import redact_text


CONFIRM_SENT = "TELEGRAM_HISTORY_CONFIRMED_SENT"
CONFIRM_NOT_SENT = "TELEGRAM_HISTORY_CONFIRMED_NOT_SENT"
OUTCOMES = {"sent", "not_sent", "unresolved"}


def uncertain_jobs(db: Database, *, campaign_id: str | None = None, limit: int = 100) -> list[dict]:
    where = "WHERE q.status='uncertain'"
    params: list[object] = []
    if campaign_id:
        where += " AND q.campaign_id=?"
        params.append(campaign_id)
    params.append(max(1, min(500, int(limit))))
    with db.connect() as con:
        rows = con.execute(
            f"""SELECT q.id,q.run_key,q.campaign_id,q.group_id,d.group_name,q.content_id,
                       q.account_key,q.attempts,q.error_kind,q.last_error,q.updated_at
                FROM queue q JOIN destinations d ON d.group_id=q.group_id
                {where} ORDER BY q.updated_at,q.id LIMIT ?""",
            params,
        ).fetchall()
    return [dict(row) for row in rows]


def reconciliation_history(db: Database, *, queue_id: int | None = None, limit: int = 100) -> list[dict]:
    where = ""
    params: list[object] = []
    if queue_id is not None:
        where = "WHERE r.queue_id=?"
        params.append(int(queue_id))
    params.append(max(1, min(500, int(limit))))
    with db.connect() as con:
        rows = con.execute(
            f"""SELECT r.*,q.campaign_id,q.group_id,q.content_id
                FROM delivery_reconciliations r JOIN queue q ON q.id=r.queue_id
                {where} ORDER BY r.id DESC LIMIT ?""",
            params,
        ).fetchall()
    return [dict(row) for row in rows]


def reconcile_uncertain(
    db: Database,
    queue_id: int,
    outcome: str,
    *,
    evidence: str,
    confirmation: str | None = None,
    actor: str = "local",
) -> dict:
    outcome = str(outcome or "").strip().lower()
    if outcome not in OUTCOMES:
        raise ValueError(f"outcome must be one of: {', '.join(sorted(OUTCOMES))}")
    evidence = redact_text(str(evidence or "").strip())
    if not evidence:
        raise ValueError("reconciliation evidence is required")
    expected = CONFIRM_SENT if outcome == "sent" else (CONFIRM_NOT_SENT if outcome == "not_sent" else None)
    if expected and confirmation != expected:
        raise RuntimeError(f"Outcome '{outcome}' requires --confirmation {expected}")

    now = utcnow()
    with db.connect() as con:
        row = con.execute("SELECT * FROM queue WHERE id=?", (int(queue_id),)).fetchone()
        if not row:
            raise RuntimeError(f"Unknown queue job: {queue_id}")
        previous = str(row["status"])
        if previous != "uncertain":
            latest = con.execute(
                "SELECT * FROM delivery_reconciliations WHERE queue_id=? ORDER BY id DESC LIMIT 1",
                (int(queue_id),),
            ).fetchone()
            expected_status = {"sent": "sent", "not_sent": "retry"}.get(outcome, "uncertain")
            if latest and latest["outcome"] == outcome and previous == expected_status:
                return {"queue_id": int(queue_id), "outcome": outcome, "status": previous, "idempotent": True}
            raise RuntimeError(f"Job #{queue_id} is '{previous}', not uncertain; reconciliation blocked")

        if outcome == "sent":
            resulting = "sent"
            con.execute(
                """UPDATE queue SET status='sent',error_kind='history_reconciled_sent',
                   last_error='Telegram history confirmed delivery',resolved_at=?,phase='sent',phase_percent=100,
                   phase_detail='Telegram history confirmed delivery',phase_updated_at=?,updated_at=? WHERE id=? AND status='uncertain'""",
                (now, now, now, int(queue_id)),
            )
        elif outcome == "not_sent":
            resulting = "retry"
            con.execute(
                """UPDATE queue SET status='retry',due_at=?,error_kind='history_reconciled_not_sent',
                   last_error='Telegram history confirmed not sent; explicit retry released',resolved_at=NULL,pass_no=pass_no+1,
                   phase='retry_wait',phase_percent=35,phase_detail='history confirmed not sent; retry released',phase_updated_at=?,updated_at=?
                   WHERE id=? AND status='uncertain'""",
                (now, now, now, int(queue_id)),
            )
        else:
            resulting = "uncertain"

        cur = con.execute(
            """INSERT INTO delivery_reconciliations
               (created_at,queue_id,previous_status,outcome,actor,evidence,confirmation_token,resulting_status)
               VALUES(?,?,?,?,?,?,?,?)""",
            (now, int(queue_id), previous, outcome, actor, evidence, expected, resulting),
        )
        reconciliation_id = int(cur.lastrowid)
        con.execute(
            """INSERT INTO audit_log(created_at,actor,action,target_type,target_id,details)
               VALUES(?,?,?,?,?,?)""",
            (now, actor, f"uncertain_reconcile_{outcome}", "queue_job", str(queue_id), evidence),
        )
        con.execute(
            """INSERT INTO events(created_at,severity,event_type,group_id,campaign_id,message,details)
               VALUES(?,?,?,?,?,?,?)""",
            (now, "WARNING" if outcome == "unresolved" else "INFO", "uncertain_reconciliation",
             row["group_id"], row["campaign_id"], f"Uncertain job #{queue_id} reconciled as {outcome}", evidence),
        )
    return {
        "reconciliation_id": reconciliation_id,
        "queue_id": int(queue_id),
        "outcome": outcome,
        "previous_status": previous,
        "status": resulting,
        "idempotent": False,
        "automatic_retry": False,
    }
