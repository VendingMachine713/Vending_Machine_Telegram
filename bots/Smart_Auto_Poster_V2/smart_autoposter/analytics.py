from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .db import Database


def analytics_snapshot(db: Database, hours: int = 168) -> dict:
    hours = max(1, int(hours))
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")
    with db.connect() as con:
        campaign = [dict(r) for r in con.execute('''SELECT campaign_id,
            SUM(CASE WHEN status='sent' THEN 1 ELSE 0 END) sent,
            SUM(CASE WHEN status IN ('failed','quarantined') THEN 1 ELSE 0 END) failed,
            SUM(CASE WHEN status='deferred' THEN 1 ELSE 0 END) deferred,
            COUNT(*) total
            FROM queue WHERE updated_at>=? GROUP BY campaign_id ORDER BY sent DESC,total DESC''', (cutoff,)).fetchall()]
        variants = [dict(r) for r in con.execute('''SELECT content_id,COUNT(*) sent FROM queue
            WHERE status='sent' AND updated_at>=? AND content_id IS NOT NULL GROUP BY content_id ORDER BY sent DESC''', (cutoff,)).fetchall()]
        accounts = [dict(r) for r in con.execute('''SELECT COALESCE(account_key,'unassigned') account_key,
            SUM(CASE WHEN status='sent' THEN 1 ELSE 0 END) sent,
            SUM(CASE WHEN status IN ('failed','quarantined') THEN 1 ELSE 0 END) failed,
            SUM(CASE WHEN status='deferred' THEN 1 ELSE 0 END) deferred,
            COUNT(*) total FROM queue WHERE updated_at>=? GROUP BY COALESCE(account_key,'unassigned') ORDER BY sent DESC''', (cutoff,)).fetchall()]
        destinations = [dict(r) for r in con.execute('''SELECT d.group_id,d.group_name,
            SUM(CASE WHEN q.status='sent' THEN 1 ELSE 0 END) sent,
            SUM(CASE WHEN q.status IN ('failed','quarantined') THEN 1 ELSE 0 END) failed,
            SUM(CASE WHEN q.status='deferred' THEN 1 ELSE 0 END) deferred,
            COUNT(q.id) total
            FROM destinations d JOIN queue q ON q.group_id=d.group_id WHERE q.updated_at>=?
            GROUP BY d.group_id,d.group_name ORDER BY failed DESC,total DESC LIMIT 50''', (cutoff,)).fetchall()]
        error_kinds = [dict(r) for r in con.execute('''SELECT COALESCE(error_kind,'unknown') error_kind,COUNT(*) n FROM queue
            WHERE status IN ('failed','quarantined','uncertain') AND updated_at>=? GROUP BY COALESCE(error_kind,'unknown') ORDER BY n DESC''', (cutoff,)).fetchall()]
        hour_utc = [dict(r) for r in con.execute('''SELECT substr(updated_at,12,2) hour_utc,COUNT(*) sent FROM queue
            WHERE status='sent' AND updated_at>=? GROUP BY substr(updated_at,12,2) ORDER BY hour_utc''', (cutoff,)).fetchall()]
        queue_status = {r['status']: int(r['n']) for r in con.execute('SELECT status,COUNT(*) n FROM queue WHERE updated_at>=? GROUP BY status',(cutoff,)).fetchall()}
        lifecycle = {r['lifecycle_state']: int(r['n']) for r in con.execute('SELECT lifecycle_state,COUNT(*) n FROM campaigns GROUP BY lifecycle_state').fetchall()}
        dest_state = dict(con.execute('''SELECT COUNT(*) total,
                SUM(CASE WHEN enabled=1 THEN 1 ELSE 0 END) enabled,
                SUM(CASE WHEN needs_review=1 THEN 1 ELSE 0 END) review,
                SUM(CASE WHEN quarantine_until IS NOT NULL THEN 1 ELSE 0 END) quarantined,
                SUM(CASE WHEN never_auto_post=1 THEN 1 ELSE 0 END) never_auto_post,
                SUM(CASE WHEN protected=1 THEN 1 ELSE 0 END) protected
                FROM destinations''').fetchone())
        account_health = [dict(r) for r in con.execute('SELECT account_key,authorized,identity,health_score,cooldown_until,last_success_at,last_failure_at FROM accounts ORDER BY account_key').fetchall()]
    for rows in (campaign, accounts, destinations):
        for r in rows:
            attempts = int(r.get("sent", 0)) + int(r.get("failed", 0))
            r["success_rate"] = round(int(r.get("sent", 0)) / attempts * 100, 2) if attempts else 100.0
    sent=int(queue_status.get('sent',0)); failed=int(queue_status.get('failed',0))+int(queue_status.get('quarantined',0)); denom=sent+failed
    return {
        "window_hours": hours,
        "cutoff": cutoff,
        "queue_status": queue_status,
        "success_rate": round(sent/denom*100,2) if denom else 100.0,
        "campaign_lifecycle": lifecycle,
        "destination_state": dest_state,
        "account_health": account_health,
        "campaigns": campaign,
        "variants": variants,
        "accounts": accounts,
        "destinations": destinations,
        "error_kinds": error_kinds,
        "sent_by_hour_utc": hour_utc,
    }
