from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .db import Database, utcnow

ACTIVE_QUEUE_STATUSES = ("pending", "retry", "sending", "deferred")
FINAL_QUEUE_STATUSES = ("sent", "failed", "cancelled", "expired", "quarantined")
CAMPAIGN_STATES = {"draft", "ready", "active", "paused", "archived"}
CONTENT_STATES = {"ready", "disabled", "archived", "rejected"}


def audit(db: Database, actor: str, action: str, target_type: str | None = None, target_id: str | None = None, **details):
    db.audit(actor, action, target_type=target_type, target_id=target_id,
             details=json.dumps(details, ensure_ascii=False, default=str) if details else None)


def set_campaign_state(db: Database, campaign_id: str, state: str, *, actor: str = "local") -> dict:
    state = state.strip().lower()
    if state not in CAMPAIGN_STATES:
        raise ValueError(f"campaign state must be one of: {', '.join(sorted(CAMPAIGN_STATES))}")
    enabled = 1 if state == "active" else 0
    now = utcnow()
    with db.connect() as con:
        row = con.execute("SELECT campaign_id,lifecycle_state,enabled FROM campaigns WHERE campaign_id=?", (campaign_id,)).fetchone()
        if not row:
            raise RuntimeError(f"Unknown campaign: {campaign_id}")
        if state == "active":
            full = con.execute("SELECT lifecycle_state,last_preview_at FROM campaigns WHERE campaign_id=?", (campaign_id,)).fetchone()
            variants = con.execute("SELECT COUNT(*) FROM campaign_content WHERE campaign_id=? AND enabled=1", (campaign_id,)).fetchone()[0]
            if not variants:
                raise RuntimeError("Campaign has no enabled content variants")
            if full and full["lifecycle_state"] in {"draft", "ready"} and not full["last_preview_at"]:
                raise RuntimeError("Preview the campaign before activation")
        con.execute("UPDATE campaigns SET lifecycle_state=?,enabled=?,updated_at=? WHERE campaign_id=?",
                    (state, enabled, now, campaign_id))
        if state == "archived":
            con.execute("UPDATE campaign_schedules SET enabled=0,updated_at=? WHERE campaign_id=?", (now, campaign_id))
    audit(db, actor, "campaign_state", "campaign", campaign_id, previous=row["lifecycle_state"], state=state)
    return {"campaign_id": campaign_id, "state": state, "enabled": bool(enabled)}


def mark_campaign_previewed(db: Database, campaign_id: str, *, actor: str = "local"):
    now = utcnow()
    with db.connect() as con:
        if not con.execute("SELECT 1 FROM campaigns WHERE campaign_id=?", (campaign_id,)).fetchone():
            raise RuntimeError(f"Unknown campaign: {campaign_id}")
        con.execute("UPDATE campaigns SET last_preview_at=?,lifecycle_state=CASE WHEN lifecycle_state='draft' THEN 'ready' ELSE lifecycle_state END,updated_at=? WHERE campaign_id=?", (now, now, campaign_id))
    audit(db, actor, "campaign_preview", "campaign", campaign_id)
    return now


def set_content_state(db: Database, content_id: str, state: str, *, actor: str = "local"):
    state = state.strip().lower()
    if state not in CONTENT_STATES:
        raise ValueError(f"content state must be one of: {', '.join(sorted(CONTENT_STATES))}")
    enabled = int(state == "ready")
    with db.connect() as con:
        row = con.execute("SELECT content_id,lifecycle_state FROM content WHERE content_id=?", (content_id,)).fetchone()
        if not row:
            raise RuntimeError(f"Unknown content: {content_id}")
        if state in {"disabled", "archived", "rejected"}:
            active_campaigns = con.execute('''SELECT DISTINCT c.campaign_id FROM campaigns c
                                              JOIN campaign_content cc ON cc.campaign_id=c.campaign_id
                                              WHERE cc.content_id=? AND cc.enabled=1 AND c.enabled=1''', (content_id,)).fetchall()
            if active_campaigns:
                raise RuntimeError("Content is used by active campaign(s): " + ", ".join(r[0] for r in active_campaigns))
        con.execute("UPDATE content SET lifecycle_state=?,enabled=?,updated_at=? WHERE content_id=?",
                    (state, enabled, utcnow(), content_id))
    audit(db, actor, "content_state", "content", content_id, previous=row["lifecycle_state"], state=state)


def set_content_tags(db: Database, content_id: str, *, add: list[str] | None = None, remove: list[str] | None = None, actor: str = "local"):
    add = [x.strip().lower() for x in (add or []) if x.strip()]
    remove = [x.strip().lower() for x in (remove or []) if x.strip()]
    with db.connect() as con:
        if not con.execute("SELECT 1 FROM content WHERE content_id=?", (content_id,)).fetchone():
            raise RuntimeError(f"Unknown content: {content_id}")
        for tag in add:
            con.execute("INSERT OR IGNORE INTO content_tags(content_id,tag) VALUES(?,?)", (content_id, tag))
        for tag in remove:
            con.execute("DELETE FROM content_tags WHERE content_id=? AND tag=?", (content_id, tag))
        rows = con.execute("SELECT tag FROM content_tags WHERE content_id=? ORDER BY tag", (content_id,)).fetchall()
    audit(db, actor, "content_tags", "content", content_id, added=add, removed=remove)
    return [r[0] for r in rows]


def queue_counts(db: Database) -> dict[str, int]:
    with db.connect() as con:
        rows = con.execute("SELECT status,COUNT(*) n FROM queue GROUP BY status").fetchall()
    return {r["status"]: int(r["n"]) for r in rows}


def queue_capacity(db: Database) -> dict[str, int]:
    with db.connect() as con:
        total = con.execute("SELECT COUNT(*) FROM queue WHERE status IN ('pending','retry','sending','deferred')").fetchone()[0]
        max_campaign = con.execute('''SELECT COALESCE(MAX(n),0) FROM (
                                      SELECT COUNT(*) n FROM queue WHERE status IN ('pending','retry','sending','deferred') GROUP BY campaign_id)''').fetchone()[0]
        max_destination = con.execute('''SELECT COALESCE(MAX(n),0) FROM (
                                         SELECT COUNT(*) n FROM queue WHERE status IN ('pending','retry','sending','deferred') GROUP BY group_id)''').fetchone()[0]
    return {"active_total": int(total), "max_campaign": int(max_campaign), "max_destination": int(max_destination)}


def enforce_queue_limits(db: Database, *, add_count: int, campaign_id: str, group_ids: list[int],
                         max_queue_size: int, max_pending_per_campaign: int, max_pending_per_destination: int):
    with db.connect() as con:
        total = con.execute("SELECT COUNT(*) FROM queue WHERE status IN ('pending','retry','sending','deferred')").fetchone()[0]
        camp = con.execute("SELECT COUNT(*) FROM queue WHERE campaign_id=? AND status IN ('pending','retry','sending','deferred')", (campaign_id,)).fetchone()[0]
        if total + add_count > max_queue_size:
            raise RuntimeError(f"Queue capacity protection: {total}+{add_count} would exceed MAX_QUEUE_SIZE={max_queue_size}")
        if camp + add_count > max_pending_per_campaign:
            raise RuntimeError(f"Campaign queue protection: {camp}+{add_count} would exceed MAX_PENDING_PER_CAMPAIGN={max_pending_per_campaign}")
        if group_ids:
            placeholders = ",".join("?" for _ in group_ids)
            rows = con.execute(f'''SELECT group_id,COUNT(*) n FROM queue WHERE group_id IN ({placeholders})
                                  AND status IN ('pending','retry','sending','deferred') GROUP BY group_id''', group_ids).fetchall()
            counts = {int(r["group_id"]): int(r["n"]) for r in rows}
            bad = [gid for gid in group_ids if counts.get(gid, 0) + 1 > max_pending_per_destination]
            if bad:
                raise RuntimeError(f"Destination queue protection: {len(bad)} destination(s) exceed MAX_PENDING_PER_DESTINATION={max_pending_per_destination}")


def manage_job(db: Database, job_id: int, action: str, *, actor: str = "local", minutes: int | None = None) -> dict:
    action = action.lower()
    now = utcnow()
    with db.connect() as con:
        row = con.execute("SELECT * FROM queue WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise RuntimeError(f"Unknown queue job: {job_id}")
        if action == "cancel":
            if row["status"] == "sent":
                raise RuntimeError("Cannot cancel a sent job")
            con.execute("UPDATE queue SET status='cancelled',resolved_at=?,updated_at=? WHERE id=?", (now, now, job_id))
        elif action == "retry":
            if row["status"] not in {"failed", "uncertain", "cancelled", "quarantined", "deferred"}:
                raise RuntimeError(f"Job status {row['status']} is not eligible for retry")
            con.execute("UPDATE queue SET status='retry',due_at=?,last_error='manual retry requested',error_kind=NULL,resolved_at=NULL,updated_at=? WHERE id=?",
                        (now, now, job_id))
        elif action == "defer":
            if row["status"] == "sent":
                raise RuntimeError("Cannot defer a sent job")
            if not minutes or minutes < 1:
                raise ValueError("defer minutes must be >=1")
            due = (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat(timespec="seconds")
            con.execute("UPDATE queue SET status='deferred',due_at=?,last_error='manually deferred',error_kind='manual_defer',updated_at=? WHERE id=?",
                        (due, now, job_id))
        elif action == "mark-sent":
            if row["status"] not in {"uncertain", "failed"}:
                raise RuntimeError("mark-sent is only for uncertain/failed jobs")
            con.execute("UPDATE queue SET status='sent',last_error='manually resolved as sent',resolved_at=?,updated_at=? WHERE id=?", (now, now, job_id))
        else:
            raise ValueError("Unknown job action")
    audit(db, actor, f"job_{action}", "queue_job", str(job_id), previous_status=row["status"], minutes=minutes)
    with db.connect() as con:
        return dict(con.execute("SELECT * FROM queue WHERE id=?", (job_id,)).fetchone())


def bulk_cancel_campaign(db: Database, campaign_id: str, *, actor: str = "local") -> int:
    now = utcnow()
    with db.connect() as con:
        cur = con.execute("UPDATE queue SET status='cancelled',resolved_at=?,updated_at=? WHERE campaign_id=? AND status IN ('pending','retry','deferred')",
                          (now, now, campaign_id))
        n = cur.rowcount
    audit(db, actor, "campaign_queue_cancel", "campaign", campaign_id, jobs=n)
    return n


def bulk_destination_action(db: Database, *, tag: str, enable: bool | None = None, protect: bool | None = None,
                            never_auto_post: bool | None = None, add_tag: str | None = None, remove_tag: str | None = None,
                            actor: str = "local") -> int:
    tag = tag.strip().lower()
    with db.connect() as con:
        ids = [int(r[0]) for r in con.execute("SELECT group_id FROM destination_tags WHERE tag=?", (tag,)).fetchall()]
        if not ids:
            return 0
        for gid in ids:
            sets, vals = [], []
            if enable is not None:
                row = con.execute("SELECT needs_review,mode FROM destinations WHERE group_id=?", (gid,)).fetchone()
                if enable and (row["needs_review"] or row["mode"] not in {"photo", "text"}):
                    continue
                sets.append("enabled=?"); vals.append(int(enable))
            if protect is not None:
                sets.append("protected=?"); vals.append(int(protect))
            if never_auto_post is not None:
                sets.append("never_auto_post=?"); vals.append(int(never_auto_post))
                if never_auto_post:
                    # Hard exclusions fail closed immediately; clearing the flag later
                    # does not silently re-enable the destination.
                    sets.append("enabled=0")
            if sets:
                sets.append("updated_at=?"); vals.append(utcnow()); vals.append(gid)
                con.execute(f"UPDATE destinations SET {','.join(sets)} WHERE group_id=?", vals)
            if add_tag:
                con.execute("INSERT OR IGNORE INTO destination_tags(group_id,tag) VALUES(?,?)", (gid, add_tag.strip().lower()))
            if remove_tag:
                con.execute("DELETE FROM destination_tags WHERE group_id=? AND tag=?", (gid, remove_tag.strip().lower()))
    audit(db, actor, "destination_bulk", "destination_tag", tag, count=len(ids), enable=enable, protect=protect,
          never_auto_post=never_auto_post, add_tag=add_tag, remove_tag=remove_tag)
    return len(ids)


def operational_summary(db: Database, hours: int = 24) -> dict:
    hours = max(1, int(hours))
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")
    with db.connect() as con:
        by_status = {r["status"]: int(r["n"]) for r in con.execute(
            "SELECT status,COUNT(*) n FROM queue WHERE updated_at>=? GROUP BY status", (cutoff,)).fetchall()}
        account_rows = con.execute("SELECT account_key,authorized,identity,cooldown_until,last_success_at,last_failure_at,health_score FROM accounts ORDER BY account_key").fetchall()
        campaign_rows = con.execute("SELECT lifecycle_state,COUNT(*) n FROM campaigns GROUP BY lifecycle_state").fetchall()
        destination_rows = con.execute('''SELECT
            SUM(CASE WHEN enabled=1 THEN 1 ELSE 0 END) enabled,
            SUM(CASE WHEN needs_review=1 THEN 1 ELSE 0 END) review,
            SUM(CASE WHEN quarantine_until>? THEN 1 ELSE 0 END) quarantined,
            COUNT(*) total FROM destinations''', (utcnow(),)).fetchone()
        errors = con.execute('''SELECT COALESCE(error_kind,'unknown') kind,COUNT(*) n FROM queue
                                WHERE status='failed' AND updated_at>=? GROUP BY COALESCE(error_kind,'unknown') ORDER BY n DESC LIMIT 8''', (cutoff,)).fetchall()
        active_queue = con.execute("SELECT COUNT(*) FROM queue WHERE status IN ('pending','retry','sending','deferred')").fetchone()[0]
    sent = by_status.get("sent", 0)
    failed = by_status.get("failed", 0)
    attempts = sent + failed
    return {
        "window_hours": hours,
        "queue_status": by_status,
        "success_rate": round(sent / attempts * 100, 2) if attempts else 100.0,
        "active_queue": int(active_queue),
        "accounts": [dict(r) for r in account_rows],
        "campaigns": {r["lifecycle_state"]: int(r["n"]) for r in campaign_rows},
        "destinations": {k: int(destination_rows[k] or 0) for k in destination_rows.keys()},
        "top_errors": [dict(r) for r in errors],
    }


def recent_audit(db: Database, limit: int = 50) -> list[dict]:
    with db.connect() as con:
        rows = con.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (max(1, min(limit, 500)),)).fetchall()
    return [dict(r) for r in rows]


def expire_old_jobs(db: Database, *, days: int) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max(1, days))).isoformat(timespec="seconds")
    now = utcnow()
    with db.connect() as con:
        cur = con.execute('''UPDATE queue SET status='expired',resolved_at=?,updated_at=?
                             WHERE status IN ('pending','retry','deferred') AND created_at<?''', (now, now, cutoff))
        return cur.rowcount


def set_campaign_gap(db: Database, campaign_id: str, related_campaign_id: str, minutes: float, *, both: bool = False, actor: str = "local"):
    if campaign_id == related_campaign_id:
        raise ValueError("A campaign cannot have a gap relation to itself")
    seconds = int(float(minutes) * 60)
    if seconds < 0:
        raise ValueError("gap cannot be negative")
    now = utcnow()
    with db.connect() as con:
        for cid in (campaign_id, related_campaign_id):
            if not con.execute("SELECT 1 FROM campaigns WHERE campaign_id=?", (cid,)).fetchone():
                raise RuntimeError(f"Unknown campaign: {cid}")
        con.execute('''INSERT INTO campaign_relations(campaign_id,related_campaign_id,relation_type,min_gap_seconds,created_at)
                       VALUES(?,?,'min_gap',?,?) ON CONFLICT(campaign_id,related_campaign_id,relation_type)
                       DO UPDATE SET min_gap_seconds=excluded.min_gap_seconds''', (campaign_id, related_campaign_id, seconds, now))
        if both:
            con.execute('''INSERT INTO campaign_relations(campaign_id,related_campaign_id,relation_type,min_gap_seconds,created_at)
                           VALUES(?,?,'min_gap',?,?) ON CONFLICT(campaign_id,related_campaign_id,relation_type)
                           DO UPDATE SET min_gap_seconds=excluded.min_gap_seconds''', (related_campaign_id, campaign_id, seconds, now))
    audit(db, actor, "campaign_gap", "campaign", campaign_id, related=related_campaign_id, minutes=minutes, both=both)


def remove_campaign_gap(db: Database, campaign_id: str, related_campaign_id: str, *, both: bool = False, actor: str = "local"):
    with db.connect() as con:
        con.execute("DELETE FROM campaign_relations WHERE campaign_id=? AND related_campaign_id=? AND relation_type='min_gap'", (campaign_id, related_campaign_id))
        if both:
            con.execute("DELETE FROM campaign_relations WHERE campaign_id=? AND related_campaign_id=? AND relation_type='min_gap'", (related_campaign_id, campaign_id))
    audit(db, actor, "campaign_gap_remove", "campaign", campaign_id, related=related_campaign_id, both=both)



def expire_ineligible_jobs(db: Database, *, now: str | None = None) -> int:
    """Expire queued work that can no longer become eligible.

    Paused campaigns are intentionally not expired: their queue remains intact so
    a later resume can continue. Archived campaigns and campaigns whose end_at has
    passed are terminal and their unsent jobs are marked expired.
    """
    now = now or utcnow()
    with db.connect() as con:
        cur = con.execute(
            '''UPDATE queue
               SET status='expired',error_kind='campaign_ineligible',
                   last_error='campaign archived or end date passed',resolved_at=?,updated_at=?
               WHERE status IN ('pending','retry','deferred')
                 AND campaign_id IN (
                    SELECT campaign_id FROM campaigns
                    WHERE lifecycle_state='archived' OR (end_at IS NOT NULL AND end_at<?)
                 )''',
            (now, now, now),
        )
        return cur.rowcount


def record_update_history(db: Database, version: str, *, previous_version: str | None = None,
                          status: str = 'applied', package_name: str | None = None,
                          details: str | None = None) -> int:
    now = utcnow()
    with db.connect() as con:
        cur = con.execute(
            '''INSERT INTO update_history(created_at,version,previous_version,status,package_name,details)
               VALUES(?,?,?,?,?,?)''',
            (now, version, previous_version, status, package_name, details),
        )
        return int(cur.lastrowid)


def recent_update_history(db: Database, limit: int = 50) -> list[dict]:
    with db.connect() as con:
        rows = con.execute(
            'SELECT * FROM update_history ORDER BY id DESC LIMIT ?',
            (max(1, min(int(limit), 500)),),
        ).fetchall()
    return [dict(r) for r in rows]


def finalize_cycle_limited_campaigns(db: Database, *, actor: str = "system") -> int:
    """Archive cycle-limited campaigns only after their active queue has drained."""
    changed = 0
    now = utcnow()
    with db.connect() as con:
        rows = con.execute("""SELECT campaign_id,max_cycles,completed_cycles FROM campaigns
                              WHERE lifecycle_state='active' AND enabled=1 AND max_cycles>0 AND completed_cycles>=max_cycles""").fetchall()
        for r in rows:
            active = con.execute("SELECT COUNT(*) FROM queue WHERE campaign_id=? AND status IN ('pending','retry','sending','deferred')", (r['campaign_id'],)).fetchone()[0]
            if active:
                continue
            con.execute("UPDATE campaigns SET lifecycle_state='archived',enabled=0,updated_at=? WHERE campaign_id=?", (now, r['campaign_id']))
            con.execute("UPDATE campaign_schedules SET enabled=0,updated_at=? WHERE campaign_id=?", (now, r['campaign_id']))
            changed += 1
    if changed:
        db.audit(actor, 'campaign_cycle_limit_finalize', target_type='campaign', details=json.dumps({'archived': changed}))
    return changed
