from __future__ import annotations

import json
import os
import shutil
import sqlite3
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .db import Database, utcnow
from .operations import operational_summary, expire_ineligible_jobs
from .redaction import redact_text
from .watchdog import Watchdog

SECRET_NAMES = {".env", "telegram_api_hash", "admin_bot_token"}


def database_integrity(db: Database) -> dict:
    with db.connect() as con:
        rows = [r[0] for r in con.execute("PRAGMA integrity_check").fetchall()]
        fk = [tuple(r) for r in con.execute("PRAGMA foreign_key_check").fetchall()]
    return {"integrity": rows, "foreign_key_errors": fk, "ok": rows == ["ok"] and not fk}


def vacuum_database(db: Database):
    # VACUUM cannot run within an open transaction context manager.
    con = sqlite3.connect(db.path, timeout=30)
    try:
        con.execute("PRAGMA busy_timeout=30000")
        con.execute("VACUUM")
    finally:
        con.close()
    return db.path


def media_cache_status(cache_dir: Path) -> dict:
    cache_dir = Path(cache_dir)
    result = {}
    for account in ("primary", "secondary"):
        path = cache_dir / f"telegram_media_cache_v2_{account}.json"
        items = 0
        valid = True
        error = None
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                items = len(data.get("items", {})) if isinstance(data, dict) else 0
            except Exception as exc:
                valid = False; error = str(exc)
        result[account] = {"path": str(path), "exists": path.exists(), "items": items, "valid": valid, "error": error}
    return result


def clear_media_cache(cache_dir: Path, account: str | None = None) -> list[str]:
    cache_dir = Path(cache_dir)
    accounts = [account] if account else ["primary", "secondary"]
    removed = []
    for key in accounts:
        path = cache_dir / f"telegram_media_cache_v2_{key}.json"
        if path.exists():
            path.unlink()
            removed.append(str(path))
    return removed


def cleanup_storage(*, log_dir: Path, backup_dir: Path, diagnostics_dir: Path, log_days: int, backup_keep: int, diagnostic_days: int = 30) -> dict:
    now = datetime.now(timezone.utc).timestamp()
    result = {"logs": 0, "diagnostics": 0, "backups": 0}
    for p in Path(log_dir).glob("*"):
        if p.is_file() and now - p.stat().st_mtime > log_days * 86400:
            try: p.unlink(); result["logs"] += 1
            except OSError: pass
    for p in Path(diagnostics_dir).glob("*"):
        if p.is_file() and now - p.stat().st_mtime > diagnostic_days * 86400:
            try: p.unlink(); result["diagnostics"] += 1
            except OSError: pass
    db_backups = sorted(Path(backup_dir).glob("*.sqlite3"), key=lambda x: x.stat().st_mtime, reverse=True)
    for p in db_backups[max(1, backup_keep):]:
        try: p.unlink(); result["backups"] += 1
        except OSError: pass
    return result


def prune_database(db: Database, *, event_days: int = 90, notification_days: int = 30, queue_days: int = 180) -> dict:
    events_cutoff = (datetime.now(timezone.utc) - timedelta(days=max(7, event_days))).isoformat(timespec="seconds")
    notif_cutoff = (datetime.now(timezone.utc) - timedelta(days=max(7, notification_days))).isoformat(timespec="seconds")
    queue_cutoff = (datetime.now(timezone.utc) - timedelta(days=max(7, queue_days))).isoformat(timespec="seconds")
    expired_now = expire_ineligible_jobs(db)
    with db.connect() as con:
        e = con.execute("DELETE FROM events WHERE created_at<? AND severity IN ('INFO','WARNING')", (events_cutoff,)).rowcount
        n = con.execute("DELETE FROM notifications WHERE created_at<? AND status IN ('sent','failed')", (notif_cutoff,)).rowcount
        # Preserve failure/uncertain evidence longer; prune only safely resolved history.
        q = con.execute("DELETE FROM queue WHERE updated_at<? AND status IN ('sent','cancelled','expired')", (queue_cutoff,)).rowcount
    return {"events_deleted": e, "notifications_deleted": n, "queue_deleted": q, "jobs_expired_now": expired_now}


def _safe_json(path: Path, obj):
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def generate_diagnostics(db: Database, settings, *, include_logs: bool = True) -> Path:
    settings.ensure_dirs()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    work = settings.diagnostics_dir / f"diagnostics_{stamp}"
    if work.exists(): shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)

    with db.connect() as con:
        meta = {r["key"]: r["value"] for r in con.execute("SELECT key,value FROM meta ORDER BY key").fetchall() if "secret" not in r["key"].lower()}
        accounts = [dict(r) for r in con.execute("SELECT account_key,enabled,authorized,identity,cooldown_until,consecutive_failures,last_error,last_success_at,last_failure_at,last_heartbeat_at,health_score,updated_at FROM accounts ORDER BY account_key").fetchall()]
        queue = [dict(r) for r in con.execute("SELECT status,COUNT(*) n FROM queue GROUP BY status ORDER BY status").fetchall()]
        recent_errors = [dict(r) for r in con.execute("SELECT id,created_at,severity,event_type,account_key,group_id,campaign_id,message FROM events WHERE severity IN ('ERROR','CRITICAL','WARNING') ORDER BY id DESC LIMIT 100").fetchall()]
        campaigns = [dict(r) for r in con.execute("SELECT campaign_id,name,enabled,lifecycle_state,priority,rotation_mode,start_at,end_at,updated_at FROM campaigns ORDER BY campaign_id").fetchall()]
        destinations = [dict(r) for r in con.execute("SELECT group_id,group_name,enabled,needs_review,primary_access,secondary_access,preferred_account,mode,protected,never_auto_post,consecutive_failures,quarantine_until,updated_at FROM destinations ORDER BY group_name").fetchall()]

    _safe_json(work / "system_status.json", operational_summary(db, 24))
    _safe_json(work / "database_integrity.json", database_integrity(db))
    _safe_json(work / "meta.json", meta)
    _safe_json(work / "accounts.json", accounts)
    _safe_json(work / "queue_summary.json", queue)
    _safe_json(work / "recent_errors.json", recent_errors)
    _safe_json(work / "campaigns.json", campaigns)
    _safe_json(work / "destinations.json", destinations)
    _safe_json(work / "heartbeats.json", Watchdog(db, stale_seconds=settings.heartbeat_stale_seconds).snapshot())
    _safe_json(work / "media_cache.json", media_cache_status(settings.media_cache_dir))

    version = Path("VERSION.txt")
    if version.exists(): shutil.copy2(version, work / "VERSION.txt")
    build = Path("BUILD_REPORT.txt")
    if build.exists(): shutil.copy2(build, work / "BUILD_REPORT.txt")

    if include_logs:
        logs_out = work / "logs"; logs_out.mkdir(exist_ok=True)
        logs = sorted(Path(settings.log_dir).glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)[:5]
        for p in logs:
            # Redact again at bundle time even though runtime logging already avoids secrets.
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
                (logs_out / p.name).write_text(redact_text(text), encoding="utf-8")
            except Exception:
                # If a log cannot be safely read/redacted, omit it rather than copying raw bytes.
                pass

    note = (
        "SAFE DIAGNOSTIC BUNDLE\n"
        "Excluded: .env, API hash, bot token, Telegram .session files, login codes/passwords.\n"
        "This bundle contains operational metadata, destination names/IDs, campaign IDs and recent error messages.\n"
    )
    (work / "README.txt").write_text(note, encoding="utf-8")

    zip_path = settings.diagnostics_dir / f"Smart_Auto_Poster_Diagnostics_{stamp}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for p in work.rglob("*"):
            if p.is_file(): z.write(p, p.relative_to(work))
    shutil.rmtree(work, ignore_errors=True)
    return zip_path
