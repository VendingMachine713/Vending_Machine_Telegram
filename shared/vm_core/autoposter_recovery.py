from __future__ import annotations

from pathlib import Path
from typing import Any

from .adapters import _connect_readonly, _resolve_bot_path, _tables
from .paths import project_root


def smart_auto_poster_recovery_gate(root: Path | None = None) -> dict[str, Any]:
    """Return read-only evidence describing whether lifecycle restart is safe.

    This gate deliberately does not reconcile, retry, mutate queue state or contact
    Telegram. It only allows lifecycle recovery when no delivery-ambiguity evidence
    is present in Smart Auto Poster's durable database.
    """
    root = root or project_root()
    bot_dir = root / "bots" / "Smart_Auto_Poster_V2"
    db_path = _resolve_bot_path(bot_dir, "DATABASE_PATH", bot_dir / "data" / "smart_autoposter.sqlite3")
    con = _connect_readonly(db_path)
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
