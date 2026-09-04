from __future__ import annotations

from datetime import datetime, timezone

from .db import Database, utcnow
from .queue_hygiene import queue_hygiene_plan
from .mission_control import mission_snapshot

TERMINAL = {"sent","failed","quarantined","cancelled","expired"}
ACTIVE = {"pending","retry","deferred","processing","sending"}


def refresh_run_ledger(db: Database, *, campaign_id: str | None = None) -> list[dict]:
    where="WHERE run_key IS NOT NULL"; params=[]
    if campaign_id:
        where += " AND campaign_id=?"; params.append(campaign_id)
    with db.connect() as con:
        groups=con.execute(f"SELECT run_key,campaign_id,MIN(created_at) started FROM queue {where} GROUP BY run_key,campaign_id",params).fetchall()
        out=[]
        for g in groups:
            counts={r["status"]:int(r["n"]) for r in con.execute("SELECT status,COUNT(*) n FROM queue WHERE run_key=? AND campaign_id=? GROUP BY status",(g["run_key"],g["campaign_id"])).fetchall()}
            active=sum(counts.get(x,0) for x in ACTIVE)
            uncertain=counts.get("uncertain",0)
            state="attention" if uncertain else ("open" if active else "complete")
            completed=utcnow() if state=="complete" else None
            con.execute("""INSERT INTO production_runs(run_key,campaign_id,state,target_count,inserted_count,overlap_locked,incompatible_count,started_at,completed_at,updated_at)
                         VALUES(?,?,?,?,?,?,?,?,?,?)
                         ON CONFLICT(run_key,campaign_id) DO UPDATE SET state=excluded.state,
                         completed_at=COALESCE(production_runs.completed_at,excluded.completed_at),updated_at=excluded.updated_at""",
                        (g["run_key"],g["campaign_id"],state,sum(counts.values()),sum(counts.values()),0,0,g["started"],completed,utcnow()))
            out.append({"run_key":g["run_key"],"campaign_id":g["campaign_id"],"state":state,"counts":counts})
    return out


def production_gate(db: Database, *, campaign_id: str = "main_production_01") -> dict:
    refresh_run_ledger(db, campaign_id=campaign_id)
    hygiene = queue_hygiene_plan(db, campaign_id=None)
    mission = mission_snapshot(db, campaign_id=campaign_id, limit=20)
    with db.connect() as con:
        camp = con.execute("SELECT campaign_id,lifecycle_state,enabled FROM campaigns WHERE campaign_id=?", (campaign_id,)).fetchone()
        schedule = con.execute("SELECT mode,interval_seconds,next_run_at,enabled,timezone FROM campaign_schedules WHERE campaign_id=?", (campaign_id,)).fetchone()
        uncertain = int(con.execute("SELECT COUNT(*) FROM queue WHERE status='uncertain'").fetchone()[0])
        sending = int(con.execute("SELECT COUNT(*) FROM queue WHERE status IN ('processing','sending')").fetchone()[0])
        integrity = [r[0] for r in con.execute("PRAGMA integrity_check").fetchall()]
        fk = [tuple(r) for r in con.execute("PRAGMA foreign_key_check").fetchall()]
        heartbeats = {r["component"]: dict(r) for r in con.execute("SELECT * FROM heartbeats WHERE component IN ('service','scheduler','worker','admin_bot')").fetchall()}
        destination_stats=dict(con.execute("""SELECT COUNT(*) total,
               SUM(CASE WHEN mode='photo' THEN 1 ELSE 0 END) photo,
               SUM(CASE WHEN mode='text' THEN 1 ELSE 0 END) text,
               SUM(CASE WHEN mode NOT IN ('photo','text') THEN 1 ELSE 0 END) invalid_mode,
               SUM(CASE WHEN needs_review=1 THEN 1 ELSE 0 END) review
               FROM destinations WHERE enabled=1""").fetchone())
        timing=[dict(r) for r in con.execute("""SELECT t.group_id,d.group_name,t.slow_mode_events,t.flood_wait_events,
                    t.max_wait_seconds,t.observed_min_interval_seconds,t.next_safe_at
                    FROM destination_timing_profiles t JOIN destinations d ON d.group_id=t.group_id
                    ORDER BY t.max_wait_seconds DESC,t.slow_mode_events DESC LIMIT 10""").fetchall()]
        cap_coverage=int(con.execute("SELECT COUNT(DISTINCT group_id) FROM destination_account_capabilities").fetchone()[0])
        latest_runs=[dict(r) for r in con.execute("SELECT * FROM production_runs WHERE campaign_id=? ORDER BY started_at DESC LIMIT 5",(campaign_id,)).fetchall()]
    blockers = []
    warnings = []
    if not camp:
        blockers.append("production campaign missing")
    if uncertain:
        blockers.append(f"{uncertain} UNCERTAIN delivery row(s) require evidence-backed reconciliation")
    if sending:
        blockers.append(f"{sending} in-flight processing/sending row(s)")
    if hygiene["safe_suppressions"]:
        blockers.append(f"{hygiene['safe_suppressions']} provably-unsent overlap row(s) still require safe suppression")
    if hygiene["review_count"]:
        blockers.append(f"{hygiene['review_count']} queue overlap(s) require review")
    if integrity != ["ok"] or fk:
        blockers.append("database integrity/foreign-key gate failed")
    if destination_stats.get("invalid_mode"):
        blockers.append(f"{destination_stats['invalid_mode']} enabled destination(s) have unresolved delivery mode")
    if destination_stats.get("review"):
        warnings.append(f"{destination_stats['review']} enabled destination(s) are still marked review")
    if schedule and int(schedule["enabled"] or 0) and str(schedule["mode"]) == "interval" and int(schedule["interval_seconds"] or 0) != 14400:
        warnings.append(f"production interval is {schedule['interval_seconds']}s, expected 14400s")
    if mission.get("duplicate_unresolved_group_sets", 0):
        warnings.append(f"mission view sees {mission['duplicate_unresolved_group_sets']} unresolved overlap group(s)")
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "campaign_id": campaign_id,
        "ready": not blockers,
        "blockers": blockers,
        "warnings": warnings,
        "campaign": dict(camp) if camp else None,
        "schedule": dict(schedule) if schedule else None,
        "uncertain": uncertain,
        "in_flight": sending,
        "queue_hygiene": hygiene,
        "mission": mission,
        "heartbeats": heartbeats,
        "database_ok": integrity == ["ok"] and not fk,
        "destination_stats": destination_stats,
        "capability_coverage_groups": cap_coverage,
        "timing_hotspots": timing,
        "latest_runs": latest_runs,
        "safety": {"uncertain_auto_retry": False, "one_unresolved_group": True, "round_pass": True, "evidence_preserved": True},
    }
