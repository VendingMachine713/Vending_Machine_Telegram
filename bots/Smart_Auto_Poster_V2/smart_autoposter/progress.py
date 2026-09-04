from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .db import Database


# Progress reflects pipeline advancement, not success. Terminal failures therefore
# reach 100% processed but remain visibly FAILED/UNCERTAIN in the outcome counts.
_STAGE_META = {
    "pending": {"percent": 10, "stage": "QUEUED", "icon": "🕒", "terminal": False},
    "deferred": {"percent": 25, "stage": "DEFERRED", "icon": "⏸", "terminal": False},
    "retry": {"percent": 35, "stage": "RETRY", "icon": "🔁", "terminal": False},
    "processing": {"percent": 45, "stage": "PREPARING", "icon": "⚙️", "terminal": False},
    "sending": {"percent": 65, "stage": "SENDING", "icon": "📤", "terminal": False},
    "uncertain": {"percent": 90, "stage": "VERIFY", "icon": "⚠️", "terminal": True},
    "sent": {"percent": 100, "stage": "SENT", "icon": "✅", "terminal": True},
    "failed": {"percent": 100, "stage": "FAILED", "icon": "❌", "terminal": True},
    "quarantined": {"percent": 100, "stage": "QUARANTINED", "icon": "🛑", "terminal": True},
    "cancelled": {"percent": 100, "stage": "CANCELLED", "icon": "🚫", "terminal": True},
    "expired": {"percent": 100, "stage": "EXPIRED", "icon": "⌛", "terminal": True},
}

ACTIVE_STATUSES = {"pending", "deferred", "retry", "processing", "sending"}
ATTENTION_STATUSES = {"uncertain", "failed", "quarantined"}
TERMINAL_STATUSES = {k for k, v in _STAGE_META.items() if v["terminal"]}

_PIPELINE_STEPS = [
    ("validating_destination", "Destination validated"),
    ("checking_timing", "Timing / rate-limit checked"),
    ("validating_content", "Compatible content selected"),
    ("selecting_account", "Telegram account selected"),
    ("preparing_payload", "Payload prepared"),
    ("starting_telegram_send", "Telegram send started"),
    ("telegram_acknowledged", "Telegram acknowledgement received"),
    ("sent", "Delivery recorded SENT"),
]


def _short(value, n: int = 44) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    if len(text) <= n:
        return text
    return text[: max(1, n - 1)] + "…"


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError):
        return None


def _local_due(value: str | None, timezone_name: str) -> str | None:
    dt = _parse_iso(value)
    if dt is None:
        return None
    try:
        local = dt.astimezone(ZoneInfo(timezone_name))
    except Exception:
        local = dt.astimezone(timezone.utc)
    return local.strftime("%H:%M:%S")


def progress_bar(percent: int | float, width: int = 20, *, green: bool = False) -> str:
    width = max(5, min(40, int(width)))
    pct = max(0, min(100, int(round(float(percent)))))
    filled = int(round(width * pct / 100.0))
    filled = max(0, min(width, filled))
    if green:
        return ("🟩" * filled) + ("⬜" * (width - filled))
    return "[" + ("#" * filled) + ("-" * (width - filled)) + "]"


def status_stage(status: str | None) -> dict:
    key = str(status or "pending").lower()
    meta = _STAGE_META.get(key, {"percent": 0, "stage": key.upper() or "UNKNOWN", "icon": "•", "terminal": False})
    return {"status": key, **meta}


def _select_run(db: Database, *, campaign_id: str | None = None, run_key: str | None = None):
    with db.connect() as con:
        if run_key:
            sql = "SELECT run_key,campaign_id,MAX(id) newest_id FROM queue WHERE run_key=?"
            params: list[object] = [run_key]
            if campaign_id:
                sql += " AND campaign_id=?"
                params.append(campaign_id)
            sql += " GROUP BY run_key,campaign_id ORDER BY newest_id DESC LIMIT 1"
            row = con.execute(sql, params).fetchone()
            return dict(row) if row else None

        sql = "SELECT run_key,campaign_id,id newest_id FROM queue WHERE run_key IS NOT NULL"
        params: list[object] = []
        if campaign_id:
            sql += " AND campaign_id=?"
            params.append(campaign_id)
        sql += " ORDER BY id DESC LIMIT 1"
        row = con.execute(sql, params).fetchone()
        return dict(row) if row else None


def progress_snapshot(
    db: Database,
    *,
    campaign_id: str | None = None,
    run_key: str | None = None,
    limit: int = 40,
) -> dict:
    selected = _select_run(db, campaign_id=campaign_id, run_key=run_key)
    if not selected:
        return {
            "found": False,
            "campaign_id": campaign_id,
            "run_key": run_key,
            "total": 0,
            "shown": 0,
            "counts": {},
            "progress_percent": 0,
            "finalised": 0,
            "sent": 0,
            "deferred": 0,
            "attention": 0,
            "active": 0,
            "state": "EMPTY",
            "jobs": [],
        }

    selected_run = selected["run_key"]
    selected_campaign = selected["campaign_id"]
    with db.connect() as con:
        rows = con.execute(
            '''SELECT q.id,q.run_key,q.campaign_id,q.group_id,q.content_id,q.status,q.attempts,q.max_attempts,
                      q.account_key,q.due_at,q.error_kind,q.last_error,q.telegram_message_ids,q.created_at,q.updated_at,
                      q.pass_no,q.phase,q.phase_percent,q.phase_detail,q.phase_updated_at,q.deferral_count,
                      q.progress_current,q.progress_total,q.progress_unit,
                      d.group_name,d.mode,c.enabled AS campaign_enabled,c.lifecycle_state AS campaign_state,
                      (SELECT da.outcome FROM delivery_attempts da WHERE da.queue_id=q.id ORDER BY da.id DESC LIMIT 1) latest_attempt_outcome,
                      (SELECT da.error_kind FROM delivery_attempts da WHERE da.queue_id=q.id ORDER BY da.id DESC LIMIT 1) latest_attempt_kind,
                      (SELECT da.retry_at FROM delivery_attempts da WHERE da.queue_id=q.id ORDER BY da.id DESC LIMIT 1) latest_retry_at,
                      (SELECT h.created_at FROM queue_stage_history h WHERE h.queue_id=q.id ORDER BY h.id DESC LIMIT 1) last_stage_at,
                      (SELECT COUNT(*) FROM queue_stage_history h WHERE h.queue_id=q.id) history_count,
                      (SELECT COUNT(*) FROM queue_phase_history ph WHERE ph.queue_id=q.id) phase_history_count
               FROM queue q JOIN destinations d ON d.group_id=q.group_id
               JOIN campaigns c ON c.campaign_id=q.campaign_id
               WHERE q.run_key=? AND q.campaign_id=?
               ORDER BY q.id ASC''',
            (selected_run, selected_campaign),
        ).fetchall()
        duration_rows = con.execute(
            '''SELECT duration_ms FROM delivery_attempts
               WHERE outcome='sent' AND duration_ms IS NOT NULL AND duration_ms>0
               ORDER BY id DESC LIMIT 100'''
        ).fetchall()

    durations = sorted(int(r['duration_ms']) for r in duration_rows)
    if durations:
        median_ms = durations[len(durations)//2]
        avg_slot_seconds = max(2.0, min(60.0, median_ms / 1000.0 + 3.0))
    else:
        avg_slot_seconds = 5.0
    now_dt = datetime.now(timezone.utc)
    jobs: list[dict] = []
    counts: Counter[str] = Counter()
    stage_total = 0
    for raw in rows:
        row = dict(raw)
        meta = status_stage(row.get("status"))
        counts[meta["status"]] += 1
        raw_phase = str(row.get("phase") or "").strip().lower()
        phase_stale_for_status = raw_phase in {"", "queued"} and meta["status"] != "pending"
        if phase_stale_for_status:
            live_phase = meta["stage"]
            live_percent = int(meta["percent"])
        else:
            live_phase = str(row.get("phase") or meta["stage"]).replace("_", " ").upper()
            live_percent = max(int(meta["percent"]), int(row.get("phase_percent") or 0)) if meta["terminal"] else int(row.get("phase_percent") or meta["percent"])
        stage_total += live_percent
        stage_at = _parse_iso(row.get('phase_updated_at') or row.get('last_stage_at') or row.get('updated_at'))
        stage_age = max(0, int((now_dt - stage_at).total_seconds())) if stage_at else None
        due_dt = _parse_iso(row.get('due_at'))
        overdue = max(0, int((now_dt - due_dt).total_seconds())) if due_dt and due_dt < now_dt else 0
        campaign_running = bool(row.get('campaign_enabled')) and str(row.get('campaign_state') or '') == 'active'
        stuck = False
        stuck_reason = None
        if meta['status'] in {'processing','sending'} and stage_age is not None and stage_age >= 120:
            stuck = True; stuck_reason = f"{row.get('phase') or meta['status']} for {stage_age}s"
        elif meta['status'] in {'pending','deferred','retry'} and overdue >= 300 and campaign_running:
            stuck = True; stuck_reason = f"overdue by {overdue}s"
        elif meta['status'] in {'pending','deferred','retry'} and overdue and not campaign_running:
            stuck_reason = f"campaign {row.get('campaign_state') or 'inactive'}"
        jobs.append({
            **row,
            "stage": live_phase,
            "stage_percent": live_percent,
            "stage_icon": meta["icon"],
            "terminal": meta["terminal"],
            "stage_age_seconds": stage_age,
            "overdue_seconds": overdue,
            "stuck": stuck,
            "stuck_reason": stuck_reason,
        })

    total = len(jobs)
    finalised = sum(counts[s] for s in TERMINAL_STATUSES)
    attention = sum(counts[s] for s in ATTENTION_STATUSES)
    active = sum(counts[s] for s in ACTIVE_STATUSES)
    if total == 0:
        state = "EMPTY"
    elif active:
        state = "ACTIVE"
    elif attention:
        state = "ATTENTION"
    else:
        state = "COMPLETE"

    # Estimate completion conservatively for a single worker: each active job
    # consumes one recent median send slot and cannot start before its due time.
    cursor = now_dt
    active_jobs = [j for j in jobs if j['status'] in ACTIVE_STATUSES]
    for job in sorted(active_jobs, key=lambda j: (_parse_iso(j.get('due_at')) or now_dt, int(j.get('id') or 0))):
        due_dt = _parse_iso(job.get('due_at'))
        if due_dt and due_dt > cursor:
            cursor = due_dt
        cursor += timedelta(seconds=avg_slot_seconds)
    eta_seconds = max(0, int((cursor - now_dt).total_seconds())) if active_jobs else 0
    eta_at = cursor.isoformat(timespec='seconds') if active_jobs else None
    future_due = [_parse_iso(j.get('due_at')) for j in active_jobs]
    future_due = [d for d in future_due if d is not None and d > now_dt]
    next_due_at = min(future_due).isoformat(timespec='seconds') if future_due else None
    stuck_count = sum(1 for j in jobs if j.get('stuck'))
    pass_counts: Counter[int] = Counter(int(j.get("pass_no") or 1) for j in jobs if j.get("status") in ACTIVE_STATUSES)
    current_pass = min(pass_counts) if pass_counts else None
    max_pass = max((int(j.get("pass_no") or 1) for j in jobs), default=1)
    first_pass_remaining = sum(1 for j in jobs if int(j.get("pass_no") or 1) == 1 and j.get("status") in ACTIVE_STATUSES)

    limit = max(1, int(limit))
    return {
        "found": True,
        "campaign_id": selected_campaign,
        "run_key": selected_run,
        "total": total,
        "shown": min(total, limit),
        "counts": dict(sorted(counts.items())),
        "progress_percent": int(round(stage_total / total)) if total else 0,
        "finalised": finalised,
        "sent": counts["sent"],
        "deferred": counts["deferred"],
        "attention": attention,
        "active": active,
        "state": state,
        "stuck_count": stuck_count,
        "current_pass": current_pass,
        "max_pass": max_pass,
        "first_pass_remaining": first_pass_remaining,
        "pass_counts": dict(sorted(pass_counts.items())),
        "eta_seconds": eta_seconds,
        "eta_at": eta_at,
        "next_due_at": next_due_at,
        "avg_slot_seconds": round(avg_slot_seconds, 1),
        "jobs": jobs[:limit],
    }


def _job_detail(job: dict, timezone_name: str, *, compact: bool = False) -> str:
    status = str(job.get("status") or "")
    due = _local_due(job.get("due_at"), timezone_name)
    account = job.get("account_key")
    kind = job.get("error_kind") or job.get("latest_attempt_kind")
    error = _short(job.get("last_error"), 28)

    bits: list[str] = []
    bits.append(f"r{int(job.get('pass_no') or 1)}" if compact else f"round {int(job.get('pass_no') or 1)}")
    if job.get("mode"):
        mode = str(job.get("mode"))
        bits.append(mode[:1].upper() if compact else mode)
    if account:
        bits.append(str(account)[:1].upper() if compact else str(account))
    if status in {"pending", "deferred", "retry"} and due:
        bits.append((f"@{due[:5]}" if compact else f"due {due}"))
    if status in {"deferred", "retry", "failed", "quarantined", "uncertain"}:
        reason = None
        if kind and str(kind) not in {"deferred"}:
            reason = _short(kind, 16 if compact else 28)
        elif error:
            reason = _short(error, 16) if compact else error
        if reason:
            bits.append(reason)
    current = job.get("progress_current")
    total = job.get("progress_total")
    unit = str(job.get("progress_unit") or "")
    if current is not None and total:
        if unit == "bytes":
            cur_mb = float(current) / (1024 * 1024)
            total_mb = float(total) / (1024 * 1024)
            bits.append(f"{cur_mb:.1f}/{total_mb:.1f} MB")
        else:
            bits.append(f"{current}/{total} {unit}".strip())
    if job.get("phase_detail") and status in {"processing", "sending"}:
        bits.append(_short(job.get("phase_detail"), 20 if compact else 36))
    return " | ".join(bits)


def _format_seconds(seconds: int | None) -> str:
    if seconds is None:
        return '-'
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {sec:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


def render_progress_text(
    snapshot: dict,
    *,
    timezone_name: str = "Australia/Adelaide",
    emoji: bool = False,
    bar_width: int = 20,
    compact: bool = False,
) -> str:
    if not snapshot.get("found"):
        return "No auto-post run found yet."

    pct = int(snapshot.get("progress_percent") or 0)
    counts = snapshot.get("counts") or {}
    lines = [
        ("📊 AUTO-POST PROGRESS · LIVE" if emoji else "AUTO-POST PROGRESS"),
        f"Campaign: {snapshot.get('campaign_id')}",
        f"Run: {_short(snapshot.get('run_key'), 72)}",
        f"Overall {progress_bar(pct, bar_width, green=emoji)} {pct}%",
        (
            f"Finalised {snapshot.get('finalised',0)}/{snapshot.get('total',0)} | "
            f"SENT {counts.get('sent',0)} | DEFERRED {counts.get('deferred',0)} | "
            f"SENDING {counts.get('sending',0)} | PENDING {counts.get('pending',0)} | "
            f"RETRY {counts.get('retry',0)}"
        ),
    ]
    if snapshot.get('active'):
        pass_text = f"Round {snapshot.get('current_pass')}" if snapshot.get('current_pass') else "No active pass"
        lines.append(
            f"{pass_text} | First-pass remaining {snapshot.get('first_pass_remaining',0)} | "
            f"ETA ~{_format_seconds(snapshot.get('eta_seconds'))} | Stuck {snapshot.get('stuck_count',0)}"
        )
    if snapshot.get("attention"):
        lines.append(
            f"Attention: UNCERTAIN {counts.get('uncertain',0)} | FAILED {counts.get('failed',0)} | QUARANTINED {counts.get('quarantined',0)}"
        )
    lines += ["", "POST STAGES"]

    for job in snapshot.get("jobs", []):
        icon = job.get("stage_icon") if emoji else ""
        prefix = f"{icon} " if icon else ""
        stage = str(job.get("stage") or "UNKNOWN")
        detail = _job_detail(job, timezone_name, compact=compact)
        destination = _short(job.get("group_name"), 22 if compact else 30)
        arrow = "→" if emoji else "->"
        job_bar_width = 8 if compact else 10
        stage_width = 16 if compact else 22
        line = (
            f"{prefix}#{job.get('id')} {progress_bar(job.get('stage_percent',0), job_bar_width, green=emoji)} "
            f"{int(job.get('stage_percent',0)):>3}% {stage:<{stage_width}} {arrow} {destination}"
        )
        sep = " • " if emoji else " | "
        if detail:
            line += f"{sep}{detail}"
        if job.get('stuck'):
            line += f"{sep}STUCK: {_short(job.get('stuck_reason'), 34)}"
        elif job.get('stage_age_seconds') is not None and job.get('status') in ACTIVE_STATUSES:
            line += f"{sep}stage {_format_seconds(job.get('stage_age_seconds'))}"
        lines.append(line)

    omitted = int(snapshot.get("total", 0)) - int(snapshot.get("shown", 0))
    if omitted > 0:
        lines.append(f"... {omitted} more post(s) not shown")
    return "\n".join(lines)


def _terminal_bar(percent: int | float, width: int = 40) -> str:
    """High-resolution ASCII bar safe for Windows cmd.exe/PowerShell."""
    width = max(10, min(72, int(width)))
    pct = max(0, min(100, int(round(float(percent)))))
    filled = int(width * pct / 100.0)
    # Keep the leading edge visible between integer-cell transitions without
    # relying on Unicode block glyphs that break legacy Windows code pages.
    if 0 < pct < 100 and filled < width:
        body = "=" * filled + ">" + "." * max(0, width - filled - 1)
    else:
        body = "=" * filled + "." * (width - filled)
    return "[" + body + "]"


def _focus_job(snapshot: dict) -> dict | None:
    jobs = list(snapshot.get("jobs") or [])
    priority = {"sending": 0, "processing": 1, "retry": 2, "deferred": 3, "pending": 4}
    active = [j for j in jobs if str(j.get("status") or "") in ACTIVE_STATUSES]
    if not active:
        return None
    now = datetime.now(timezone.utc)
    def key(job):
        status = str(job.get("status") or "")
        due = _parse_iso(job.get("due_at")) or now
        return (priority.get(status, 9), due, int(job.get("id") or 0))
    return sorted(active, key=key)[0]


def _next_jobs(snapshot: dict, focus_id: int | None, limit: int = 3) -> list[dict]:
    jobs = [j for j in (snapshot.get("jobs") or []) if str(j.get("status") or "") in ACTIVE_STATUSES and int(j.get("id") or 0) != int(focus_id or -1)]
    now = datetime.now(timezone.utc)
    def key(job):
        due = _parse_iso(job.get("due_at")) or now
        return (due, int(job.get("pass_no") or 1), int(job.get("id") or 0))
    return sorted(jobs, key=key)[:max(0, int(limit))]


def render_terminal_dashboard(
    snapshot: dict,
    *,
    timezone_name: str = "Australia/Adelaide",
    terminal_width: int = 100,
    max_rows: int = 14,
) -> str:
    """Render a stable, dense live dashboard for Windows terminals."""
    if not snapshot.get("found"):
        return "SMART AUTO POSTER - LIVE PROGRESS\nNo auto-post run found yet."

    width = max(76, min(160, int(terminal_width or 100)))
    counts = snapshot.get("counts") or {}
    pct = int(snapshot.get("progress_percent") or 0)
    total = int(snapshot.get("total") or 0)
    finalised = int(snapshot.get("finalised") or 0)
    remaining = max(0, total - finalised)
    bar_width = max(24, min(64, width - 28))
    rule = "=" * min(width, 118)
    lines = [
        rule,
        " SMART AUTO POSTER - LIVE PRODUCTION PROGRESS",
        rule,
        f" Campaign : {_short(snapshot.get('campaign_id'), 58)}",
        f" Run      : {_short(snapshot.get('run_key'), max(30, width - 14))}",
        "",
        f" OVERALL  {_terminal_bar(pct, bar_width)} {pct:>3}%",
        f"          {finalised}/{total} finalised | {remaining} remaining | ETA {_format_seconds(snapshot.get('eta_seconds'))}",
    ]

    current_pass = snapshot.get("current_pass")
    if current_pass:
        pass_active = int((snapshot.get("pass_counts") or {}).get(current_pass, 0))
        pass_done = max(0, total - int(snapshot.get("active") or 0))
        pass_pct = int(round((pass_done / total) * 100)) if total else 0
        lines.append(f" PASS {current_pass:<3} {_terminal_bar(pass_pct, max(18, min(38, bar_width - 8)))} {pass_pct:>3}% | active {pass_active} | first-pass left {snapshot.get('first_pass_remaining',0)}")

    lines += [
        "",
        " OUTCOMES",
        f" SENT {counts.get('sent',0):>3}  | DEFERRED {counts.get('deferred',0):>3} | RETRY {counts.get('retry',0):>3} | PENDING {counts.get('pending',0):>3} | SENDING {counts.get('sending',0):>3}",
        f" UNCERTAIN {counts.get('uncertain',0):>3} | FAILED {counts.get('failed',0):>3}   | CANCELLED {counts.get('cancelled',0):>3} | STUCK {snapshot.get('stuck_count',0):>3}",
    ]

    focus = _focus_job(snapshot)
    lines += ["", " CURRENT POST"]
    if focus:
        fpct = int(focus.get("stage_percent") or 0)
        name = _short(focus.get("group_name"), max(24, width - 36))
        lines.append(f" #{focus.get('id')}  {name}")
        lines.append(f" {_terminal_bar(fpct, bar_width)} {fpct:>3}%  {str(focus.get('stage') or 'UNKNOWN')}")
        detail = _job_detail(focus, timezone_name, compact=False)
        if detail:
            lines.append(f" {detail}")
        if focus.get("stuck"):
            lines.append(f" ATTENTION: STUCK - {_short(focus.get('stuck_reason'), width - 22)}")
        nexts = _next_jobs(snapshot, int(focus.get("id") or 0), 3)
        if nexts:
            lines.append(" Next     : " + " | ".join(f"#{j.get('id')} {_short(j.get('group_name'),18)} ({j.get('status')})" for j in nexts))
    else:
        lines.append(" No active post. Run is complete or waiting for attention.")

    lines += ["", " DESTINATION PIPELINE"]
    jobs = list(snapshot.get("jobs") or [])
    # Put active/attention rows first, while retaining SENT rows for useful visual completion.
    order = {"sending":0,"processing":1,"retry":2,"deferred":3,"pending":4,"uncertain":5,"failed":6,"quarantined":7,"sent":8,"cancelled":9,"expired":10}
    jobs = sorted(jobs, key=lambda j: (order.get(str(j.get("status") or ""), 99), int(j.get("id") or 0)))
    for job in jobs[:max(4, int(max_rows))]:
        jpct = int(job.get("stage_percent") or 0)
        status = str(job.get("status") or "").upper()
        name = _short(job.get("group_name"), 27)
        mini = _terminal_bar(jpct, 12)
        due = _local_due(job.get("due_at"), timezone_name)
        suffix = ""
        if status in {"DEFERRED","RETRY","PENDING"} and due:
            suffix = f" due {due}"
        kind = job.get("error_kind") or job.get("latest_attempt_kind")
        if status in {"DEFERRED","RETRY","UNCERTAIN","FAILED"} and kind:
            suffix += f" {str(kind)[:22]}"
        lines.append(f" #{int(job.get('id') or 0):<4} {mini} {jpct:>3}% {status:<10} {name:<27}{suffix}")
    if len(jobs) > max_rows:
        lines.append(f" ... {len(jobs) - max_rows} more destination(s); use --limit to expand")

    lines += [
        "",
        f" State: {snapshot.get('state')} | refresh live | Ctrl+C stops dashboard",
        rule,
    ]
    return "\n".join(lines)



def post_pipeline_snapshot(db: Database, queue_id: int, *, history_limit: int = 60) -> dict:
    """Return one queue job plus its durable per-step pipeline timeline."""
    from .lifecycle import queue_phase_history, queue_stage_history
    with db.connect() as con:
        row = con.execute(
            '''SELECT q.*,d.group_name,d.mode,c.name AS campaign_name
               FROM queue q JOIN destinations d ON d.group_id=q.group_id
               JOIN campaigns c ON c.campaign_id=q.campaign_id WHERE q.id=?''',
            (int(queue_id),),
        ).fetchone()
        attempts = [dict(r) for r in con.execute(
            '''SELECT id,created_at,attempt_number,outcome,error_kind,retry_at,duration_ms,account_key,details
               FROM delivery_attempts WHERE queue_id=? ORDER BY id ASC LIMIT ?''',
            (int(queue_id), max(1, min(200, int(history_limit)))),
        ).fetchall()]
    if not row:
        return {"found": False, "queue_id": int(queue_id), "phases": [], "stages": [], "attempts": []}
    return {
        "found": True,
        "queue_id": int(queue_id),
        "job": dict(row),
        "phases": queue_phase_history(db, int(queue_id), limit=history_limit),
        "stages": queue_stage_history(db, int(queue_id), limit=history_limit),
        "attempts": attempts,
    }


def _pipeline_checklist(snapshot: dict) -> list[str]:
    job = snapshot.get("job") or {}
    current_pass = int(job.get("pass_no") or 1)
    seen = []
    for item in snapshot.get("phases") or []:
        if int(item.get("pass_no") or 1) == current_pass:
            phase = str(item.get("phase") or "")
            if phase and phase not in seen:
                seen.append(phase)
    current = str(job.get("phase") or "queued")
    reached = set(seen) | {current}
    order = [x[0] for x in _PIPELINE_STEPS]
    current_index = order.index(current) if current in order else -1
    lines = []
    for index, (phase, label) in enumerate(_PIPELINE_STEPS):
        if phase in reached and phase != current:
            mark = "[x]"
        elif phase == current:
            mark = "[>]"
        elif current_index >= 0 and index < current_index:
            mark = "[x]"
        else:
            mark = "[ ]"
        lines.append(f"  {mark} {label}")
    status = str(job.get("status") or "")
    if status in {"deferred","retry","uncertain","failed","quarantined","cancelled","expired"}:
        lines.append(f"  [!] Current outcome: {status.upper()}" + (f" ({job.get('error_kind')})" if job.get("error_kind") else ""))
    return lines


def render_post_pipeline(snapshot: dict, *, timezone_name: str = "Australia/Adelaide", emoji: bool = False) -> str:
    if not snapshot.get("found"):
        return f"Post job #{snapshot.get('queue_id')} was not found."
    job = snapshot["job"]
    meta = status_stage(job.get("status"))
    phase = str(job.get("phase") or meta["stage"]).replace("_", " ").upper()
    pct = int(job.get("phase_percent") or meta["percent"])
    lines = [
        ("ðŸ”Ž POST PIPELINE" if emoji else "POST PIPELINE"),
        f"Job #{job['id']} -> {_short(job.get('group_name'), 48)}",
        f"Campaign: {job.get('campaign_id')} | Round {int(job.get('pass_no') or 1)} | Mode {job.get('mode')}",
        f"Current {progress_bar(pct, 20)} {pct}% {phase}",
        f"Status: {str(job.get('status') or '').upper()} | Account: {job.get('account_key') or '-'} | Attempts: {job.get('attempts',0)}/{job.get('max_attempts',0)}",
    ]
    detail = _job_detail(job, timezone_name, compact=False)
    if detail:
        lines.append(f"Detail: {detail}")
    lines.append("")
    lines.append("CURRENT PASS CHECKLIST")
    lines.extend(_pipeline_checklist(snapshot))
    lines.append("")
    lines.append("PIPELINE HISTORY")
    phases = snapshot.get("phases") or []
    for item in phases[-20:]:
        name = str(item.get("phase") or "unknown").replace("_", " ").upper()
        transfer = ""
        cur, total, unit = item.get("progress_current"), item.get("progress_total"), item.get("progress_unit")
        if cur is not None and total:
            if unit == "bytes":
                transfer = f" | {float(cur)/(1024*1024):.1f}/{float(total)/(1024*1024):.1f} MB"
            else:
                transfer = f" | {cur}/{total} {unit or ''}".rstrip()
        lines.append(
            f"  R{int(item.get('pass_no') or 1)} {int(item.get('phase_percent') or 0):>3}% {name}{transfer}"
            + (f" | {_short(item.get('detail'), 54)}" if item.get('detail') else "")
        )
    if snapshot.get("attempts"):
        lines.append("")
        lines.append("DELIVERY ATTEMPTS")
        for item in snapshot["attempts"][-10:]:
            text = f"  #{item.get('attempt_number')} {str(item.get('outcome') or '').upper()}"
            if item.get("error_kind"):
                text += f" | {item.get('error_kind')}"
            if item.get("retry_at"):
                text += f" | retry {item.get('retry_at')}"
            lines.append(text)
    return "\n".join(lines)
