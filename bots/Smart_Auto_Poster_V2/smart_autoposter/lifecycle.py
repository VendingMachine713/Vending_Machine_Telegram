from __future__ import annotations

from datetime import datetime, timezone

from .db import Database


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError):
        return None


def queue_stage_history(db: Database, queue_id: int, *, limit: int = 50) -> list[dict]:
    """Return durable status transitions for one queue job, oldest first.

    The history is populated by database triggers, so every code path that changes
    queue.status is covered automatically (worker, admin, reconciliation, CLI, or
    future automation) without duplicating mutation logic in each caller.
    """
    limit = max(1, min(500, int(limit)))
    with db.connect() as con:
        rows = con.execute(
            '''SELECT id,created_at,queue_id,run_key,campaign_id,group_id,status,account_key,
                      attempts,due_at,error_kind,message
               FROM queue_stage_history WHERE queue_id=? ORDER BY id DESC LIMIT ?''',
            (int(queue_id), limit),
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


def queue_phase_history(db: Database, queue_id: int, *, limit: int = 100) -> list[dict]:
    """Return the durable V4 per-step pipeline timeline for one post."""
    limit = max(1, min(1000, int(limit)))
    with db.connect() as con:
        rows = con.execute(
            '''SELECT id,created_at,queue_id,run_key,campaign_id,group_id,pass_no,status,phase,
                      phase_percent,account_key,progress_current,progress_total,progress_unit,detail
               FROM queue_phase_history WHERE queue_id=? ORDER BY id DESC LIMIT ?''',
            (int(queue_id), limit),
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


def latest_stage_details(db: Database, queue_ids: list[int]) -> dict[int, dict]:
    if not queue_ids:
        return {}
    unique = sorted({int(x) for x in queue_ids})
    placeholders = ','.join('?' for _ in unique)
    with db.connect() as con:
        rows = con.execute(
            f'''SELECT h.* FROM queue_stage_history h
                JOIN (
                    SELECT queue_id,MAX(id) max_id FROM queue_stage_history
                    WHERE queue_id IN ({placeholders}) GROUP BY queue_id
                ) latest ON latest.max_id=h.id''',
            unique,
        ).fetchall()
    now = datetime.now(timezone.utc)
    out: dict[int, dict] = {}
    for raw in rows:
        row = dict(raw)
        dt = _parse_iso(row.get('created_at'))
        row['stage_age_seconds'] = max(0, int((now - dt).total_seconds())) if dt else None
        out[int(row['queue_id'])] = row
    return out


def transition_summary(db: Database, *, run_key: str | None = None, campaign_id: str | None = None) -> dict:
    where = []
    params: list[object] = []
    if run_key:
        where.append('run_key=?'); params.append(run_key)
    if campaign_id:
        where.append('campaign_id=?'); params.append(campaign_id)
    sql = 'SELECT status,COUNT(*) n FROM queue_stage_history'
    if where:
        sql += ' WHERE ' + ' AND '.join(where)
    sql += ' GROUP BY status ORDER BY status'
    with db.connect() as con:
        rows = con.execute(sql, params).fetchall()
    return {r['status']: int(r['n']) for r in rows}
