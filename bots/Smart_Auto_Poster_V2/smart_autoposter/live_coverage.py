from __future__ import annotations

import asyncio
import csv
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .core import _eligible_destinations, enqueue_campaign
from .db import Database, utcnow

ACTIVE = {"pending", "retry", "deferred", "processing", "sending", "uncertain"}
TERMINAL = {"sent", "failed", "cancelled", "expired", "quarantined"}


def _dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        out = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return out if out.tzinfo else out.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def ensure_schema(db: Database) -> None:
    with db.connect() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS live_coverage_runs(
                run_key TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'created',
                target_count INTEGER NOT NULL DEFAULT 0,
                sent_count INTEGER NOT NULL DEFAULT 0,
                failed_count INTEGER NOT NULL DEFAULT 0,
                blocked_count INTEGER NOT NULL DEFAULT 0,
                deferred_count INTEGER NOT NULL DEFAULT 0,
                original_campaign_enabled INTEGER,
                original_campaign_state TEXT,
                original_schedule_enabled INTEGER,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                report_json TEXT,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS live_coverage_targets(
                run_key TEXT NOT NULL,
                group_id INTEGER NOT NULL,
                group_name TEXT NOT NULL,
                queue_id INTEGER,
                state TEXT NOT NULL DEFAULT 'planned',
                attempts INTEGER NOT NULL DEFAULT 0,
                pass_no INTEGER NOT NULL DEFAULT 1,
                reason TEXT,
                error_kind TEXT,
                last_error TEXT,
                account_key TEXT,
                content_id TEXT,
                due_at TEXT,
                sent_at TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(run_key,group_id)
            );
            CREATE INDEX IF NOT EXISTS idx_live_coverage_targets_state ON live_coverage_targets(run_key,state);
            """
        )


def _failure_help(kind: str | None, detail: str | None = None) -> str:
    k = str(kind or "unknown")
    mapping = {
        "slow_mode": "Telegram SlowMode: deferred to its next safe time and retried later in the same run.",
        "flood_wait": "Telegram FloodWait/account pacing: wait for Telegram's retry time, then retry the same obligation.",
        "predictive_timing": "Known timing window: intentionally deferred before contacting Telegram.",
        "quiet_hours": "Destination quiet hours: wait until the configured quiet period ends.",
        "media_forbidden": "Selected account cannot send media here; try another authorised account or learned text fallback.",
        "text_forbidden": "Selected account cannot send text here; try another authorised account or compatible photo fallback.",
        "no_supported_format": "No authorised account has a supported delivery format for this group. Permissions/configuration must change.",
        "no_compatible_fallback": "Campaign has no content compatible with the format Telegram allows for this destination.",
        "no_authorized_account": "No authorised Telegram account currently has usable access to this destination.",
        "account_disabled": "Accessible account is disabled/unhealthy; account recovery or alternate-account routing is required.",
        "ChannelPrivateError": "Account no longer has access to the group/channel. Rescan membership/access before retrying.",
        "ChatWriteForbiddenError": "Telegram says posting is forbidden for this account. Check membership/posting rights.",
        "ChatSendMediaForbiddenError": "Telegram blocks media in this group. Use another account or a compatible text variant.",
        "ChatSendPhotosForbiddenError": "Telegram blocks photos in this group. Use another account or compatible text content.",
        "UserBannedInChannelError": "The selected account is banned/restricted in this destination.",
        "content_incompatible": "No compatible content can currently be selected for this destination mode.",
        "send_timeout_uncertain": "Telegram acknowledgement was lost after send began. Do not retry until delivery evidence is reconciled.",
        "uncertain_telegram_ack": "Telegram acknowledgement is ambiguous. Evidence reconciliation is required before any retry.",
        "interrupted_send": "Runtime stopped after send began. Verify Telegram history before another delivery.",
    }
    return mapping.get(k, (detail or "Unclassified delivery failure; inspect job timeline and Telegram error details.")[:500])


def _snapshot(db: Database, run_key: str) -> dict[str, Any]:
    ensure_schema(db)
    with db.connect() as con:
        run = con.execute("SELECT * FROM live_coverage_runs WHERE run_key=?", (run_key,)).fetchone()
        if not run:
            raise RuntimeError(f"Unknown live coverage run: {run_key}")
        rows = [dict(r) for r in con.execute("SELECT * FROM live_coverage_targets WHERE run_key=? ORDER BY group_name COLLATE NOCASE,group_id", (run_key,))]
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["state"]] = counts.get(r["state"], 0) + 1
    target_count = len(rows)
    sent = counts.get("sent", 0)
    return {
        "run": dict(run), "targets": rows, "counts": counts, "target_count": target_count,
        "sent_count": sent, "remaining": max(0, target_count - sent),
        "coverage_percent": 100 if target_count == 0 else int(round(100 * sent / target_count)),
    }


def _sync_targets(db: Database, run_key: str) -> dict[str, Any]:
    now = utcnow()
    with db.connect() as con:
        targets = con.execute("SELECT group_id,queue_id,state FROM live_coverage_targets WHERE run_key=?", (run_key,)).fetchall()
        for t in targets:
            q = None
            if t["queue_id"]:
                q = con.execute("SELECT * FROM queue WHERE id=?", (t["queue_id"],)).fetchone()
            if q is None:
                q = con.execute("SELECT * FROM queue WHERE run_key=? AND group_id=? ORDER BY id DESC LIMIT 1", (run_key, t["group_id"])).fetchone()
            if not q:
                continue
            status = q["status"]
            if status == "sent": state = "sent"
            elif status in {"pending", "processing", "sending"}: state = status
            elif status in {"retry", "deferred"}: state = status
            elif status == "uncertain": state = "blocked_uncertain"
            elif status in {"failed", "quarantined"}: state = "failed"
            elif status in {"cancelled", "expired"}: state = status
            else: state = status
            con.execute(
                """UPDATE live_coverage_targets SET queue_id=?,state=?,attempts=?,pass_no=?,reason=?,error_kind=?,last_error=?,
                   account_key=?,content_id=?,due_at=?,sent_at=?,updated_at=? WHERE run_key=? AND group_id=?""",
                (q["id"], state, int(q["attempts"] or 0), int(q["pass_no"] or 1), _failure_help(q["error_kind"], q["last_error"]) if state in {"failed","blocked_uncertain","retry","deferred"} else None,
                 q["error_kind"], q["last_error"], q["account_key"], q["content_id"], q["due_at"], q["updated_at"] if status == "sent" else None,
                 now, run_key, t["group_id"]),
            )
        counts = {r["state"]: int(r["n"]) for r in con.execute("SELECT state,COUNT(*) n FROM live_coverage_targets WHERE run_key=? GROUP BY state", (run_key,))}
        con.execute(
            """UPDATE live_coverage_runs SET sent_count=?,failed_count=?,blocked_count=?,deferred_count=?,updated_at=? WHERE run_key=?""",
            (counts.get("sent",0), counts.get("failed",0), counts.get("blocked_uncertain",0)+counts.get("blocked_existing",0),
             counts.get("deferred",0)+counts.get("retry",0), now, run_key),
        )
    return _snapshot(db, run_key)


def _retire_safe_old_rows(db: Database, campaign_id: str, target_ids: set[int]) -> list[int]:
    """Retire only retry-safe old obligations from this same campaign.

    UNCERTAIN/SENDING/PROCESSING are never touched. Other campaigns are never touched.
    """
    if not target_ids:
        return []
    now = utcnow(); retired: list[int] = []
    with db.connect() as con:
        qmarks = ",".join("?" for _ in target_ids)
        rows = con.execute(
            f"""SELECT id,status,group_id FROM queue WHERE campaign_id=? AND group_id IN ({qmarks})
                AND status IN ('pending','retry','deferred') ORDER BY id""",
            (campaign_id, *sorted(target_ids)),
        ).fetchall()
        for r in rows:
            con.execute(
                """UPDATE queue SET status='cancelled',error_kind='coverage_superseded',
                   last_error='retired before explicit full-coverage live run; known non-inflight obligation',
                   resolved_at=?,phase='cancelled',phase_percent=100,
                   phase_detail='superseded by explicit full-coverage live run',phase_updated_at=?,updated_at=?
                   WHERE id=? AND status IN ('pending','retry','deferred')""",
                (now, now, now, r["id"]),
            )
            retired.append(int(r["id"]))
    return retired


def prepare_run(db: Database, campaign_id: str, *, run_key: str | None = None) -> dict[str, Any]:
    ensure_schema(db)
    run_key = run_key or f"coverage:{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    now = utcnow()
    with db.connect() as con:
        if con.execute("SELECT 1 FROM live_coverage_runs WHERE run_key=?", (run_key,)).fetchone():
            return _snapshot(db, run_key)
        camp = con.execute("SELECT * FROM campaigns WHERE campaign_id=?", (campaign_id,)).fetchone()
        if not camp:
            raise RuntimeError(f"Unknown campaign: {campaign_id}")
        selected, skipped = _eligible_destinations(con, camp)
        if not selected:
            raise RuntimeError("No eligible destinations are configured for this campaign")
        schedule = con.execute("SELECT enabled FROM campaign_schedules WHERE campaign_id=?", (campaign_id,)).fetchone()
        con.execute(
            """INSERT INTO live_coverage_runs(run_key,campaign_id,state,target_count,original_campaign_enabled,
               original_campaign_state,original_schedule_enabled,started_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)""",
            (run_key,campaign_id,"preparing",len(selected),int(camp["enabled"]),camp["lifecycle_state"],int(schedule["enabled"]) if schedule else None,now,now),
        )
        for d in selected:
            con.execute(
                "INSERT INTO live_coverage_targets(run_key,group_id,group_name,state,updated_at) VALUES(?,?,?,?,?)",
                (run_key,int(d["group_id"]),str(d["group_name"]),"planned",now),
            )
        # Prevent scheduler-created work during this explicit one-shot live run.
        if schedule:
            con.execute("UPDATE campaign_schedules SET enabled=0,updated_at=? WHERE campaign_id=?", (now,campaign_id))
        con.execute("UPDATE campaigns SET enabled=1,lifecycle_state='active',updated_at=? WHERE campaign_id=?", (now,campaign_id))
    target_ids = {int(r["group_id"]) for r in _snapshot(db,run_key)["targets"]}
    retired = _retire_safe_old_rows(db,campaign_id,target_ids)
    result = enqueue_campaign(db,campaign_id,dry_run=False,run_key=run_key)
    with db.connect() as con:
        for t in con.execute("SELECT group_id FROM live_coverage_targets WHERE run_key=?", (run_key,)).fetchall():
            q = con.execute("SELECT id,status FROM queue WHERE run_key=? AND group_id=? ORDER BY id DESC LIMIT 1", (run_key,t["group_id"])).fetchone()
            if q:
                con.execute("UPDATE live_coverage_targets SET queue_id=?,state=?,updated_at=? WHERE run_key=? AND group_id=?", (q["id"],q["status"],utcnow(),run_key,t["group_id"]))
            else:
                old = con.execute("""SELECT id,status,campaign_id,error_kind,last_error FROM queue WHERE group_id=? AND status IN ('pending','retry','deferred','processing','sending','uncertain') ORDER BY id DESC LIMIT 1""", (t["group_id"],)).fetchone()
                if old:
                    if old["status"] == "uncertain": state="blocked_uncertain"; reason="Historical UNCERTAIN delivery evidence must be resolved before a new live post can safely be created."
                    elif old["status"] in {"sending","processing"}: state="blocked_existing"; reason=f"Existing {old['status']} obligation is still active; it must settle before this group's coverage post."
                    else: state="blocked_existing"; reason=f"Existing unresolved job #{old['id']} ({old['status']}) prevented coverage enqueue."
                    con.execute("UPDATE live_coverage_targets SET state=?,reason=?,error_kind=?,last_error=?,updated_at=? WHERE run_key=? AND group_id=?",
                                (state,reason,old["error_kind"],old["last_error"],utcnow(),run_key,t["group_id"]))
                else:
                    con.execute("UPDATE live_coverage_targets SET state='failed',reason='Destination was selected but no queue row was created; inspect enqueue diagnostics.',updated_at=? WHERE run_key=? AND group_id=?", (utcnow(),run_key,t["group_id"]))
        con.execute("UPDATE live_coverage_runs SET state='running',updated_at=? WHERE run_key=?", (utcnow(),run_key))
    snap = _sync_targets(db,run_key)
    snap["enqueue"] = result
    snap["retired_old_safe_rows"] = retired
    snap["campaign_skipped_summary"] = skipped
    return snap


def restore_campaign_state(db: Database, run_key: str) -> None:
    with db.connect() as con:
        run = con.execute("SELECT * FROM live_coverage_runs WHERE run_key=?", (run_key,)).fetchone()
        if not run:
            return
        now=utcnow()
        con.execute("UPDATE campaigns SET enabled=?,lifecycle_state=?,updated_at=? WHERE campaign_id=?",
                    (int(run["original_campaign_enabled"] or 0), run["original_campaign_state"] or "paused", now, run["campaign_id"]))
        if run["original_schedule_enabled"] is not None:
            con.execute("UPDATE campaign_schedules SET enabled=?,updated_at=? WHERE campaign_id=?",
                        (int(run["original_schedule_enabled"]),now,run["campaign_id"]))


def render_dashboard(snapshot: dict[str, Any], width: int = 100) -> str:
    width=max(76,min(140,int(width or 100))); barw=max(24,min(60,width-36))
    total=snapshot["target_count"]; sent=snapshot["sent_count"]; pct=snapshot["coverage_percent"]
    filled=round(barw*pct/100); bar="="*filled + ">" + "."*max(0,barw-filled-1) if pct<100 else "="*barw
    c=snapshot["counts"]
    lines=["="*width," SMART AUTO POSTER - FULL COVERAGE LIVE RUN","="*width,
           f" Run      : {snapshot['run']['run_key']}",
           f" Campaign : {snapshot['run']['campaign_id']}",
           f" COVERAGE [{bar}] {pct:3d}%",
           f" Confirmed SENT {sent}/{total} | remaining {max(0,total-sent)}",
           f" Active: pending {c.get('pending',0)} processing {c.get('processing',0)} sending {c.get('sending',0)} | deferred {c.get('deferred',0)} retry {c.get('retry',0)}",
           f" Trouble: uncertain {c.get('blocked_uncertain',0)} failed {c.get('failed',0)} blocked {c.get('blocked_existing',0)} quarantined {c.get('quarantined',0)}",
           "-"*width]
    active=[r for r in snapshot["targets"] if r["state"] not in {"sent","cancelled","expired"}]
    active.sort(key=lambda r: ({"sending":0,"processing":1,"retry":2,"deferred":3,"pending":4,"blocked_uncertain":5,"failed":6}.get(r["state"],7), r.get("due_at") or "", r["group_name"]))
    lines.append(" CURRENT / OUTSTANDING")
    for r in active[:14]:
        reason = r.get("error_kind") or r.get("reason") or ""
        due = f" due {r['due_at'][11:19]}" if r.get("due_at") and len(r["due_at"])>=19 else ""
        lines.append(f" #{str(r.get('queue_id') or '-'):>4} {r['state'].upper():18} {r['group_name'][:34]:34} pass {r.get('pass_no') or 1}{due} {reason[:34]}")
    if len(active)>14: lines.append(f" ... {len(active)-14} more outstanding destination(s)")
    if snapshot["counts"].get("failed") or snapshot["counts"].get("blocked_uncertain") or snapshot["counts"].get("blocked_existing"):
        lines.extend(["-"*width," TROUBLESHOOTING"])
        trouble=[r for r in snapshot["targets"] if r["state"] in {"failed","blocked_uncertain","blocked_existing","quarantined"}]
        for r in trouble[:10]:
            lines.append(f" - {r['group_name']}: {r.get('error_kind') or r['state']} - {(r.get('reason') or r.get('last_error') or '')[:max(20,width-45)]}")
    lines.append("="*width)
    return "\n".join(lines)


def export_report(db: Database, run_key: str, output_dir: Path) -> dict[str, str]:
    snap=_sync_targets(db,run_key); output_dir.mkdir(parents=True,exist_ok=True)
    safe=run_key.replace(":","_")
    jp=output_dir/f"live_coverage_{safe}.json"; cp=output_dir/f"live_coverage_{safe}.csv"
    report={"generated_at":utcnow(),**snap}
    jp.write_text(json.dumps(report,indent=2,ensure_ascii=False,default=str),encoding="utf-8")
    with cp.open("w",newline="",encoding="utf-8-sig") as f:
        fields=["group_id","group_name","queue_id","state","attempts","pass_no","account_key","content_id","due_at","sent_at","error_kind","last_error","reason"]
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader()
        for r in snap["targets"]: w.writerow({k:r.get(k) for k in fields})
    return {"json":str(jp),"csv":str(cp)}


async def run_live_coverage(db: Database, settings, *, campaign_id: str="main_production_01", poll_seconds: int=2,
                            run_key: str|None=None, evidence_scan: bool=True) -> dict[str,Any]:
    from .account_guard import assert_distinct_authorized_accounts
    from .runtime_lock import RuntimeLock
    from .safety import SafetyController
    from .telegram_io import TelegramPool
    from .uncertain_evidence import scan_uncertain_history
    from .worker import Worker

    safety=SafetyController(db,failure_threshold=settings.circuit_breaker_failures,window_minutes=settings.circuit_breaker_window_minutes,
                            pause_minutes=settings.circuit_breaker_pause_minutes,failure_ratio=settings.circuit_breaker_failure_ratio)
    if safety.status().paused:
        raise RuntimeError(f"Outbound posting is safety-paused: {safety.status().reason or 'no reason'}")
    with db.connect() as con:
        inflight=con.execute("SELECT id,group_id,status FROM queue WHERE status IN ('sending','processing')").fetchall()
    if inflight:
        raise RuntimeError("Cannot begin full-coverage run while another Telegram send/processing job is in flight")

    with RuntimeLock(settings.runtime_lock_path):
        if evidence_scan:
            # Positive exact historical evidence can free a previously UNCERTAIN group.
            # Absence never becomes NOT_SENT.
            await scan_uncertain_history(db, settings, campaign_id=campaign_id, window_minutes=20,
                                         diagnostic_window_minutes=120, limit=200, apply_sent=True)
        prep=prepare_run(db,campaign_id,run_key=run_key); rk=prep["run"]["run_key"]
        pool=TelegramPool(settings.api_id,settings.api_hash,settings.sessions,settings.staging_chats,settings.media_cache_dir)
        await pool.connect()
        try:
            auth=await pool.authorization(); assert_distinct_authorized_accounts(auth)
            worker=Worker(db,pool,poll_seconds=max(1,poll_seconds),timezone_name=settings.timezone,
                          min_send_gap_seconds=settings.min_send_gap_seconds,safety=safety)
            worker.sync_accounts(auth,settings.sessions)
            worker.recover_interrupted_sends()
            idle_loops=0
            while True:
                snap=_sync_targets(db,rk)
                # Continue until every runnable target has a terminal result. Historical
                # ambiguity is a blocker, not a reason to skip the rest of the run.
                runnable=[r for r in snap["targets"] if r["state"] in {"pending","retry","deferred","processing","sending"}]
                if not runnable:
                    break
                print("\x1b[2J\x1b[H"+render_dashboard(snap),flush=True)
                worked=await worker.run_once(auth)
                if worked:
                    idle_loops=0
                    continue
                idle_loops+=1
                # If all remaining work is deferred to the future, wait for the earliest
                # due item while keeping the dashboard responsive.
                future=[]; now=datetime.now(timezone.utc)
                for r in runnable:
                    d=_dt(r.get("due_at"))
                    if d and d>now: future.append(d)
                delay=max(1,poll_seconds)
                if future:
                    delay=max(1,min(15,int((min(future)-now).total_seconds())))
                await asyncio.sleep(delay)
            final=_sync_targets(db,rk)
            blocked=final["counts"].get("blocked_uncertain",0)+final["counts"].get("blocked_existing",0)
            failed=final["counts"].get("failed",0)+final["counts"].get("quarantined",0)
            state="complete" if final["sent_count"]==final["target_count"] else "needs_attention"
            with db.connect() as con:
                con.execute("UPDATE live_coverage_runs SET state=?,completed_at=?,updated_at=? WHERE run_key=?", (state,utcnow(),utcnow(),rk))
            final=_sync_targets(db,rk)
            paths=export_report(db,rk,settings.diagnostics_dir)
            final["report_files"]=paths; final["complete"]=(state=="complete"); final["blocked_count"]=blocked; final["failed_count"]=failed
            print("\x1b[2J\x1b[H"+render_dashboard(final),flush=True)
            return final
        finally:
            await pool.disconnect()
            restore_campaign_state(db,rk)
