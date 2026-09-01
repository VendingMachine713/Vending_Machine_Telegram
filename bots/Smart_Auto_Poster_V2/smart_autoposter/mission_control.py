from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from .db import Database
from .progress import progress_snapshot, progress_bar
from .queue_hygiene import queue_hygiene_plan


def _short(value, n=44):
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    return text if len(text) <= n else text[: max(1, n - 1)] + "â€¦"


def mission_snapshot(db: Database, *, campaign_id: str | None = None, limit: int = 12) -> dict:
    progress = progress_snapshot(db, campaign_id=campaign_id, limit=max(1, limit))
    with db.connect() as con:
        queue_rows = con.execute("SELECT status,COUNT(*) n FROM queue GROUP BY status ORDER BY status").fetchall()
        accounts = [dict(r) for r in con.execute(
            "SELECT account_key,enabled,authorized,identity,cooldown_until,health_score,last_success_at,last_failure_at,last_error FROM accounts ORDER BY account_key"
        ).fetchall()]
        modes = [dict(r) for r in con.execute(
            "SELECT mode,COUNT(*) n FROM destinations WHERE enabled=1 AND needs_review=0 GROUP BY mode ORDER BY mode"
        ).fetchall()]
        schedule = None
        if progress.get("campaign_id"):
            row = con.execute(
                "SELECT mode,interval_seconds,timezone,next_run_at,last_run_at,enabled FROM campaign_schedules WHERE campaign_id=?",
                (progress["campaign_id"],),
            ).fetchone()
            schedule = dict(row) if row else None
        attention = [dict(r) for r in con.execute(
            '''SELECT q.id,q.status,q.error_kind,q.last_error,q.pass_no,q.due_at,d.group_name
               FROM queue q JOIN destinations d ON d.group_id=q.group_id
               WHERE q.status IN ('uncertain','failed','quarantined')
               ORDER BY q.updated_at DESC LIMIT ?''', (max(1, limit),)
        ).fetchall()]
        unresolved_groups = int(con.execute(
            '''SELECT COUNT(*) FROM (
                 SELECT group_id,COUNT(*) n FROM queue
                 WHERE status IN ('pending','retry','deferred','processing','sending','uncertain')
                 GROUP BY group_id HAVING COUNT(*)>1
               )'''
        ).fetchone()[0])
    hygiene = queue_hygiene_plan(db, campaign_id=None)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "campaign_id": progress.get("campaign_id"),
        "progress": progress,
        "queue_counts": {r["status"]: int(r["n"]) for r in queue_rows},
        "accounts": accounts,
        "destination_modes": {r["mode"]: int(r["n"]) for r in modes},
        "schedule": schedule,
        "attention": attention,
        "duplicate_unresolved_group_sets": unresolved_groups,
        "safe_suppressible_overlap_rows": hygiene.get("safe_suppressions", 0),
        "overlap_review_rows": hygiene.get("review_count", 0),
        "anti_spam_ok": unresolved_groups == 0,
    }


def render_mission_control(snapshot: dict, *, emoji: bool = False) -> str:
    p = snapshot.get("progress") or {}
    q = snapshot.get("queue_counts") or {}
    modes = snapshot.get("destination_modes") or {}
    icon = "ðŸ§­ " if emoji else ""
    lines = [
        f"{icon}SMART AUTO POSTER MISSION CONTROL",
        f"Campaign: {snapshot.get('campaign_id') or '-'}",
    ]
    if p.get("found"):
        lines.append(f"Run: {_short(p.get('run_key'), 64)}")
        lines.append(f"Progress {progress_bar(p.get('progress_percent',0), 16)} {p.get('progress_percent',0)}%")
        lines.append(
            f"Pass {p.get('current_pass') or '-'} | SENT {p.get('counts',{}).get('sent',0)}/{p.get('total',0)} | "
            f"deferred {p.get('counts',{}).get('deferred',0)} | retry {p.get('counts',{}).get('retry',0)} | stuck {p.get('stuck_count',0)}"
        )
    lines.append(
        f"Queue: pending {q.get('pending',0)} | processing {q.get('processing',0)} | sending {q.get('sending',0)} | "
        f"deferred {q.get('deferred',0)} | retry {q.get('retry',0)} | uncertain {q.get('uncertain',0)}"
    )
    lines.append(f"Delivery modes: photo {modes.get('photo',0)} | text {modes.get('text',0)}")
    lines.append(f"Anti-spam overlap groups: {snapshot.get('duplicate_unresolved_group_sets',0)} ({'OK' if snapshot.get('anti_spam_ok') else 'ATTENTION'})")
    if snapshot.get('duplicate_unresolved_group_sets',0):
        lines.append(f"  safely suppressible unsent rows {snapshot.get('safe_suppressible_overlap_rows',0)} | evidence/review {snapshot.get('overlap_review_rows',0)}")
    sched = snapshot.get("schedule")
    if sched:
        lines.append(f"Schedule: {sched.get('mode')} | next {sched.get('next_run_at') or '-'} | enabled {bool(sched.get('enabled'))}")
    if snapshot.get("accounts"):
        lines.append("Accounts:")
        for a in snapshot["accounts"]:
            state = "ready" if a.get("enabled") and a.get("authorized") and not a.get("cooldown_until") else "cooldown/limited"
            lines.append(f"  {a.get('account_key')}: {state} | health {a.get('health_score')} | {_short(a.get('identity'),24)}")
    if snapshot.get("attention"):
        lines.append("Attention:")
        for r in snapshot["attention"]:
            lines.append(f"  #{r['id']} {r['status']} p{r.get('pass_no') or 1} -> {_short(r['group_name'],24)} | {_short(r.get('error_kind') or r.get('last_error'),38)}")
    return "\n".join(lines)
