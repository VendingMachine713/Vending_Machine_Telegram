from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from smart_autoposter.settings import Settings
from smart_autoposter.status_view import ATTENTION_STATUSES, render_job, render_snapshot, summarise_queue


def _connect_read_only(path: Path) -> sqlite3.Connection:
    resolved = path.resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"Smart Auto Poster database not found: {resolved}")
    con = sqlite3.connect(f"file:{resolved.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _latest_rows(con: sqlite3.Connection, limit: int) -> tuple[str, list[dict]]:
    latest = con.execute(
        "SELECT run_key FROM queue WHERE run_key IS NOT NULL AND TRIM(run_key) <> '' ORDER BY id DESC LIMIT 1"
    ).fetchone()

    if latest:
        run_key = str(latest["run_key"])
        rows = con.execute(
            """SELECT q.id,q.run_key,q.status,q.due_at,q.attempts,q.account_key,q.campaign_id,
                      q.content_id,q.group_id,q.last_error,d.group_name
               FROM queue q
               JOIN destinations d ON d.group_id=q.group_id
               WHERE q.run_key=?
               ORDER BY q.id ASC""",
            (run_key,),
        ).fetchall()
        return run_key, [dict(row) for row in rows]

    rows = con.execute(
        """SELECT q.id,q.run_key,q.status,q.due_at,q.attempts,q.account_key,q.campaign_id,
                  q.content_id,q.group_id,q.last_error,d.group_name
           FROM queue q
           JOIN destinations d ON d.group_id=q.group_id
           ORDER BY q.id DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    return "latest jobs (no run key)", [dict(row) for row in reversed(rows)]


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Smart Auto Poster delivery progress view")
    parser.add_argument("--details", action="store_true", help="Show every destination in the current run")
    parser.add_argument("--limit", type=int, default=100, help="Fallback job count when no run key exists")
    args = parser.parse_args()

    settings = Settings.load(False)
    with _connect_read_only(settings.database_path) as con:
        run_key, rows = _latest_rows(con, max(1, args.limit))

    snapshot = summarise_queue(rows)
    print(f"Run: {run_key}")
    print(render_snapshot(snapshot))

    attention = [row for row in rows if str(row.get("status") or "").lower() in ATTENTION_STATUSES]
    if attention:
        print("\nNEEDS ATTENTION")
        print("-" * 60)
        for row in attention:
            print(render_job(row))
            print()

    if args.details:
        print("\nDESTINATION DETAILS")
        print("-" * 60)
        for row in rows:
            print(render_job(row))
            print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
