from __future__ import annotations

from . import __version__
import argparse
import asyncio
import csv
import json
import shutil
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .core import (
    add_campaign_content, campaign_preview, clone_campaign, create_campaign, create_content,
    enqueue_campaign, refresh_system_tags, validate, repair_routing_preferences, remove_campaign_content,
)
from .db import Database, utcnow
from .importer import import_config
from .scheduler import Scheduler, configure_daily, configure_interval, configure_once, disable_schedule, rearm_schedule, simulate_schedules
from .settings import Settings
from .account_guard import assert_distinct_authorized_accounts
from .runtime_lock import RuntimeLock
from .safety import SafetyController
from .time_rules import parse_hhmm
from .content_library import ensure_content_structure, import_content_inbox, audit_content_library
from .wizard import campaign_wizard
from .destination_sync import sync_destinations
from .operations import (
    audit, bulk_cancel_campaign, bulk_destination_action, manage_job, mark_campaign_previewed,
    operational_summary, queue_capacity, recent_audit, set_campaign_state, set_content_state, set_content_tags, set_campaign_gap, remove_campaign_gap,
    record_update_history, recent_update_history, retry_failed_safely,
)
from .maintenance import database_integrity, vacuum_database, generate_diagnostics, media_cache_status, clear_media_cache, cleanup_storage, prune_database
from .watchdog import Watchdog
from .templates import list_templates, create_from_template
from .analytics import analytics_snapshot
from .collections import CollectionSpec, upsert_collection, list_collections, collection_preview, delete_collection
from .rules import upsert_rule, list_rules, apply_rules, evaluate_rule
from .recommendations import generate_recommendations, list_recommendations, apply_recommendation, dismiss_recommendation
from .reports import daily_report_text, weekly_report_text
from .production import ProductionBootstrapSpec, bootstrap_production, production_readiness, canary_queue_status, album_delivery_plan, apply_album_delivery_modes, reconcile_visual_canary_sent
from .delivery_intelligence import delivery_diagnosis, safe_recovery_plan
from .reconciliation import uncertain_jobs, reconciliation_history, reconcile_uncertain
from .progress import progress_snapshot, render_progress_text, render_terminal_dashboard, post_pipeline_snapshot, render_post_pipeline
from .mission_control import mission_snapshot, render_mission_control
from .lifecycle import queue_phase_history
from .queue_hygiene import queue_hygiene_plan, apply_queue_hygiene, install_active_group_guard
from .v5_controller import production_gate
from .v6_controller import v6_readiness, render_v6_control, refresh_destination_intelligence, refresh_delivery_confidence, predictive_plan, recovery_snapshot
from .uncertain_evidence import scan_uncertain_history
from .live_coverage import run_live_coverage, _snapshot as live_coverage_snapshot, render_dashboard as render_live_coverage, export_report as export_live_coverage_report




def _console_text(value, *, encoding: str | None = None) -> str:
    """Return text that cannot crash the active console encoder.

    Telegram/group names may contain arbitrary Unicode while Windows PowerShell
    5.1 commonly captures native stdout through a legacy code page.  Rendering
    remains lossless on UTF-8 consoles and substitutes only characters the
    current console genuinely cannot represent.
    """
    text = str(value)
    enc = encoding or getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        return text.encode(enc, errors="replace").decode(enc, errors="replace")
    except LookupError:
        return text.encode("ascii", errors="replace").decode("ascii")


def _console_print(value=""):
    print(_console_text(value))


def _json_text(value, *, machine_safe: bool = False, indent: int = 2):
    """Serialize structured CLI output safely for Windows pipes.

    Windows PowerShell 5.1 may capture native stdout through a legacy code page.
    Machine-parsed JSON therefore defaults to ASCII escapes so destination names
    containing symbols such as â™§ cannot crash Python with UnicodeEncodeError.
    """
    return json.dumps(
        value,
        indent=indent,
        ensure_ascii=bool(machine_safe),
        default=str,
    )

def db_for(settings: Settings):
    settings.ensure_dirs()
    db = Database(settings.database_path)
    db.init()
    return db

def _queue_limits(settings: Settings) -> dict:
    return {
        "max_queue_size": settings.max_queue_size,
        "max_pending_per_campaign": settings.max_pending_per_campaign,
        "max_pending_per_destination": settings.max_pending_per_destination,
    }


def _backup_file(src: Path, dst_dir: Path, prefix: str | None = None):
    if not src.exists():
        return None
    dst_dir.mkdir(parents=True, exist_ok=True)
    stamp = utcnow().replace(":", "").replace("+00:00", "Z")
    name = f"{prefix or src.stem}_{stamp}{src.suffix}"
    dst = dst_dir / name
    shutil.copy2(src, dst)
    return dst


def cmd_init(args):
    s = Settings.load(False)
    s.ensure_dirs()
    db = db_for(s)
    print(f"[OK] Database ready: {db.path}")
    print(f"[OK] Runtime folders ready under: {Path.cwd()}")


def cmd_import(args):
    s = Settings.load(False); db = db_for(s)
    src = Path(args.csv or s.config_csv)
    stamp = utcnow().replace(":", "").replace("+00:00", "Z")
    backup = s.backup_dir / f"smart_autoposter_before_import_{stamp}.sqlite3"
    db.backup_to(backup)
    result = import_config(db, src)
    print(f"[BACKUP] {backup}")
    print(f"[OK] Imported {src}: added={result['added']} updated={result['updated']}")


def cmd_validate(args):
    s = Settings.load(False); db = db_for(s)
    problems = validate(db)
    if problems:
        print("[FAIL] Pre-flight problems:")
        for x in problems:
            print(" -", x)
        raise SystemExit(2)
    print("[OK] Local pre-flight validation passed")


def cmd_delivery_intelligence(args):
    s = Settings.load(False); db = db_for(s)
    result = delivery_diagnosis(db, hours=args.hours, campaign_id=args.campaign)
    if args.json_only:
        print(_json_text(result, machine_safe=True)); return
    print("SMART AUTO POSTER DELIVERY INTELLIGENCE")
    print("=" * 72)
    print(f"Problem jobs: {result['problem_jobs']} | Window: {result['window_hours']}h")
    for family, count in result["families"].items():
        print(f"  {family:24} {count}")
    print("\nTop affected destinations")
    for item in result["destinations"][:args.limit]:
        print(f"  {item['group_name'][:36]:36} jobs={item['jobs']:<3} {item['families']}")
    if result["families"].get("uncertain"):
        print("\n[SAFE] UNCERTAIN jobs remain blocked from automatic retry pending Telegram-history reconciliation.")


def cmd_delivery_recovery(args):
    s = Settings.load(False); db = db_for(s)
    result = safe_recovery_plan(db, campaign_id=args.campaign, apply=args.apply)
    print(_json_text(result, machine_safe=True))


def cmd_add_content(args):
    s = Settings.load(False); db = db_for(s)
    caption = Path(args.caption_file).read_text(encoding="utf-8") if args.caption_file else (args.caption or "")
    create_content(db, args.content_id, caption, args.media or [])
    print(f"[OK] Content saved: {args.content_id}")


def cmd_contents(args):
    s = Settings.load(False); db = db_for(s)
    with db.connect() as con:
        rows = con.execute("SELECT content_id,enabled,caption,media_json,updated_at FROM content ORDER BY content_id").fetchall()
    if not rows:
        print("No content items."); return
    print(f"{'CONTENT':24} {'ON':3} {'MEDIA':5} CAPTION")
    print("-" * 80)
    for r in rows:
        try: count = len(json.loads(r["media_json"] or "[]"))
        except Exception: count = -1
        preview = (r["caption"] or "").replace("\n", " ")[:42]
        print(f"{r['content_id'][:24]:24} {('Y' if r['enabled'] else 'N'):3} {count:<5} {preview}")


def cmd_add_campaign(args):
    s = Settings.load(False); db = db_for(s)
    create_campaign(
        db, args.campaign_id, args.name, args.content_id, args.priority, args.tags or "",
        start_at=args.start_at, end_at=args.end_at, min_destination_interval_seconds=args.min_interval,
        exclude_tags=args.exclude_tags or "", rotation_mode=args.rotation,
        min_content_reuse_seconds=int(args.reuse_minutes * 60),
        allow_protected=args.allow_protected, conflict_gap_seconds=int(args.conflict_gap_minutes * 60), spread_seconds=int(args.spread_minutes * 60),
        category=args.category or "", target_collections=args.collections or "", max_cycles=args.max_cycles,
    )
    print(f"[OK] Campaign saved (disabled by default on first creation): {args.campaign_id}")


def cmd_campaigns(args):
    s = Settings.load(False); db = db_for(s)
    with db.connect() as con:
        rows = con.execute('''SELECT c.*,s.mode AS schedule_mode,s.enabled AS schedule_enabled,s.next_run_at,
                              (SELECT COUNT(*) FROM campaign_content cc WHERE cc.campaign_id=c.campaign_id AND cc.enabled=1) AS variant_count
                              FROM campaigns c LEFT JOIN campaign_schedules s ON s.campaign_id=c.campaign_id
                              ORDER BY c.priority DESC,c.campaign_id''').fetchall()
    if not rows:
        print("No campaigns."); return
    print(f"{'CAMPAIGN':18} {'ON':3} {'PRI':3} {'VAR':3} {'ROTATION':12} {'SCHEDULE':10} NEXT RUN")
    print("-" * 105)
    for r in rows:
        sched = r["schedule_mode"] if r["schedule_enabled"] else "manual"
        print(f"{r['campaign_id'][:18]:18} {('Y' if r['enabled'] else 'N'):3} {r['priority']:<3} {r['variant_count']:<3} {r['rotation_mode'][:12]:12} {sched[:10]:10} {r['next_run_at'] or '-'}")


def cmd_campaign_toggle(args):
    s = Settings.load(False); db = db_for(s)
    state = "active" if args.enabled else "paused"
    result = set_campaign_state(db, args.campaign_id, state, actor="local-cli")
    print(f"[OK] Campaign {args.campaign_id}: {result['state']}")


def cmd_schedule(args):
    s = Settings.load(False); db = db_for(s)
    tz = args.timezone or s.timezone
    if args.off:
        disable_schedule(db, args.campaign_id)
        print(f"[OK] Schedule disabled: {args.campaign_id}")
        return
    if args.interval_minutes is not None:
        configure_interval(db, args.campaign_id, int(args.interval_minutes * 60), tz,
                           start_in_seconds=None if args.start_in_minutes is None else int(args.start_in_minutes * 60))
    elif args.once_at is not None:
        configure_once(db, args.campaign_id, args.once_at, tz)
    else:
        times = [x.strip() for x in args.daily_times.split(",") if x.strip()]
        days = [x.strip() for x in (args.days or "").split(",") if x.strip()] or None
        configure_daily(db, args.campaign_id, times, days, tz)
    with db.connect() as con:
        r = con.execute("SELECT * FROM campaign_schedules WHERE campaign_id=?", (args.campaign_id,)).fetchone()
    print(f"[OK] {args.campaign_id} schedule={r['mode']} next_run={r['next_run_at']} timezone={r['timezone']}")


def cmd_schedule_rearm(args):
    s = Settings.load(False); db = db_for(s)
    result = rearm_schedule(db, args.campaign_id)
    print(_json_text(result, machine_safe=True))


def cmd_scheduler(args):
    s = Settings.load(False); db = db_for(s)
    results = Scheduler(db, limits=_queue_limits(s)).tick()
    if not results:
        print("[OK] No schedules due.")
    for r in results:
        print(json.dumps(r, indent=2))


def cmd_enqueue(args):
    s = Settings.load(False); db = db_for(s)
    problems = validate(db)
    if problems:
        print("[FAIL] Fix validation problems before enqueueing:")
        for x in problems: print(" -", x)
        raise SystemExit(2)
    r = enqueue_campaign(db, args.campaign_id, args.dry_run, run_key=args.run_key, limits=_queue_limits(s))
    print(json.dumps(r, indent=2))
    if args.dry_run:
        print("[DRY RUN] Nothing was added to the queue")


def _destination_tags(con, gid: int):
    return [x[0] for x in con.execute("SELECT tag FROM destination_tags WHERE group_id=? ORDER BY tag", (gid,)).fetchall()]


def cmd_destinations(args):
    s = Settings.load(False); db = db_for(s)
    where, params = [], []
    if args.review: where.append("needs_review=1")
    if args.enabled: where.append("enabled=1")
    if args.disabled: where.append("enabled=0")
    if args.search:
        where.append("(LOWER(group_name) LIKE ? OR CAST(group_id AS TEXT) LIKE ? OR LOWER(COALESCE(username,'')) LIKE ?)")
        q = f"%{args.search.lower()}%"; params += [q,q,q]
    sql = "SELECT * FROM destinations" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY group_name LIMIT ?"
    params.append(args.limit)
    with db.connect() as con:
        rows = con.execute(sql, params).fetchall()
        print(f"{'ID':16} {'ON':3} {'REV':3} {'MODE':8} {'ACCT':9} {'P/S':3} NAME / TAGS")
        print("-" * 120)
        for r in rows:
            tags = ",".join(_destination_tags(con, r["group_id"]))
            access = f"{int(bool(r['primary_access']))}/{int(bool(r['secondary_access']))}"
            suffix = f" [{tags}]" if tags else ""
            print(f"{r['group_id']:<16} {('Y' if r['enabled'] else 'N'):3} {('Y' if r['needs_review'] else 'N'):3} {r['mode'][:8]:8} {r['preferred_account'][:9]:9} {access:3} {r['group_name']}{suffix}")


def cmd_destination(args):
    s = Settings.load(False); db = db_for(s)
    gid = int(args.group_id)
    with db.connect() as con:
        row = con.execute("SELECT * FROM destinations WHERE group_id=?", (gid,)).fetchone()
        if not row:
            raise RuntimeError(f"Unknown destination: {gid}")
        sets, vals = [], []
        if args.approve:
            sets += ["needs_review=0"]
        if args.mode is not None:
            sets += ["mode=?"]; vals += [args.mode]
        if args.account is not None:
            sets += ["preferred_account=?"]; vals += [args.account]
        if args.topic is not None:
            sets += ["topic_id=?"]; vals += [None if args.topic.lower() == "none" else int(args.topic)]
        if args.min_interval is not None:
            if args.min_interval < 0: raise ValueError("min interval cannot be negative")
            sets += ["min_interval_seconds=?"]; vals += [args.min_interval]
        if args.quiet_start is not None or args.quiet_end is not None:
            start = args.quiet_start if args.quiet_start is not None else row["quiet_start"]
            end = args.quiet_end if args.quiet_end is not None else row["quiet_end"]
            if (start is None) != (end is None):
                raise ValueError("quiet hours require both --quiet-start and --quiet-end")
            if start and end:
                parse_hhmm(start); parse_hhmm(end)
                if start == end: raise ValueError("quiet start/end cannot be identical")
            sets += ["quiet_start=?", "quiet_end=?"]; vals += [start,end]
        if args.clear_quiet:
            sets += ["quiet_start=NULL", "quiet_end=NULL"]
        if args.note is not None:
            sets += ["notes=?"]; vals += [args.note]
        if args.protect is not None:
            sets += ["protected=?"]; vals += [1 if args.protect else 0]
        if args.never_auto_post is not None:
            sets += ["never_auto_post=?"]; vals += [1 if args.never_auto_post else 0]
        if args.enable is True:
            effective_review = False if args.approve else bool(row["needs_review"])
            effective_mode = args.mode if args.mode is not None else row["mode"]
            if effective_review:
                raise RuntimeError("Destination still needs review. Use --approve before enabling.")
            if effective_mode not in {"photo","text"}:
                raise RuntimeError("Destination mode must be photo or text before enabling.")
            sets += ["enabled=1"]
        elif args.enable is False:
            sets += ["enabled=0"]
        if sets:
            sets += ["updated_at=?"]; vals += [utcnow(), gid]
            con.execute(f"UPDATE destinations SET {','.join(sets)} WHERE group_id=?", vals)
        for tag in args.add_tag or []:
            tag = tag.strip().lower()
            if tag: con.execute("INSERT OR IGNORE INTO destination_tags(group_id,tag) VALUES(?,?)", (gid,tag))
        for tag in args.remove_tag or []:
            con.execute("DELETE FROM destination_tags WHERE group_id=? AND tag=?", (gid,tag.strip().lower()))
        row = con.execute("SELECT * FROM destinations WHERE group_id=?", (gid,)).fetchone()
        tags = _destination_tags(con, gid)
    refresh_system_tags(db)
    with db.connect() as con:
        row = con.execute("SELECT * FROM destinations WHERE group_id=?", (gid,)).fetchone()
        tags = _destination_tags(con, gid)
    print(json.dumps({**dict(row), "tags": tags}, indent=2, default=str))




def cmd_progress(args):
    s = Settings.load(False); db = db_for(s)

    def read_snapshot():
        return progress_snapshot(db, campaign_id=args.campaign, run_key=args.run_key, limit=args.limit)

    if args.json_only:
        print(_json_text(read_snapshot(), machine_safe=True)); return
    if not args.watch:
        _console_print(render_progress_text(read_snapshot(), timezone_name=s.timezone, emoji=False, bar_width=20)); return

    interval = max(1.0, float(args.interval))
    try:
        while True:
            snap = read_snapshot()
            if os.name == "nt":
                os.system("cls")
            else:
                print("\033[2J\033[H", end="")
            term_width = shutil.get_terminal_size(fallback=(100, 30)).columns
            _console_print(render_terminal_dashboard(
                snap, timezone_name=s.timezone, terminal_width=term_width,
                max_rows=max(8, min(int(args.limit), 24)),
            ))
            print(f"Live refresh every {interval:g}s.")
            if snap.get("found") and snap.get("total") and snap.get("finalised") == snap.get("total"):
                print("No active worker-stage jobs remain; live watch complete.")
                break
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nProgress watch stopped.")


def cmd_mission_control(args):
    s = Settings.load(False); db = db_for(s)
    snap = mission_snapshot(db, campaign_id=args.campaign, limit=args.limit)
    if args.json_only:
        print(_json_text(snap, machine_safe=True)); return
    _console_print(render_mission_control(snap, emoji=False))


def cmd_queue_hygiene(args):
    s = Settings.load(False); db = db_for(s)
    if args.apply:
        result = apply_queue_hygiene(db, campaign_id=args.campaign, actor="cli_v5")
        result["database_guard"] = install_active_group_guard(db)
    else:
        result = queue_hygiene_plan(db, campaign_id=args.campaign)
    print(_json_text(result, machine_safe=True))


def cmd_v5_readiness(args):
    s = Settings.load(False); db = db_for(s)
    result = production_gate(db, campaign_id=args.campaign)
    if args.json_only:
        print(_json_text(result, machine_safe=True)); return
    print("SMART AUTO POSTER V5 PRODUCTION GATE")
    print("="*72)
    print(f"Ready: {'YES' if result['ready'] else 'NO'}")
    print(f"UNCERTAIN: {result['uncertain']} | In-flight: {result['in_flight']}")
    print(f"Safe overlap suppressions pending: {result['queue_hygiene']['safe_suppressions']}")
    print(f"Overlap review required: {result['queue_hygiene']['review_count']}")
    if result['blockers']:
        print("BLOCKERS:")
        for x in result['blockers']: print(f" - {x}")
    if result['warnings']:
        print("WARNINGS:")
        for x in result['warnings']: print(f" - {x}")


def cmd_v6_control(args):
    s = Settings.load(False); db = db_for(s)
    result = v6_readiness(db, campaign_id=args.campaign)
    if args.json_only:
        print(_json_text(result, machine_safe=True)); return
    _console_print(render_v6_control(result))

def cmd_v6_intelligence(args):
    s = Settings.load(False); db = db_for(s)
    rows = refresh_destination_intelligence(db)
    rows = sorted(rows, key=lambda x:(-x['delivery_risk'],-x['timing_risk'],x['group_name']))
    if args.limit: rows=rows[:args.limit]
    print(_json_text({'count':len(rows),'destinations':rows}, machine_safe=True))

def cmd_v6_confidence(args):
    s = Settings.load(False); db = db_for(s)
    rows = refresh_delivery_confidence(db, campaign_id=args.campaign)
    print(_json_text({'count':len(rows),'rows':rows[-args.limit:] if args.limit else rows}, machine_safe=True))

def cmd_v6_plan(args):
    s = Settings.load(False); db = db_for(s)
    print(_json_text(predictive_plan(db, campaign_id=args.campaign), machine_safe=True))

def cmd_v6_recovery(args):
    s = Settings.load(False); db = db_for(s)
    print(_json_text(recovery_snapshot(db), machine_safe=True))

def cmd_job_timeline(args):
    s = Settings.load(False); db = db_for(s)
    snap = post_pipeline_snapshot(db, args.job_id, history_limit=args.limit)
    if args.json_only:
        print(_json_text(snap, machine_safe=True)); return
    _console_print(render_post_pipeline(snap, timezone_name=s.timezone, emoji=False))

def cmd_queue(args):
    s = Settings.load(False); db = db_for(s)
    where, params = [], []
    if args.status:
        where.append("q.status=?"); params.append(args.status)
    if args.campaign:
        where.append("q.campaign_id=?"); params.append(args.campaign)
    sql = '''SELECT q.id,q.status,q.due_at,q.attempts,q.account_key,q.campaign_id,q.content_id,q.group_id,d.group_name,q.last_error
             FROM queue q JOIN destinations d ON d.group_id=q.group_id'''
    if where: sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY q.id DESC LIMIT ?"; params.append(args.limit)
    with db.connect() as con: rows = con.execute(sql, params).fetchall()
    if not rows: print("No matching queue jobs."); return
    print(f"{'ID':6} {'STATUS':10} {'ATT':3} {'ACCOUNT':9} {'CAMPAIGN':16} {'CONTENT':18} {'GROUP':16} NAME / ERROR")
    print("-"*120)
    for r in rows:
        tail = r["group_name"]
        if r["last_error"]: tail += " | " + r["last_error"][:55]
        print(f"{r['id']:<6} {r['status'][:10]:10} {r['attempts']:<3} {(r['account_key'] or '-')[:9]:9} {r['campaign_id'][:16]:16} {(r['content_id'] or '-')[:18]:18} {r['group_id']:<16} {tail}")


def cmd_job(args):
    s = Settings.load(False); db = db_for(s)
    if args.retry:
        row = manage_job(db, args.job_id, "retry", actor="local-cli")
    elif args.cancel:
        row = manage_job(db, args.job_id, "cancel", actor="local-cli")
    elif args.mark_sent:
        row = manage_job(db, args.job_id, "mark-sent", actor="local-cli")
    elif args.defer_minutes is not None:
        row = manage_job(db, args.job_id, "defer", actor="local-cli", minutes=args.defer_minutes)
    else:
        with db.connect() as con:
            r = con.execute("SELECT * FROM queue WHERE id=?", (args.job_id,)).fetchone()
        if not r: raise RuntimeError(f"Unknown queue job: {args.job_id}")
        print(json.dumps(dict(r), indent=2)); return
    print(json.dumps(row, indent=2, default=str))


def cmd_uncertain_list(args):
    s = Settings.load(False); db = db_for(s)
    rows = uncertain_jobs(db, campaign_id=args.campaign, limit=args.limit)
    print(_json_text({"count": len(rows), "jobs": rows, "automatic_retry": False}, machine_safe=True))


def cmd_uncertain_reconcile(args):
    s = Settings.load(False); db = db_for(s)
    result = reconcile_uncertain(
        db,
        args.job_id,
        args.outcome,
        evidence=args.evidence,
        confirmation=args.confirmation,
        actor="local-cli",
    )
    print(_json_text(result, machine_safe=True))



def cmd_uncertain_scan(args):
    s = Settings.load(True); db = db_for(s)
    result = asyncio.run(scan_uncertain_history(
        db, s, campaign_id=args.campaign, window_minutes=args.window_minutes,
        diagnostic_window_minutes=args.diagnostic_window_minutes, limit=args.limit, apply_sent=args.apply_sent
    ))
    print(_json_text(result, machine_safe=True))

def cmd_reconciliation_history(args):
    s = Settings.load(False); db = db_for(s)
    rows = reconciliation_history(db, queue_id=args.job_id, limit=args.limit)
    print(_json_text({"count": len(rows), "reconciliations": rows}, machine_safe=True))


def cmd_status(args):
    s = Settings.load(False); db = db_for(s)
    with db.connect() as con:
        print(f"\nSMART AUTO POSTER V{__version__} STATUS")
        print("="*72)
        print(f"database              {db.path}")
        for status, n in con.execute("SELECT status,COUNT(*) FROM queue GROUP BY status ORDER BY status"):
            print(f"queue {status:15} {n}")
        print("destinations enabled  ", con.execute("SELECT COUNT(*) FROM destinations WHERE enabled=1").fetchone()[0])
        print("destinations review   ", con.execute("SELECT COUNT(*) FROM destinations WHERE needs_review=1").fetchone()[0])
        print("destinations quarantine", con.execute("SELECT COUNT(*) FROM destinations WHERE quarantine_until> ?", (utcnow(),)).fetchone()[0])
        print("campaigns enabled     ", con.execute("SELECT COUNT(*) FROM campaigns WHERE enabled=1").fetchone()[0])
        print("schedules enabled     ", con.execute("SELECT COUNT(*) FROM campaign_schedules WHERE enabled=1").fetchone()[0])
        print("content items         ", con.execute("SELECT COUNT(*) FROM content").fetchone()[0])
        print("collections           ", con.execute("SELECT COUNT(*) FROM destination_collections WHERE enabled=1").fetchone()[0])
        print("automation rules      ", con.execute("SELECT COUNT(*) FROM automation_rules WHERE enabled=1").fetchone()[0])
        print("recommendations open  ", con.execute("SELECT COUNT(*) FROM recommendations WHERE status='open'").fetchone()[0])
        accounts = con.execute("SELECT account_key,authorized,identity,cooldown_until,last_error,health_score,last_success_at FROM accounts ORDER BY account_key").fetchall()
        if accounts:
            print("\nACCOUNTS")
            for a in accounts:
                state = "AUTHORIZED" if a["authorized"] else "NOT AUTHORIZED"
                if a["cooldown_until"] and a["cooldown_until"] > utcnow(): state += f" | cooldown until {a['cooldown_until']}"
                print(f"{a['account_key']:10} {state} | {a['identity'] or '-'} | health={a['health_score']} last_success={a['last_success_at'] or '-'}")
        recent = con.execute("SELECT created_at,severity,event_type,message FROM events ORDER BY id DESC LIMIT 10").fetchall()
        if recent:
            print("\nRECENT EVENTS")
            for r in recent: print(f"{r['created_at']} {r['severity']:7} {r['event_type']:18} {r['message'][:86]}")


async def async_scan(args):
    try:
        from .telegram_io import TelegramPool
        from .worker import Worker
    except ImportError as exc:
        raise RuntimeError("Telegram dependencies are not installed. Run: py -m pip install -r requirements.txt") from exc
    s = Settings.load(True); s.ensure_dirs(); db = db_for(s)
    with RuntimeLock(s.runtime_lock_path):
        pool = TelegramPool(s.api_id,s.api_hash,s.sessions,s.staging_chats,s.media_cache_dir)
        await pool.connect()
        try:
            auth = await pool.authorization(); print(json.dumps(auth,indent=2))
            assert_distinct_authorized_accounts(auth)
            Worker(db,pool,timezone_name=s.timezone,min_send_gap_seconds=s.min_send_gap_seconds).sync_accounts(auth,s.sessions)
            result = await sync_destinations(db, pool, auth, fail_closed=True)
            if s.auto_apply_rules_on_scan:
                rule_result = apply_rules(db, actor="manual-scan")
                refresh_system_tags(db)
                result["rules"] = rule_result
                print(f"[RULES] matched={rule_result['matched']} changed={rule_result['changed']}")
            for key in ("primary", "secondary"):
                count = result["counts"].get(key)
                if count is not None:
                    print(f"{key.upper()}: {count} destinations")
            repaired = result["routing_repaired"]
            if repaired["total"]:
                print(f"[ROUTING] Repaired {repaired['total']} stale account preference(s): {repaired['to_primary']} -> primary, {repaired['to_secondary']} -> secondary")
            print(f"[SYNC] new={result['new']} lost_disabled={result['lost_disabled']} system_tags={result['system_tags_written']}")
            print("[OK] Scan synchronized. New destinations remain REVIEW + disabled. Lost access fails closed.")
        finally:
            await pool.disconnect()

def cmd_scan(args): asyncio.run(async_scan(args))


async def _telegram_runtime(args, mode: str):
    try:
        from .telegram_io import TelegramPool
        from .worker import Worker
        from .service import AutoPosterService
    except ImportError as exc:
        raise RuntimeError("Telegram dependencies are not installed. Run: py -m pip install -r requirements.txt") from exc
    s = Settings.load(True); s.ensure_dirs(); db = db_for(s)
    safety = _safety_controller(s, db)
    with RuntimeLock(s.runtime_lock_path):
        pool = TelegramPool(s.api_id,s.api_hash,s.sessions,s.staging_chats,s.media_cache_dir)
        await pool.connect()
        try:
            if mode == "worker":
                state = safety.status()
                if state.paused:
                    raise RuntimeError(f"Outbound posting is safety-paused: {state.reason or 'no reason'}")
                auth = await pool.authorization(); print("Authorization:", json.dumps(auth))
                assert_distinct_authorized_accounts(auth)
                w = Worker(db,pool,poll_seconds=args.poll,timezone_name=s.timezone,min_send_gap_seconds=s.min_send_gap_seconds,safety=safety)
                w.sync_accounts(auth,s.sessions)
                recovered = w.recover_interrupted_sends()
                if recovered: print(f"[RECOVERY] {recovered} interrupted send(s) marked UNCERTAIN")
                if args.once:
                    worked = await w.run_once(auth); print("[OK] one queue cycle", "processed" if worked else "idle")
                else:
                    print("[RUNNING] Queue worker active. Ctrl+C to stop cleanly.")
                    await w.run_forever(auth,s.sessions)
            else:
                service = AutoPosterService(db,pool,s,poll_seconds=args.poll,scheduler_seconds=args.scheduler_poll)
                await service.run()
        finally:
            await pool.disconnect()

def cmd_worker(args):
    try: asyncio.run(_telegram_runtime(args,"worker"))
    except KeyboardInterrupt: print("\n[STOPPED] Worker stopped")


def cmd_run(args):
    try: asyncio.run(_telegram_runtime(args,"service"))
    except KeyboardInterrupt: print("\n[STOPPED] Smart Auto Poster stopped cleanly")


def cmd_live_coverage(args):
    async def _run():
        s=Settings.load(True); s.ensure_dirs(); db=db_for(s)
        result=await run_live_coverage(db,s,campaign_id=args.campaign,poll_seconds=args.poll,run_key=args.run_key,evidence_scan=not args.no_evidence_scan)
        print(_json_text({
            "run_key": result["run"]["run_key"], "complete": result.get("complete"),
            "sent": result["sent_count"], "target": result["target_count"],
            "remaining": result["remaining"], "counts": result["counts"],
            "report_files": result.get("report_files"),
        }, machine_safe=True))
        if not result.get("complete"):
            raise RuntimeError("Full-coverage live run finished all safely runnable groups but still has blocked/failed destinations; see troubleshooting report")
    try: asyncio.run(_run())
    except KeyboardInterrupt: print("\n[STOPPED] Full-coverage live run interrupted; existing queue evidence has been preserved")

def cmd_live_coverage_status(args):
    s=Settings.load(False); db=db_for(s)
    if not args.run_key:
        with db.connect() as con:
            r=con.execute("SELECT run_key FROM live_coverage_runs ORDER BY started_at DESC LIMIT 1").fetchone()
        if not r: raise RuntimeError("No live coverage run exists yet")
        args.run_key=r["run_key"]
    snap=live_coverage_snapshot(db,args.run_key)
    _console_print(render_live_coverage(snap, width=args.width))
    if args.export:
        _console_print(_json_text(export_live_coverage_report(db,args.run_key,s.diagnostics_dir),machine_safe=True))

def cmd_health(args):
    import sys
    try:
        from importlib.metadata import version as pkg_version
    except ImportError:
        pkg_version = None
    s = Settings.load(False); s.ensure_dirs(); db = db_for(s)
    checks = []
    checks.append(("Python", True, sys.version.split()[0]))
    try:
        tv = pkg_version("telethon") if pkg_version else "installed"
        checks.append(("Telethon", True, tv))
    except Exception:
        checks.append(("Telethon", False, "not installed - run setup"))
    checks.append(("API credentials", bool(s.api_id and s.api_hash), "configured" if (s.api_id and s.api_hash) else "missing in .env"))
    for key, session in s.sessions.items():
        pth = Path(session)
        if pth.suffix != ".session":
            pth = Path(str(pth) + ".session")
        checks.append((f"{key} session", pth.exists(), str(pth)))
    checks.append(("destination config", s.config_csv.exists(), str(s.config_csv)))
    checks.append(("database", s.database_path.exists(), str(s.database_path)))
    checks.append(("runtime lock", not s.runtime_lock_path.exists(), "clear" if not s.runtime_lock_path.exists() else f"present: {s.runtime_lock_path}"))
    checks.append(("admin control bot", True, "configured" if s.admin_bot_enabled else "optional / not configured"))
    integrity = database_integrity(db)
    checks.append(("database integrity", integrity["ok"], "OK" if integrity["ok"] else str(integrity)))
    safety_state = _safety_controller(s, db).status()
    checks.append(("outbound safety", not safety_state.paused, "ready" if not safety_state.paused else f"PAUSED: {safety_state.reason or '-'}"))
    problems = validate(db)
    checks.append(("local validation", not problems, "OK" if not problems else f"{len(problems)} problem(s)"))

    print(f"SMART AUTO POSTER V{__version__} - HEALTH CHECK")
    print("="*72)
    for name, ok, detail in checks:
        print(f"{('[OK]' if ok else '[!!]'):4} {name:22} {detail}")
    if problems:
        print("\nVALIDATION DETAILS")
        for x in problems:
            print(" -", x)
    ready = all(ok for name,ok,_ in checks if name not in {"destination config", "runtime lock"})
    if ready:
        print("\n[READY] Local runtime prerequisites look ready for controlled live validation.")
    else:
        print("\n[NOT READY] Fix the items marked [!!] before unattended live operation.")


def _safety_controller(s, db):
    return SafetyController(
        db,
        failure_threshold=s.circuit_breaker_failures,
        window_minutes=s.circuit_breaker_window_minutes,
        pause_minutes=s.circuit_breaker_pause_minutes,
        failure_ratio=s.circuit_breaker_failure_ratio,
    )


def cmd_safety_status(args):
    s = Settings.load(False); db = db_for(s)
    state = _safety_controller(s, db).status()
    print("SMART AUTO POSTER - SAFETY STATUS")
    print("="*72)
    print(f"outbound paused       {'YES' if state.paused else 'NO'}")
    print(f"manual pause          {'YES' if state.manual else 'NO'}")
    print(f"pause until           {state.until or '-'}")
    print(f"reason                {state.reason or '-'}")
    print(f"recent successes      {state.successes}")
    print(f"recent failures       {state.failures}")
    print(f"breaker threshold     {s.circuit_breaker_failures} failures / {s.circuit_breaker_window_minutes} min")
    print(f"breaker ratio         {s.circuit_breaker_failure_ratio:.0%}")
    print(f"automatic pause       {s.circuit_breaker_pause_minutes} min")


def cmd_pause(args):
    s = Settings.load(False); db = db_for(s)
    controller = _safety_controller(s, db)
    state = controller.pause(args.reason or "manual outbound pause", args.minutes, manual=(args.minutes is None))
    print(f"[OK] Outbound posting paused. Reason: {state.reason}")
    print(f"Resume: {'manual command required' if state.manual else state.until}")


def cmd_resume(args):
    s = Settings.load(False); db = db_for(s)
    _safety_controller(s, db).resume("manual resume")
    print("[OK] Outbound posting resumed")


def cmd_backup(args):
    s = Settings.load(False); db = db_for(s)
    outputs = []
    stamp = utcnow().replace(":","").replace("+00:00","Z")
    db_dst = s.backup_dir / f"smart_autoposter_{stamp}.sqlite3"
    db.backup_to(db_dst); outputs.append(db_dst)
    cfg = _backup_file(s.config_csv,s.backup_dir,"destination_config")
    if cfg: outputs.append(cfg)
    cache = s.media_cache_dir
    if cache.exists():
        dst = s.backup_dir / f"media_cache_{stamp}"
        shutil.copytree(cache,dst,dirs_exist_ok=True); outputs.append(dst)
    print("[OK] Consistent backup complete")
    for x in outputs: print(" -",x)


def cmd_export(args):
    s = Settings.load(False); db = db_for(s)
    out = Path(args.output); out.parent.mkdir(parents=True,exist_ok=True)
    with db.connect() as con, out.open("w",newline="",encoding="utf-8-sig") as f:
        rows = con.execute("SELECT * FROM destinations ORDER BY group_name").fetchall()
        fields = list(rows[0].keys()) + ["tags"] if rows else ["group_id","group_name","tags"]
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader()
        for r in rows:
            d=dict(r); d["tags"] = ",".join(_destination_tags(con,r["group_id"])); w.writerow(d)
    print(f"[OK] Exported destinations: {out}")



async def async_accounts_check(args):
    try:
        from .telegram_io import TelegramPool
    except ImportError as exc:
        raise RuntimeError("Telegram dependencies are not installed. Run setup first.") from exc
    s = Settings.load(True); s.ensure_dirs()
    with RuntimeLock(s.runtime_lock_path):
        pool = TelegramPool(s.api_id, s.api_hash, s.sessions, s.staging_chats, s.media_cache_dir)
        await pool.connect()
        try:
            auth = await pool.authorization()
            print("TELEGRAM ACCOUNT IDENTITIES")
            print("="*72)
            for key in ("primary", "secondary"):
                state = auth.get(key, {})
                print(f"{key:10} authorized={bool(state.get('authorized'))!s:5} identity={state.get('identity') or '-'} user_id={state.get('user_id') or '-'}")
            assert_distinct_authorized_accounts(auth)
            print("\n[OK] Primary and Secondary are distinct Telegram accounts.")
        finally:
            await pool.disconnect()


def cmd_accounts_check(args):
    asyncio.run(async_accounts_check(args))


async def async_login_account(args):
    try:
        from telethon import TelegramClient
    except ImportError as exc:
        raise RuntimeError("Telethon is not installed. Run setup first.") from exc
    s = Settings.load(True); s.ensure_dirs()
    account = args.account
    session = s.sessions[account]
    session_path = Path(session)
    if session_path.suffix != ".session":
        session_file = Path(str(session_path) + ".session")
    else:
        session_file = session_path
    session_path.parent.mkdir(parents=True, exist_ok=True)

    with RuntimeLock(s.runtime_lock_path):
        if session_file.exists():
            if not args.reset:
                raise RuntimeError(
                    f"{account} session already exists: {session_file}. Use --reset to archive it and log in again."
                )
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup_dir = s.backup_dir / "session_backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            backup = backup_dir / f"{session_file.name}.{stamp}.bak"
            shutil.copy2(session_file, backup)
            for suffix in ("-journal", "-wal", "-shm"):
                sidecar = Path(str(session_file) + suffix)
                if sidecar.exists():
                    shutil.copy2(sidecar, backup_dir / f"{sidecar.name}.{stamp}.bak")
                    sidecar.unlink()
            session_file.unlink()
            cache_file = s.media_cache_dir / f"telegram_media_cache_v2_{account}.json"
            if cache_file.exists():
                cache_backup = backup_dir / f"{cache_file.name}.{stamp}.bak"
                shutil.copy2(cache_file, cache_backup)
                cache_file.unlink()
                print(f"[BACKUP] Previous {account} media cache archived to: {cache_backup}")
            print(f"[BACKUP] Previous {account} session archived to: {backup}")

        print(f"[LOGIN] Logging in the {account.upper()} Telegram account.")
        print("Enter the phone number/code/2FA requested by Telethon. This stays in your local terminal.")
        client = TelegramClient(session, s.api_id, s.api_hash, flood_sleep_threshold=0)
        try:
            await client.start()
            me = await client.get_me()
            identity = getattr(me, "username", None) or getattr(me, "first_name", None) or str(getattr(me, "id", ""))
            print(f"[OK] {account.upper()} authorized as {identity} | Telegram user_id={getattr(me, 'id', '-')}")
        finally:
            await client.disconnect()


def cmd_login_account(args):
    asyncio.run(async_login_account(args))


def cmd_import_content(args):
    s = Settings.load(False); s.ensure_dirs(); db = db_for(s)
    ensure_content_structure(s.content_root)
    results = import_content_inbox(db, s.content_root, move=not args.keep_source)
    if not results:
        print(f"[OK] No content folders waiting in {s.content_root / 'inbox'}")
        return
    print("CONTENT INBOX IMPORT")
    print("="*72)
    for r in results:
        print(json.dumps(r, ensure_ascii=False))
    print(f"[OK] Processed {len(results)} content folder(s)")



def cmd_content_audit(args):
    s = Settings.load(False); db = db_for(s)
    result = audit_content_library(db, s.content_root)
    print("CONTENT LIBRARY AUDIT")
    print("=" * 88)
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    if not result.get("ok"):
        raise SystemExit(2)
    print("[OK] Content library audit passed")

def cmd_campaign_content(args):
    s = Settings.load(False); db = db_for(s)
    if args.add:
        add_campaign_content(db, args.campaign_id, args.add, position=args.position, weight=args.weight)
        print(f"[OK] Added {args.add} to {args.campaign_id}")
    elif args.remove:
        remove_campaign_content(db, args.campaign_id, args.remove)
        print(f"[OK] Disabled {args.remove} in {args.campaign_id}")
    with db.connect() as con:
        rows = con.execute("""SELECT cc.content_id,cc.position,cc.weight,cc.enabled,ct.caption
                              FROM campaign_content cc JOIN content ct ON ct.content_id=cc.content_id
                              WHERE cc.campaign_id=? ORDER BY cc.position,cc.content_id""", (args.campaign_id,)).fetchall()
    if not rows:
        raise RuntimeError(f"No campaign content found: {args.campaign_id}")
    print(f"{'CONTENT':26} {'ON':3} {'POS':4} {'WEIGHT':6} CAPTION")
    print("-"*90)
    for r in rows:
        print(f"{r['content_id'][:26]:26} {('Y' if r['enabled'] else 'N'):3} {r['position']:<4} {r['weight']:<6} {(r['caption'] or '').replace(chr(10),' ')[:40]}")


def cmd_campaign_preview(args):
    s = Settings.load(False); db = db_for(s)
    preview = campaign_preview(db, args.campaign_id)
    mark_campaign_previewed(db, args.campaign_id, actor="local-cli")
    print(json.dumps(preview, indent=2, ensure_ascii=False))


def cmd_campaign_clone(args):
    s = Settings.load(False); db = db_for(s)
    clone_campaign(db, args.source_campaign, args.new_campaign, args.name)
    print(f"[OK] Cloned {args.source_campaign} -> {args.new_campaign} (disabled)")


def cmd_campaign_wizard(args):
    s = Settings.load(False); db = db_for(s)
    campaign_wizard(db, s.timezone)


def cmd_simulate(args):
    s = Settings.load(False); db = db_for(s)
    rows = simulate_schedules(db, args.hours, include_inactive=args.include_inactive, campaign_id=args.campaign)
    scope = f" | campaign={args.campaign}" if args.campaign else ""
    mode = " | INCLUDING INACTIVE (read-only)" if args.include_inactive else ""
    print(f"SCHEDULE SIMULATION - NEXT {args.hours} HOURS{scope}{mode}")
    print("="*100)
    if not rows:
        print("No scheduled campaign runs in this window.")
        return
    totals = {}
    for r in rows:
        preview = campaign_preview(db, r['campaign_id'])
        totals[r['campaign_id']] = totals.get(r['campaign_id'], 0) + preview['selected']
        state = r.get('lifecycle_state') or '-'
        print(f"{r['at']}  {r['campaign_id'][:20]:20} state={state[:8]:8} destinations={preview['selected']:<4} {r['name']}")
    print("\nESTIMATED JOBS (before live eligibility/quiet-hour deferrals)")
    for cid, n in sorted(totals.items()):
        print(f" {cid:24} {n}")
    print(f" Total planned queue jobs: {sum(totals.values())}")


def cmd_queue_summary(args):
    s = Settings.load(False); db = db_for(s)
    with db.connect() as con:
        rows = con.execute("SELECT status,COUNT(*) AS n FROM queue GROUP BY status ORDER BY status").fetchall()
        failures = con.execute("""SELECT q.id,q.status,q.campaign_id,q.group_id,d.group_name,q.account_key,q.attempts,q.last_error,q.updated_at
                                  FROM queue q JOIN destinations d ON d.group_id=q.group_id
                                  WHERE q.status IN ('failed','uncertain') ORDER BY q.updated_at DESC LIMIT ?""", (args.limit,)).fetchall()
    print("QUEUE SUMMARY")
    print("="*88)
    for r in rows:
        print(f"{r['status']:15} {r['n']}")
    if failures:
        print("\nNEEDS ATTENTION")
        for r in failures:
            print(f"#{r['id']} {r['campaign_id']} -> {r['group_name']} [{r['status']}] attempts={r['attempts']} | {(r['last_error'] or '-')[:100]}")


def cmd_retry_failed(args):
    s = Settings.load(False); db = db_for(s)
    result = retry_failed_safely(db, campaign_id=args.campaign, actor="local-cli")
    print(_json_text(result, machine_safe=True))
    print(f"[OK] Safely retried {result['retried']} failed job(s); UNCERTAIN remains blocked")


def cmd_post_now(args):
    s = Settings.load(False); db = db_for(s)
    preview = campaign_preview(db, args.campaign_id)
    print(json.dumps(preview, indent=2))
    if args.dry_run:
        print("[DRY RUN] Post Now did not enqueue anything")
        return
    run_key = f"post-now:{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    result = enqueue_campaign(db, args.campaign_id, dry_run=False, run_key=run_key, limits=_queue_limits(s))
    print(json.dumps(result, indent=2))
    print("[OK] Post Now jobs queued through normal safety/routing rules")


def cmd_daily_summary(args):
    s = Settings.load(False); db = db_for(s)
    summary = operational_summary(db, args.hours)
    print(f"SMART AUTO POSTER V{__version__} - OPERATIONAL SUMMARY")
    print("="*72)
    print(json.dumps(summary, indent=2, ensure_ascii=False, default=str))


def cmd_campaign_state(args):
    s=Settings.load(False); db=db_for(s)
    result=set_campaign_state(db,args.campaign_id,args.state,actor="local-cli")
    print(json.dumps(result,indent=2))


def cmd_content_state(args):
    s=Settings.load(False); db=db_for(s)
    set_content_state(db,args.content_id,args.state,actor="local-cli")
    print(f"[OK] Content {args.content_id}: {args.state}")


def cmd_content_tags(args):
    s=Settings.load(False); db=db_for(s)
    tags=set_content_tags(db,args.content_id,add=args.add_tag,remove=args.remove_tag,actor="local-cli")
    print(json.dumps({"content_id":args.content_id,"tags":tags},indent=2))


def cmd_bulk_destinations(args):
    s=Settings.load(False); db=db_for(s)
    n=bulk_destination_action(db,tag=args.tag,enable=args.enable,protect=args.protect,never_auto_post=args.never_auto_post,
                              add_tag=args.add_tag,remove_tag=args.remove_tag,actor="local-cli")
    refresh_system_tags(db)
    print(f"[OK] Bulk action evaluated {n} destination(s) tagged {args.tag}")


def cmd_cancel_campaign_jobs(args):
    s=Settings.load(False); db=db_for(s)
    n=bulk_cancel_campaign(db,args.campaign_id,actor="local-cli")
    print(f"[OK] Cancelled {n} pending/retry/deferred job(s) for {args.campaign_id}")


def cmd_queue_capacity(args):
    s=Settings.load(False); db=db_for(s)
    result=queue_capacity(db)
    result["limits"]=_queue_limits(s)
    print(json.dumps(result,indent=2))


def cmd_audit_log(args):
    s=Settings.load(False); db=db_for(s)
    print(json.dumps(recent_audit(db,args.limit),indent=2,ensure_ascii=False))


def cmd_watchdog(args):
    s=Settings.load(False); db=db_for(s)
    wd=Watchdog(db,stale_seconds=s.heartbeat_stale_seconds)
    result={"heartbeats":wd.snapshot(),"problems":wd.evaluate(tuple(args.require or ["service","scheduler","worker"]))}
    print(_json_text(result, machine_safe=bool(getattr(args, "json_only", False))))
    if result["problems"]:
        raise SystemExit(2)


def cmd_integrity(args):
    s=Settings.load(False); db=db_for(s)
    result=database_integrity(db); print(json.dumps(result,indent=2))
    if not result["ok"]: raise SystemExit(2)


def cmd_vacuum(args):
    s=Settings.load(False); db=db_for(s)
    vacuum_database(db); print(f"[OK] Database vacuum complete: {db.path}")


def cmd_diagnostics(args):
    s=Settings.load(False); db=db_for(s)
    path=generate_diagnostics(db,s,include_logs=not args.no_logs)
    audit(db,"local-cli","diagnostics_generated","diagnostics",path.name)
    print(f"[OK] Safe diagnostics bundle: {path}")


def cmd_cache_status(args):
    s=Settings.load(False); db=db_for(s)
    print(json.dumps(media_cache_status(s.media_cache_dir),indent=2))


def cmd_clear_cache(args):
    s=Settings.load(False); db=db_for(s)
    removed=clear_media_cache(s.media_cache_dir,args.account)
    audit(db,"local-cli","media_cache_clear","media_cache",args.account or "all",removed=removed)
    print(json.dumps({"removed":removed},indent=2))


def cmd_maintenance(args):
    s=Settings.load(False); db=db_for(s)
    integrity=database_integrity(db)
    cleanup=cleanup_storage(log_dir=s.log_dir,backup_dir=s.backup_dir,diagnostics_dir=s.diagnostics_dir,
                            log_days=s.log_retention_days,backup_keep=s.auto_backup_keep)
    pruned=prune_database(db,event_days=s.event_retention_days,queue_days=s.queue_history_days)
    result={"integrity":integrity,"cleanup":cleanup,"database_prune":pruned}
    audit(db,"local-cli","maintenance",details=result)
    print(json.dumps(result,indent=2))


def cmd_admin_bot(args):
    async def run_admin():
        from .admin_bot import TelegramAdminController
        s=Settings.load(True); db=db_for(s)
        if not s.admin_bot_enabled:
            raise RuntimeError("Admin bot not configured. Set ADMIN_BOT_TOKEN and ADMIN_USER_IDS in .env")
        controller=TelegramAdminController(db,s,_safety_controller(s,db))
        await controller.run()
    try:
        asyncio.run(run_admin())
    except KeyboardInterrupt:
        print("\n[STOPPED] Telegram admin bot stopped")
    except RuntimeError as exc:
        print(f"[ERROR] {exc}")



def cmd_admin_probe(args):
    async def run_probe():
        from .admin_bot import TelegramAdminController
        s = Settings.load(True)
        db = db_for(s)
        if not s.admin_bot_enabled:
            raise RuntimeError("Admin bot not configured. Set ADMIN_BOT_TOKEN and ADMIN_USER_IDS in .env")
        controller = TelegramAdminController(db, s, _safety_controller(s, db))
        client = None
        try:
            client = await controller._build_client()
            me = await client.get_me()
            return {
                "ok": True,
                "bot_id": int(getattr(me, "id", 0) or 0),
                "username": getattr(me, "username", None),
                "session_mode": "persistent" if s.admin_bot_persist_session else "memory",
                "telegram_send_performed": False,
            }
        finally:
            if client is not None:
                try:
                    await client.disconnect()
                except BaseException:
                    pass
    try:
        result = asyncio.run(run_probe())
        print(_json_text(result, machine_safe=True))
    except RuntimeError as exc:
        print(_json_text({"ok": False, "error": str(exc), "telegram_send_performed": False}, machine_safe=True))
        raise SystemExit(2)


def cmd_admin_status(args):
    s=Settings.load(False); db=db_for(s)
    print(json.dumps({"configured":s.admin_bot_enabled,"token_configured":bool(s.admin_bot_token),
                      "control_admin_count":len(s.admin_user_ids),
                      "readonly_admin_count":len(s.admin_readonly_user_ids),"session":s.admin_bot_session,
                      "session_mode":"persistent" if s.admin_bot_persist_session else "memory",
                      "dotenv_source":str(getattr(__import__('smart_autoposter.settings', fromlist=['PROJECT_ENV_PATH']), 'PROJECT_ENV_PATH', '.env')),
                      "dotenv_precedence":"project .env overrides inherited environment",
                      "min_notification_severity":s.admin_notifications_min_severity},indent=2))



def cmd_templates(args):
    print(json.dumps(list_templates(), indent=2, ensure_ascii=False))


def cmd_create_template(args):
    s=Settings.load(False); db=db_for(s)
    t=create_from_template(db,args.template,args.campaign_id,args.name,args.content_id,tags=args.tags or "",exclude_tags=args.exclude_tags or "",timezone_name=s.timezone)
    audit(db,"local-cli","campaign_template_create","campaign",args.campaign_id,template=args.template)
    print(json.dumps(vars(t),indent=2))
    print(f"[OK] Campaign created as DRAFT: {args.campaign_id}")


def cmd_campaign_gap(args):
    s=Settings.load(False); db=db_for(s)
    if args.remove:
        remove_campaign_gap(db,args.campaign_id,args.related_campaign,both=args.both,actor="local-cli")
        print("[OK] Campaign gap relation removed")
    else:
        set_campaign_gap(db,args.campaign_id,args.related_campaign,args.minutes,both=args.both,actor="local-cli")
        print(f"[OK] Minimum gap set: {args.minutes} minute(s)")


def cmd_analytics(args):
    s=Settings.load(False); db=db_for(s)
    print(json.dumps(analytics_snapshot(db,args.hours),indent=2,ensure_ascii=False,default=str))


def cmd_record_update(args):
    s=Settings.load(False); db=db_for(s)
    rid=record_update_history(db,args.version,previous_version=args.previous,status=args.status,package_name=args.package,details=args.details)
    print(f"[OK] Update history recorded: #{rid} {args.status} {args.version}")


def cmd_update_history(args):
    s=Settings.load(False); db=db_for(s)
    rows=recent_update_history(db,args.limit)
    if not rows:
        print("No update history recorded."); return
    print(f"{'ID':4} {'STATUS':12} {'VERSION':16} {'PREVIOUS':16} PACKAGE")
    print('-'*100)
    for r in rows:
        print(f"{r['id']:<4} {r['status'][:12]:12} {r['version'][:16]:16} {(r['previous_version'] or '-')[:16]:16} {r['package_name'] or '-'}")



def cmd_collection(args):
    s=Settings.load(False); db=db_for(s)
    if args.delete:
        delete_collection(db,args.collection_id); print(f"[OK] Deleted collection: {args.collection_id}"); return
    if args.name or args.include_tags or args.exclude_tags or args.access != 'any' or args.mode != 'any' or args.forum_only or args.include_protected or args.disable:
        spec=CollectionSpec(args.collection_id,args.name or args.collection_id,args.include_tags or '',args.exclude_tags or '',args.access,args.mode,args.forum_only,args.include_protected,not args.disable)
        result=upsert_collection(db,spec); print(json.dumps(result,indent=2,ensure_ascii=False)); return
    print(json.dumps(collection_preview(db,args.collection_id),indent=2,ensure_ascii=False))


def cmd_collections(args):
    s=Settings.load(False); db=db_for(s)
    rows=list_collections(db,args.enabled)
    if args.preview:
        print(json.dumps([collection_preview(db,r['collection_id']) for r in rows],indent=2,ensure_ascii=False))
    else:
        print(json.dumps(rows,indent=2,ensure_ascii=False))


def cmd_rule(args):
    s=Settings.load(False); db=db_for(s)
    condition=json.loads(args.condition or '{}'); action=json.loads(args.action or '{}')
    result=upsert_rule(db,args.rule_id,args.name or args.rule_id,condition,action,priority=args.priority,enabled=not args.disable)
    print(json.dumps(result,indent=2,ensure_ascii=False))


def cmd_rules(args):
    s=Settings.load(False); db=db_for(s)
    print(json.dumps(list_rules(db,args.enabled),indent=2,ensure_ascii=False))


def cmd_apply_rules(args):
    s=Settings.load(False); db=db_for(s)
    result=apply_rules(db,rule_id=args.rule,dry_run=args.dry_run,actor='local-cli')
    refresh_system_tags(db)
    print(json.dumps(result,indent=2,ensure_ascii=False))


def cmd_rule_preview(args):
    s=Settings.load(False); db=db_for(s)
    print(json.dumps({'rule_id':args.rule_id,'group_ids':evaluate_rule(db,args.rule_id)},indent=2))


def cmd_recommendations(args):
    s=Settings.load(False); db=db_for(s)
    if args.generate:
        generated=generate_recommendations(db,args.hours)
        print(f"[OK] Generated/refreshed {len(generated)} recommendation(s)")
    print(json.dumps(list_recommendations(db,args.status,args.limit),indent=2,ensure_ascii=False))


def cmd_recommendation(args):
    s=Settings.load(False); db=db_for(s)
    if args.apply:
        print(json.dumps(apply_recommendation(db,args.recommendation_id,actor='local-cli'),indent=2)); return
    if args.dismiss:
        dismiss_recommendation(db,args.recommendation_id); print('[OK] Recommendation dismissed'); return
    rows=[r for r in list_recommendations(db,'open',500) if r['recommendation_id']==args.recommendation_id]
    if not rows: raise RuntimeError('Open recommendation not found')
    print(json.dumps(rows[0],indent=2,ensure_ascii=False))


def cmd_report(args):
    s=Settings.load(False); db=db_for(s)
    generate_recommendations(db,168 if args.weekly else 24)
    print(weekly_report_text(db) if args.weekly else daily_report_text(db))


def cmd_campaign_config(args):
    s=Settings.load(False); db=db_for(s)
    updates={}
    if args.category is not None: updates['category']=args.category.strip()
    if args.collections is not None: updates['target_collections']=','.join(sorted({x.strip().lower() for x in args.collections.split(',') if x.strip()}))
    if args.max_cycles is not None:
        if args.max_cycles < 0: raise ValueError('max_cycles cannot be negative')
        updates['max_cycles']=args.max_cycles
    if args.reset_cycles: updates['completed_cycles']=0
    if not updates:
        with db.connect() as con:
            row=con.execute('SELECT campaign_id,category,target_collections,max_cycles,completed_cycles FROM campaigns WHERE campaign_id=?',(args.campaign_id,)).fetchone()
        if not row: raise RuntimeError('Campaign not found')
        print(json.dumps(dict(row),indent=2)); return
    updates['updated_at']=utcnow(); cols=list(updates)
    with db.connect() as con:
        if not con.execute('SELECT 1 FROM campaigns WHERE campaign_id=?',(args.campaign_id,)).fetchone(): raise RuntimeError('Campaign not found')
        con.execute('UPDATE campaigns SET '+','.join(f'{k}=?' for k in cols)+' WHERE campaign_id=?',[updates[k] for k in cols]+[args.campaign_id])
    audit(db,'local-cli','campaign_config','campaign',args.campaign_id,**updates)
    print(json.dumps({'campaign_id':args.campaign_id,**updates},indent=2))


def cmd_production_bootstrap(args):
    s = Settings.load(False); db = db_for(s)
    explicit = tuple(x.strip() for x in (args.contents or '').split(',') if x.strip())
    tags = tuple(x.strip().lower() for x in (args.content_tags or '').split(',') if x.strip()) or ("production", "main_ads")
    spec = ProductionBootstrapSpec(
        campaign_id=args.campaign_id,
        name=args.name,
        collection_id=args.collection,
        content_prefix=args.content_prefix,
        explicit_content_ids=explicit,
        exclude_tags=args.exclude_tags,
        rotation=args.rotation,
        interval_minutes=args.interval_minutes,
        priority=args.priority,
        reuse_minutes=args.reuse_minutes,
        conflict_gap_minutes=args.conflict_gap_minutes,
        spread_minutes=args.spread_minutes,
        category=args.category,
        content_tags=tags,
        canary_campaign_id=args.canary_campaign,
        canary_collection_id=args.canary_collection,
        configure_canary=not args.no_canary,
    )
    result = bootstrap_production(db, s.timezone, spec)
    print("PRODUCTION BOOTSTRAP - SAFE PRE-ACTIVATION")
    print("=" * 88)
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    print("[OK] Production campaign is READY but INACTIVE. No Telegram send was performed.")


def cmd_go_live_readiness(args):
    s = Settings.load(False); db = db_for(s)
    problems = []
    warnings = []

    integrity = database_integrity(db)
    if not integrity.get("ok"):
        problems.append("database integrity check failed")

    validation = validate(db)
    if validation:
        problems.extend([f"validation: {x}" for x in validation])

    ready = production_readiness(db, args.campaign_id, expected_collection=args.collection)
    problems.extend([f"production: {x}" for x in ready.get("problems", [])])
    warnings.extend([f"production: {x}" for x in ready.get("warnings", [])])

    if ready.get("enabled") or ready.get("state") == "active":
        problems.append("production must be READY/inactive before guarded go-live")
    if str(ready.get("state") or "") != "ready":
        problems.append(f"production lifecycle must be ready; found {ready.get('state')}")
    if int(ready.get("active_queue_jobs") or 0) != 0:
        problems.append("production has active queue jobs before activation")
    if args.expected_destinations is not None and int(ready.get("selected") or 0) != int(args.expected_destinations):
        problems.append(f"expected {args.expected_destinations} destinations; found {ready.get('selected')}")
    variants = list(ready.get("variants") or [])
    if args.expected_variants is not None and len(variants) != int(args.expected_variants):
        problems.append(f"expected {args.expected_variants} variants; found {len(variants)}")
    if args.require_album_items is not None:
        bad = {k: int(v or 0) for k, v in (ready.get("media_counts") or {}).items() if int(v or 0) != int(args.require_album_items)}
        if bad:
            problems.append(f"variants do not all contain {args.require_album_items} media items: {bad}")

    delivery = ready.get("media_delivery") or {}
    # V4 supports native mixed destination delivery. Text-only groups receive the
    # caption from a compatible variant; photo groups receive the media group.
    if getattr(args, "require_photo_only", False) and int(delivery.get("text_destinations") or 0) != 0:
        problems.append(f"photo-only gate requested but {delivery.get('text_destinations')} text-mode destination(s) remain")

    canary = canary_queue_status(db, args.canary_campaign)
    if str(canary.get("status") or "") != "sent":
        problems.append(f"latest album canary is {canary.get('status') or 'missing'}, not sent")

    receipt_path = Path(args.visual_receipt)
    receipt = None
    if not receipt_path.exists():
        problems.append(f"visual canary receipt missing: {receipt_path}")
    else:
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            problems.append(f"visual canary receipt unreadable: {type(exc).__name__}")
    if receipt is not None:
        if str(receipt.get("confirmation") or "") != "ALBUM_OK":
            problems.append("visual canary receipt is not ALBUM_OK")
        if str(receipt.get("job_id") or "") != str(canary.get("id") or ""):
            problems.append("visual canary receipt does not match latest canary job")
        if bool(receipt.get("telegram_send_performed", False)):
            warnings.append("visual receipt indicates reconciliation performed a Telegram send")

    safety = _safety_controller(s, db).status()
    if safety.paused:
        problems.append(f"outbound safety is paused: {safety.reason or '-'}")

    with db.connect() as con:
        unresolved = con.execute(
            "SELECT COUNT(*) FROM queue WHERE campaign_id=? AND status IN ('pending','retry','deferred','processing','sending','uncertain')",
            (args.campaign_id,),
        ).fetchone()[0]
        global_unresolved_rows = con.execute(
            "SELECT id,campaign_id,status,group_id,content_id FROM queue WHERE status IN ('pending','retry','deferred','processing','sending','uncertain') ORDER BY id"
        ).fetchall()
        schedule = con.execute("SELECT * FROM campaign_schedules WHERE campaign_id=?", (args.campaign_id,)).fetchone()
    if int(unresolved or 0):
        problems.append(f"production has {int(unresolved)} unresolved queue job(s)")
    global_unresolved = [dict(r) for r in global_unresolved_rows]
    if global_unresolved:
        problems.append(f"system has {len(global_unresolved)} unresolved queue job(s) before go-live")
    if not schedule or not bool(schedule["enabled"]):
        problems.append("production schedule is missing or disabled")
    elif args.expected_interval_minutes is not None:
        expected_seconds = int(args.expected_interval_minutes) * 60
        if str(schedule["mode"] or "") != "interval" or int(schedule["interval_seconds"] or 0) != expected_seconds:
            problems.append(
                f"expected {args.expected_interval_minutes}-minute interval schedule; "
                f"found mode={schedule['mode']} interval_seconds={schedule['interval_seconds']}"
            )

    admin_configured = bool(s.admin_bot_enabled)
    if not admin_configured:
        if getattr(args, "require_admin_bot", False):
            problems.append("Telegram admin control bot is not configured")
        else:
            warnings.append("Telegram admin control bot is not configured")

    result = {
        "ok": not problems,
        "campaign_id": args.campaign_id,
        "production": ready,
        "canary": canary,
        "visual_receipt": {
            "path": str(receipt_path),
            "present": receipt is not None,
            "job_id": receipt.get("job_id") if isinstance(receipt, dict) else None,
            "confirmation": receipt.get("confirmation") if isinstance(receipt, dict) else None,
        },
        "database_integrity": integrity,
        "outbound_paused": bool(safety.paused),
        "admin_bot_configured": admin_configured,
        "schedule": dict(schedule) if schedule else None,
        "global_unresolved_queue": global_unresolved,
        "problems": problems,
        "warnings": warnings,
    }
    print(_json_text(result, machine_safe=True))
    if problems:
        raise SystemExit(2)


def cmd_production_readiness(args):
    s = Settings.load(False); db = db_for(s)
    result = production_readiness(db, args.campaign_id, expected_collection=args.collection)
    if getattr(args, "json_only", False):
        print(_json_text(result, machine_safe=True))
    else:
        print("PRODUCTION READINESS")
        print("=" * 88)
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    if not result.get("ok"):
        raise SystemExit(2)
    if not getattr(args, "json_only", False):
        print("[OK] Readiness checks passed; campaign remains under lifecycle/safety controls.")

def cmd_canary_status(args):
    s = Settings.load(False); db = db_for(s)
    result = canary_queue_status(db, args.campaign_id)
    print(_json_text(result, machine_safe=True))
    if not result.get("job_found"):
        raise SystemExit(2)

def cmd_canary_reconcile_sent(args):
    s = Settings.load(False); db = db_for(s)
    result = reconcile_visual_canary_sent(
        db,
        campaign_id=args.campaign_id,
        job_id=args.job_id,
        confirmation=args.confirmation,
        actor="local-visual-confirmation",
    )
    print(_json_text(result, machine_safe=True))


def cmd_album_delivery_plan(args):
    s = Settings.load(False); db = db_for(s)
    result = album_delivery_plan(db, args.campaign_id)
    print(_json_text(result, machine_safe=True))
    if not result.get("ok"):
        raise SystemExit(2)

def cmd_album_delivery_apply(args):
    s = Settings.load(False); db = db_for(s)
    result = apply_album_delivery_modes(db, args.campaign_id, confirmation=args.confirm)
    print(_json_text(result, machine_safe=True))

def build_parser():
    p=argparse.ArgumentParser(prog="smart-autoposter",description=f"Smart Auto Poster V{__version__}")
    sp=p.add_subparsers(dest="cmd",required=True)

    a=sp.add_parser("init"); a.set_defaults(func=cmd_init)
    a=sp.add_parser("import-config"); a.add_argument("--csv"); a.set_defaults(func=cmd_import)
    a=sp.add_parser("validate"); a.set_defaults(func=cmd_validate)
    a=sp.add_parser("scan"); a.set_defaults(func=cmd_scan)
    a=sp.add_parser("accounts-check"); a.set_defaults(func=cmd_accounts_check)
    a=sp.add_parser("login-account"); a.add_argument("account", choices=["primary","secondary"]); a.add_argument("--reset", action="store_true"); a.set_defaults(func=cmd_login_account)

    a=sp.add_parser("add-content"); a.add_argument("content_id"); a.add_argument("--caption"); a.add_argument("--caption-file"); a.add_argument("--media",nargs="*"); a.set_defaults(func=cmd_add_content)
    a=sp.add_parser("contents"); a.set_defaults(func=cmd_contents)
    a=sp.add_parser("import-content"); a.add_argument("--keep-source",action="store_true"); a.set_defaults(func=cmd_import_content)
    a=sp.add_parser("content-audit"); a.set_defaults(func=cmd_content_audit)

    a=sp.add_parser("add-campaign"); a.add_argument("campaign_id"); a.add_argument("name"); a.add_argument("content_id"); a.add_argument("--priority",type=int,default=50); a.add_argument("--tags",default=""); a.add_argument("--exclude-tags",default=""); a.add_argument("--collections",default=""); a.add_argument("--category",default=""); a.add_argument("--max-cycles",type=int,default=0); a.add_argument("--rotation",choices=["sequential","random","least_recent","weighted"],default="sequential"); a.add_argument("--reuse-minutes",type=float,default=0); a.add_argument("--allow-protected",action="store_true"); a.add_argument("--conflict-gap-minutes",type=float,default=0); a.add_argument("--spread-minutes",type=float,default=0); a.add_argument("--start-at"); a.add_argument("--end-at"); a.add_argument("--min-interval",type=int,default=0); a.set_defaults(func=cmd_add_campaign)
    a=sp.add_parser("campaigns"); a.set_defaults(func=cmd_campaigns)
    a=sp.add_parser("campaign-content"); a.add_argument("campaign_id"); g=a.add_mutually_exclusive_group(); g.add_argument("--add"); g.add_argument("--remove"); a.add_argument("--position",type=int); a.add_argument("--weight",type=int,default=1); a.set_defaults(func=cmd_campaign_content)
    a=sp.add_parser("preview"); a.add_argument("campaign_id"); a.set_defaults(func=cmd_campaign_preview)
    a=sp.add_parser("clone-campaign"); a.add_argument("source_campaign"); a.add_argument("new_campaign"); a.add_argument("--name"); a.set_defaults(func=cmd_campaign_clone)
    a=sp.add_parser("campaign-wizard"); a.set_defaults(func=cmd_campaign_wizard)
    a=sp.add_parser("production-bootstrap"); a.add_argument("--campaign-id",default="main_production_01"); a.add_argument("--name",default="Main Production Campaign"); a.add_argument("--collection",default="all_approved"); a.add_argument("--contents",help="comma-separated exact content IDs; default discovers enabled content by prefix"); a.add_argument("--content-prefix",default="main_ad_"); a.add_argument("--exclude-tags",default="live_test"); a.add_argument("--rotation",choices=["sequential","random","least_recent","weighted"],default="least_recent"); a.add_argument("--interval-minutes",type=int,default=240); a.add_argument("--priority",type=int,default=100); a.add_argument("--reuse-minutes",type=int,default=1440); a.add_argument("--conflict-gap-minutes",type=int,default=60); a.add_argument("--spread-minutes",type=int,default=0); a.add_argument("--category",default="production"); a.add_argument("--content-tags",default="production,main_ads"); a.add_argument("--canary-campaign",default="album_canary_01"); a.add_argument("--canary-collection",default="live_test"); a.add_argument("--no-canary",action="store_true"); a.set_defaults(func=cmd_production_bootstrap)
    a=sp.add_parser("production-readiness"); a.add_argument("campaign_id",nargs="?",default="main_production_01"); a.add_argument("--collection",default="all_approved"); a.add_argument("--json-only",action="store_true"); a.set_defaults(func=cmd_production_readiness)
    a=sp.add_parser("go-live-readiness"); a.add_argument("campaign_id",nargs="?",default="main_production_01"); a.add_argument("--collection",default="all_approved"); a.add_argument("--canary-campaign",default="album_canary_01"); a.add_argument("--visual-receipt",default="runtime/canary/album_canary_visual_ok.json"); a.add_argument("--expected-destinations",type=int); a.add_argument("--expected-variants",type=int); a.add_argument("--require-album-items",type=int); a.add_argument("--expected-interval-minutes",type=int); a.add_argument("--require-admin-bot",action="store_true"); a.add_argument("--require-photo-only",action="store_true",help="legacy optional gate; V4 mixed text/photo delivery is supported by default"); a.set_defaults(func=cmd_go_live_readiness)
    a=sp.add_parser("canary-status"); a.add_argument("--campaign-id",default="album_canary_01"); a.set_defaults(func=cmd_canary_status)
    a=sp.add_parser("canary-reconcile-sent"); a.add_argument("--campaign-id",default="album_canary_01"); a.add_argument("--job-id",type=int,required=True); a.add_argument("--confirmation",required=True); a.set_defaults(func=cmd_canary_reconcile_sent)
    a=sp.add_parser("album-delivery-plan"); a.add_argument("--campaign-id",default="main_production_01"); a.set_defaults(func=cmd_album_delivery_plan)
    a=sp.add_parser("album-delivery-apply"); a.add_argument("--campaign-id",default="main_production_01"); a.add_argument("--confirm",required=True); a.set_defaults(func=cmd_album_delivery_apply)
    a=sp.add_parser("campaign"); a.add_argument("campaign_id"); g=a.add_mutually_exclusive_group(required=True); g.add_argument("--enable",dest="enabled",action="store_true"); g.add_argument("--disable",dest="enabled",action="store_false"); a.set_defaults(func=cmd_campaign_toggle)

    a=sp.add_parser("schedule"); a.add_argument("campaign_id"); g=a.add_mutually_exclusive_group(required=True); g.add_argument("--interval-minutes",type=float); g.add_argument("--daily-times"); g.add_argument("--once-at",help="ISO local/offset datetime for one-off run"); g.add_argument("--off",action="store_true"); a.add_argument("--days",help="comma-separated mon,tue,...; default all days"); a.add_argument("--timezone"); a.add_argument("--start-in-minutes",type=float); a.set_defaults(func=cmd_schedule)
    a=sp.add_parser("schedule-rearm"); a.add_argument("campaign_id"); a.set_defaults(func=cmd_schedule_rearm)
    a=sp.add_parser("scheduler"); a.set_defaults(func=cmd_scheduler)
    a=sp.add_parser("simulate"); a.add_argument("--hours",type=int,default=24); a.add_argument("--campaign"); a.add_argument("--include-inactive",action="store_true"); a.set_defaults(func=cmd_simulate)

    a=sp.add_parser("enqueue"); a.add_argument("campaign_id"); a.add_argument("--dry-run",action="store_true"); a.add_argument("--run-key"); a.set_defaults(func=cmd_enqueue)
    a=sp.add_parser("post-now"); a.add_argument("campaign_id"); a.add_argument("--dry-run",action="store_true"); a.set_defaults(func=cmd_post_now)

    a=sp.add_parser("destinations"); a.add_argument("--review",action="store_true"); a.add_argument("--enabled",action="store_true"); a.add_argument("--disabled",action="store_true"); a.add_argument("--search"); a.add_argument("--limit",type=int,default=100); a.set_defaults(func=cmd_destinations)
    a=sp.add_parser("destination"); a.add_argument("group_id"); a.add_argument("--approve",action="store_true"); a.add_argument("--mode",choices=["photo","text","review","disabled"]); a.add_argument("--account",choices=["primary","secondary","both"]); a.add_argument("--topic"); a.add_argument("--min-interval",type=int); a.add_argument("--quiet-start"); a.add_argument("--quiet-end"); a.add_argument("--clear-quiet",action="store_true"); a.add_argument("--add-tag",action="append"); a.add_argument("--remove-tag",action="append"); a.add_argument("--note"); pg=a.add_mutually_exclusive_group(); pg.add_argument("--protect",dest="protect",action="store_true"); pg.add_argument("--unprotect",dest="protect",action="store_false"); ng=a.add_mutually_exclusive_group(); ng.add_argument("--never-auto-post",dest="never_auto_post",action="store_true"); ng.add_argument("--allow-auto-post",dest="never_auto_post",action="store_false"); eg=a.add_mutually_exclusive_group(); eg.add_argument("--enable",dest="enable",action="store_true"); eg.add_argument("--disable",dest="enable",action="store_false"); a.set_defaults(enable=None,protect=None,never_auto_post=None,func=cmd_destination)

    a=sp.add_parser("queue"); a.add_argument("--status",choices=["pending","retry","deferred","processing","sending","sent","failed","uncertain","cancelled","expired","quarantined"]); a.add_argument("--campaign"); a.add_argument("--limit",type=int,default=50); a.set_defaults(func=cmd_queue)
    a=sp.add_parser("progress"); a.add_argument("--campaign"); a.add_argument("--run-key"); a.add_argument("--limit",type=int,default=40); a.add_argument("--json-only",action="store_true"); a.add_argument("--watch",action="store_true"); a.add_argument("--interval",type=float,default=5.0); a.set_defaults(func=cmd_progress)
    a=sp.add_parser("mission-control"); a.add_argument("--campaign",default="main_production_01"); a.add_argument("--limit",type=int,default=12); a.add_argument("--json-only",action="store_true"); a.set_defaults(func=cmd_mission_control)
    a=sp.add_parser("queue-hygiene"); a.add_argument("--campaign"); a.add_argument("--apply",action="store_true"); a.set_defaults(func=cmd_queue_hygiene)
    a=sp.add_parser("v5-readiness"); a.add_argument("--campaign",default="main_production_01"); a.add_argument("--json-only",action="store_true"); a.set_defaults(func=cmd_v5_readiness)
    a=sp.add_parser("v6-control"); a.add_argument("--campaign",default="main_production_01"); a.add_argument("--json-only",action="store_true"); a.set_defaults(func=cmd_v6_control)
    a=sp.add_parser("v6-intelligence"); a.add_argument("--limit",type=int,default=50); a.set_defaults(func=cmd_v6_intelligence)
    a=sp.add_parser("v6-confidence"); a.add_argument("--campaign"); a.add_argument("--limit",type=int,default=100); a.set_defaults(func=cmd_v6_confidence)
    a=sp.add_parser("v6-plan"); a.add_argument("--campaign",default="main_production_01"); a.set_defaults(func=cmd_v6_plan)
    a=sp.add_parser("v6-recovery"); a.set_defaults(func=cmd_v6_recovery)
    a=sp.add_parser("job-timeline"); a.add_argument("job_id",type=int); a.add_argument("--limit",type=int,default=100); a.add_argument("--json-only",action="store_true"); a.set_defaults(func=cmd_job_timeline)
    a=sp.add_parser("job"); a.add_argument("job_id",type=int); g=a.add_mutually_exclusive_group(); g.add_argument("--retry",action="store_true"); g.add_argument("--cancel",action="store_true"); g.add_argument("--mark-sent",action="store_true"); g.add_argument("--defer-minutes",type=int); a.set_defaults(func=cmd_job)
    a=sp.add_parser("uncertain-list"); a.add_argument("--campaign"); a.add_argument("--limit",type=int,default=100); a.set_defaults(func=cmd_uncertain_list)
    a=sp.add_parser("uncertain-reconcile"); a.add_argument("job_id",type=int); a.add_argument("outcome",choices=["sent","not_sent","unresolved"]); a.add_argument("--evidence",required=True); a.add_argument("--confirmation"); a.set_defaults(func=cmd_uncertain_reconcile)
    a=sp.add_parser("uncertain-scan"); a.add_argument("--campaign"); a.add_argument("--window-minutes",type=int,default=20); a.add_argument("--diagnostic-window-minutes",type=int,default=120); a.add_argument("--limit",type=int,default=100); a.add_argument("--apply-sent",action="store_true"); a.set_defaults(func=cmd_uncertain_scan)
    a=sp.add_parser("reconciliation-history"); a.add_argument("--job-id",type=int); a.add_argument("--limit",type=int,default=100); a.set_defaults(func=cmd_reconciliation_history)
    a=sp.add_parser("queue-summary"); a.add_argument("--limit",type=int,default=20); a.set_defaults(func=cmd_queue_summary)
    a=sp.add_parser("retry-failed"); a.add_argument("--campaign"); a.set_defaults(func=cmd_retry_failed)
    a=sp.add_parser("delivery-intelligence"); a.add_argument("--hours",type=int,default=168); a.add_argument("--campaign"); a.add_argument("--limit",type=int,default=20); a.add_argument("--json-only",action="store_true"); a.set_defaults(func=cmd_delivery_intelligence)
    a=sp.add_parser("delivery-recovery"); a.add_argument("--campaign"); a.add_argument("--apply",action="store_true"); a.set_defaults(func=cmd_delivery_recovery)

    a=sp.add_parser("status"); a.set_defaults(func=cmd_status)
    a=sp.add_parser("daily-summary"); a.add_argument("--hours",type=int,default=24); a.set_defaults(func=cmd_daily_summary)
    a=sp.add_parser("live-coverage-run"); a.add_argument("--campaign",default="main_production_01"); a.add_argument("--poll",type=int,default=2); a.add_argument("--run-key"); a.add_argument("--no-evidence-scan",action="store_true"); a.set_defaults(func=cmd_live_coverage)
    a=sp.add_parser("live-coverage-status"); a.add_argument("--run-key"); a.add_argument("--width",type=int,default=100); a.add_argument("--export",action="store_true"); a.set_defaults(func=cmd_live_coverage_status)
    a=sp.add_parser("health"); a.set_defaults(func=cmd_health)
    a=sp.add_parser("worker"); a.add_argument("--once",action="store_true"); a.add_argument("--poll",type=int,default=5); a.set_defaults(func=cmd_worker)
    a=sp.add_parser("run"); a.add_argument("--poll",type=int,default=5); a.add_argument("--scheduler-poll",type=int,default=15); a.set_defaults(func=cmd_run)
    a=sp.add_parser("safety-status"); a.set_defaults(func=cmd_safety_status)
    a=sp.add_parser("pause"); a.add_argument("--minutes",type=int); a.add_argument("--reason"); a.set_defaults(func=cmd_pause)
    a=sp.add_parser("resume"); a.set_defaults(func=cmd_resume)
    a=sp.add_parser("backup"); a.set_defaults(func=cmd_backup)
    a=sp.add_parser("export-destinations"); a.add_argument("--output",default="exports/destinations_latest.csv"); a.set_defaults(func=cmd_export)

    # V2.4 autonomous operations / Telegram control centre
    a=sp.add_parser("campaign-state"); a.add_argument("campaign_id"); a.add_argument("state",choices=["draft","ready","active","paused","archived"]); a.set_defaults(func=cmd_campaign_state)
    a=sp.add_parser("content-state"); a.add_argument("content_id"); a.add_argument("state",choices=["ready","disabled","archived","rejected"]); a.set_defaults(func=cmd_content_state)
    a=sp.add_parser("content-tags"); a.add_argument("content_id"); a.add_argument("--add-tag",action="append"); a.add_argument("--remove-tag",action="append"); a.set_defaults(func=cmd_content_tags)
    a=sp.add_parser("bulk-destinations"); a.add_argument("tag"); eg=a.add_mutually_exclusive_group(); eg.add_argument("--enable",dest="enable",action="store_true"); eg.add_argument("--disable",dest="enable",action="store_false"); pg=a.add_mutually_exclusive_group(); pg.add_argument("--protect",dest="protect",action="store_true"); pg.add_argument("--unprotect",dest="protect",action="store_false"); ng=a.add_mutually_exclusive_group(); ng.add_argument("--never-auto-post",dest="never_auto_post",action="store_true"); ng.add_argument("--allow-auto-post",dest="never_auto_post",action="store_false"); a.add_argument("--add-tag"); a.add_argument("--remove-tag"); a.set_defaults(enable=None,protect=None,never_auto_post=None,func=cmd_bulk_destinations)
    a=sp.add_parser("cancel-campaign-jobs"); a.add_argument("campaign_id"); a.set_defaults(func=cmd_cancel_campaign_jobs)
    a=sp.add_parser("queue-capacity"); a.set_defaults(func=cmd_queue_capacity)
    a=sp.add_parser("audit-log"); a.add_argument("--limit",type=int,default=50); a.set_defaults(func=cmd_audit_log)
    a=sp.add_parser("watchdog"); a.add_argument("--require",action="append"); a.add_argument("--json-only",action="store_true"); a.set_defaults(func=cmd_watchdog)
    a=sp.add_parser("integrity"); a.set_defaults(func=cmd_integrity)
    a=sp.add_parser("vacuum"); a.set_defaults(func=cmd_vacuum)
    a=sp.add_parser("diagnostics"); a.add_argument("--no-logs",action="store_true"); a.set_defaults(func=cmd_diagnostics)
    a=sp.add_parser("cache-status"); a.set_defaults(func=cmd_cache_status)
    a=sp.add_parser("clear-cache"); a.add_argument("--account",choices=["primary","secondary"]); a.set_defaults(func=cmd_clear_cache)
    a=sp.add_parser("maintenance"); a.set_defaults(func=cmd_maintenance)
    a=sp.add_parser("admin-bot"); a.set_defaults(func=cmd_admin_bot)
    a=sp.add_parser("admin-status"); a.set_defaults(func=cmd_admin_status)
    a=sp.add_parser("admin-probe"); a.set_defaults(func=cmd_admin_probe)
    a=sp.add_parser("templates"); a.set_defaults(func=cmd_templates)
    a=sp.add_parser("create-template"); a.add_argument("template",choices=["evergreen","daily","announcement","one_off","rotating_ads"]); a.add_argument("campaign_id"); a.add_argument("name"); a.add_argument("content_id"); a.add_argument("--tags",default=""); a.add_argument("--exclude-tags",default=""); a.set_defaults(func=cmd_create_template)
    a=sp.add_parser("campaign-gap"); a.add_argument("campaign_id"); a.add_argument("related_campaign"); a.add_argument("--minutes",type=float,default=60); a.add_argument("--both",action="store_true"); a.add_argument("--remove",action="store_true"); a.set_defaults(func=cmd_campaign_gap)
    a=sp.add_parser("analytics"); a.add_argument("--hours",type=int,default=168); a.set_defaults(func=cmd_analytics)
    a=sp.add_parser("record-update"); a.add_argument("--version",required=True); a.add_argument("--previous"); a.add_argument("--status",default="applied"); a.add_argument("--package"); a.add_argument("--details"); a.set_defaults(func=cmd_record_update)
    a=sp.add_parser("update-history"); a.add_argument("--limit",type=int,default=50); a.set_defaults(func=cmd_update_history)

    # V3.0 collections, rules, recommendations and reports
    a=sp.add_parser("collection"); a.add_argument("collection_id"); a.add_argument("--name"); a.add_argument("--include-tags"); a.add_argument("--exclude-tags"); a.add_argument("--access",choices=["any","primary","secondary","both"],default="any"); a.add_argument("--mode",choices=["any","photo","text"],default="any"); a.add_argument("--forum-only",action="store_true"); a.add_argument("--include-protected",action="store_true"); a.add_argument("--disable",action="store_true"); a.add_argument("--delete",action="store_true"); a.set_defaults(func=cmd_collection)
    a=sp.add_parser("collections"); a.add_argument("--enabled",action="store_true"); a.add_argument("--preview",action="store_true"); a.set_defaults(func=cmd_collections)
    a=sp.add_parser("rule"); a.add_argument("rule_id"); a.add_argument("--name"); a.add_argument("--condition",required=True,help="JSON conditions"); a.add_argument("--action",required=True,help="JSON actions"); a.add_argument("--priority",type=int,default=100); a.add_argument("--disable",action="store_true"); a.set_defaults(func=cmd_rule)
    a=sp.add_parser("rules"); a.add_argument("--enabled",action="store_true"); a.set_defaults(func=cmd_rules)
    a=sp.add_parser("rule-preview"); a.add_argument("rule_id"); a.set_defaults(func=cmd_rule_preview)
    a=sp.add_parser("apply-rules"); a.add_argument("--rule"); a.add_argument("--dry-run",action="store_true"); a.set_defaults(func=cmd_apply_rules)
    a=sp.add_parser("recommendations"); a.add_argument("--generate",action="store_true"); a.add_argument("--hours",type=int,default=168); a.add_argument("--status",choices=["open","dismissed","applied"],default="open"); a.add_argument("--limit",type=int,default=50); a.set_defaults(func=cmd_recommendations)
    a=sp.add_parser("recommendation"); a.add_argument("recommendation_id"); g=a.add_mutually_exclusive_group(); g.add_argument("--apply",action="store_true"); g.add_argument("--dismiss",action="store_true"); a.set_defaults(func=cmd_recommendation)
    a=sp.add_parser("report"); a.add_argument("--weekly",action="store_true"); a.set_defaults(func=cmd_report)
    a=sp.add_parser("campaign-config"); a.add_argument("campaign_id"); a.add_argument("--category"); a.add_argument("--collections"); a.add_argument("--max-cycles",type=int); a.add_argument("--reset-cycles",action="store_true"); a.set_defaults(func=cmd_campaign_config)
    return p


def main():
    args=build_parser().parse_args()
    try:
        args.func(args)
    except (RuntimeError,ValueError,FileNotFoundError) as exc:
        print(f"[ERROR] {exc}")
        raise SystemExit(2)


if __name__ == "__main__": main()
