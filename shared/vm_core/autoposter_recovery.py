from __future__ import annotations

from pathlib import Path
from typing import Any

from .adapters import _connect_readonly, _resolve_bot_path, _tables
from .paths import project_root


def _poster_db(root: Path) -> tuple[Path, Any]:
    bot_dir = root / "bots" / "Smart_Auto_Poster_V2"
    db_path = _resolve_bot_path(bot_dir, "DATABASE_PATH", bot_dir / "data" / "smart_autoposter.sqlite3")
    return db_path, _connect_readonly(db_path)


def smart_auto_poster_reconciliation_preview(root: Path | None = None, limit: int = 50) -> dict[str, Any]:
    """Classify unresolved Smart Auto Poster delivery evidence without mutating it.

    `CONFIRM_SENT_CANDIDATE` means durable Telegram acknowledgement/message IDs are
    present and the row is suitable for a future, separately-tested local-state
    reconciliation path. It does *not* mark the job sent. `MANUAL_REVIEW` remains
    ambiguous and must never be retried automatically from this preview.
    """
    root = root or project_root()
    db_path, con = _poster_db(root)
    if con is None:
        return {"available": False, "database_path": str(db_path), "items": [], "summary": {}}
    try:
        tables = _tables(con)
        if "queue" not in tables:
            return {"available": False, "database_path": str(db_path), "items": [], "summary": {}}
        qcols = {str(row[1]) for row in con.execute("PRAGMA table_info(queue)").fetchall()}
        msg_expr = "q.telegram_message_ids" if "telegram_message_ids" in qcols else "NULL"
        err_expr = "q.error_kind" if "error_kind" in qcols else "NULL"
        rows = con.execute(
            f"""SELECT q.id,q.status,{msg_expr} AS telegram_message_ids,{err_expr} AS error_kind
                FROM queue q
                WHERE lower(q.status) IN ('uncertain','sending')
                ORDER BY q.id ASC LIMIT ?""",
            (max(1, min(int(limit), 500)),),
        ).fetchall()

        attempt_by_job: dict[int, list[dict[str, Any]]] = {}
        if "delivery_attempts" in tables and rows:
            ids = [int(row["id"]) for row in rows]
            marks = ",".join("?" for _ in ids)
            attempts = con.execute(
                f"""SELECT queue_job_id,outcome,telegram_message_ids,acknowledged_at,finished_at
                    FROM delivery_attempts WHERE queue_job_id IN ({marks})
                    ORDER BY queue_job_id,attempt_no""",
                ids,
            ).fetchall()
            for attempt in attempts:
                attempt_by_job.setdefault(int(attempt["queue_job_id"]), []).append(dict(attempt))

        items: list[dict[str, Any]] = []
        counts = {"CONFIRM_SENT_CANDIDATE": 0, "MANUAL_REVIEW": 0}
        for row in rows:
            job_id = int(row["id"])
            attempts = attempt_by_job.get(job_id, [])
            queue_ids = bool(str(row["telegram_message_ids"] or "").strip())
            acknowledged = any(
                str(a.get("outcome") or "").lower() in {"acknowledged", "sent"}
                or bool(a.get("acknowledged_at"))
                or bool(str(a.get("telegram_message_ids") or "").strip())
                for a in attempts
            )
            post_send = str(row["error_kind"] or "").lower() == "post_send_persistence"
            if str(row["status"] or "").lower() == "uncertain" and (queue_ids or acknowledged) and (post_send or acknowledged):
                classification = "CONFIRM_SENT_CANDIDATE"
                reason = "Durable Telegram acknowledgement/message IDs exist; local-state reconciliation can be evaluated without resending."
            else:
                classification = "MANUAL_REVIEW"
                reason = "Delivery completion is not durably proven; never auto-retry or auto-confirm from this evidence."
            counts[classification] += 1
            items.append({
                "queue_job_id": job_id,
                "status": str(row["status"] or "").lower(),
                "classification": classification,
                "reason": reason,
                "queue_has_message_ids": queue_ids,
                "delivery_attempt_count": len(attempts),
                "telegram_ack_evidence": acknowledged,
                "error_kind": row["error_kind"],
            })
        return {
            "available": True,
            "database_path": str(db_path),
            "items": items,
            "summary": {"total": len(items), **counts},
            "mutations_performed": False,
            "telegram_actions_performed": False,
        }
    except Exception as exc:
        return {
            "available": False,
            "database_path": str(db_path),
            "items": [],
            "summary": {},
            "error": f"{type(exc).__name__}: {exc}",
        }
    finally:
        con.close()


def format_smart_auto_poster_reconciliation_preview(preview: dict[str, Any]) -> str:
    if not preview.get("available"):
        return (
            "SMART AUTO POSTER - RECOVERY PREVIEW\n"
            "Status: UNAVAILABLE\n"
            f"Database: {preview.get('database_path', '-')}\n"
            f"Reason: {preview.get('error') or 'delivery evidence could not be read safely'}"
        )
    summary = preview.get("summary") or {}
    lines = [
        "SMART AUTO POSTER - RECOVERY PREVIEW",
        "Mode: READ ONLY / NO RESEND",
        (
            f"Unresolved: {summary.get('total', 0)} | "
            f"Confirm-sent candidates: {summary.get('CONFIRM_SENT_CANDIDATE', 0)} | "
            f"Manual review: {summary.get('MANUAL_REVIEW', 0)}"
        ),
        "",
    ]
    for item in preview.get("items") or []:
        marker = "EVIDENCE" if item.get("classification") == "CONFIRM_SENT_CANDIDATE" else "REVIEW"
        lines.append(
            f"#{item.get('queue_job_id')} {marker} {item.get('status','unknown').upper()} "
            f"[{item.get('classification')}]"
        )
        lines.append(f"  {item.get('reason','')}")
    lines.extend([
        "",
        "Safety: this view never changes queue state and never sends or retries Telegram messages.",
    ])
    return "\n".join(lines)


def smart_auto_poster_recovery_gate(root: Path | None = None) -> dict[str, Any]:
    """Return read-only evidence describing whether lifecycle restart is safe.

    This gate deliberately does not reconcile, retry, mutate queue state or contact
    Telegram. It only allows lifecycle recovery when no delivery-ambiguity evidence
    is present in Smart Auto Poster's durable database.
    """
    root = root or project_root()
    db_path, con = _poster_db(root)
    if con is None:
        return {
            "safe": False,
            "classification": "BLOCKED",
            "reason": "Smart Auto Poster database is unavailable; delivery state cannot be verified safely.",
            "database_path": str(db_path),
            "metrics": {},
        }

    try:
        tables = _tables(con)
        if "queue" not in tables:
            return {
                "safe": False,
                "classification": "BLOCKED",
                "reason": "Smart Auto Poster queue table is unavailable; lifecycle recovery is blocked.",
                "database_path": str(db_path),
                "metrics": {},
            }

        counts = {
            str(row["status"] or "").lower(): int(row["n"] or 0)
            for row in con.execute(
                "SELECT lower(status) AS status,COUNT(*) AS n FROM queue GROUP BY lower(status)"
            ).fetchall()
        }
        uncertain = counts.get("uncertain", 0)
        sending = counts.get("sending", 0)
        processing = counts.get("processing", 0)
        open_attempts = 0
        acknowledged_open = 0
        if "delivery_attempts" in tables:
            row = con.execute(
                """SELECT
                       SUM(CASE WHEN outcome IN ('started','acknowledged') THEN 1 ELSE 0 END) AS open_n,
                       SUM(CASE WHEN outcome='acknowledged' THEN 1 ELSE 0 END) AS ack_n
                   FROM delivery_attempts"""
            ).fetchone()
            if row:
                open_attempts = int(row["open_n"] or 0)
                acknowledged_open = int(row["ack_n"] or 0)

        metrics = {
            "uncertain_queue": uncertain,
            "sending_queue": sending,
            "processing_queue": processing,
            "open_delivery_attempts": open_attempts,
            "acknowledged_open_attempts": acknowledged_open,
        }

        reasons: list[str] = []
        if uncertain:
            reasons.append(f"{uncertain} UNCERTAIN queue item(s) require reconciliation")
        if sending:
            reasons.append(f"{sending} queue item(s) are still marked sending")
        if acknowledged_open:
            reasons.append(f"{acknowledged_open} Telegram-acknowledged delivery attempt(s) are not finalized")
        elif open_attempts:
            reasons.append(f"{open_attempts} delivery attempt(s) are not finalized")

        if reasons:
            return {
                "safe": False,
                "classification": "BLOCKED",
                "reason": "; ".join(reasons) + ". Automatic lifecycle recovery remains blocked.",
                "database_path": str(db_path),
                "metrics": metrics,
            }

        return {
            "safe": True,
            "classification": "CLEAR",
            "reason": "No delivery ambiguity is present in durable queue or delivery-attempt state.",
            "database_path": str(db_path),
            "metrics": metrics,
        }
    except Exception as exc:
        return {
            "safe": False,
            "classification": "BLOCKED",
            "reason": f"Smart Auto Poster recovery preflight failed safely: {type(exc).__name__}: {exc}",
            "database_path": str(db_path),
            "metrics": {},
        }
    finally:
        con.close()
