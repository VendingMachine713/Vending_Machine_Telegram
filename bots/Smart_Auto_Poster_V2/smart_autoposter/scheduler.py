from __future__ import annotations

import json
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from .core import enqueue_campaign
from .db import Database, utcnow
from .time_rules import parse_hhmm

DAY_MAP = {
    "mon": 0, "monday": 0,
    "tue": 1, "tues": 1, "tuesday": 1,
    "wed": 2, "wednesday": 2,
    "thu": 3, "thur": 3, "thurs": 3, "thursday": 3,
    "fri": 4, "friday": 4,
    "sat": 5, "saturday": 5,
    "sun": 6, "sunday": 6,
}


def normalize_days(values: list[str] | None) -> list[int]:
    if not values:
        return list(range(7))
    out = set()
    for raw in values:
        key = raw.strip().lower()
        if key.isdigit() and 0 <= int(key) <= 6:
            out.add(int(key))
        elif key in DAY_MAP:
            out.add(DAY_MAP[key])
        else:
            raise ValueError(f"Unknown day: {raw}")
    return sorted(out)


def normalize_times(values: list[str]) -> list[str]:
    result = []
    for raw in values:
        t = parse_hhmm(raw)
        result.append(f"{t.hour:02d}:{t.minute:02d}")
    return sorted(set(result))


def next_daily_run(after_utc: datetime, times: list[str], days: list[int], timezone_name: str) -> datetime:
    tz = ZoneInfo(timezone_name)
    local = after_utc.astimezone(tz)
    parsed = [parse_hhmm(x) for x in times]
    for offset in range(0, 9):
        d = local.date() + timedelta(days=offset)
        if d.weekday() not in days:
            continue
        for t in parsed:
            candidate = datetime.combine(d, t, tzinfo=tz)
            # strictly after the reference instant, preventing the same slot re-running.
            if candidate > local:
                return candidate.astimezone(timezone.utc)
    raise RuntimeError("Could not calculate next daily schedule occurrence")


def configure_interval(db: Database, campaign_id: str, seconds: int, timezone_name: str, start_in_seconds: int | None = None):
    if seconds < 60:
        raise ValueError("Interval must be at least 60 seconds")
    now = datetime.now(timezone.utc)
    delay = seconds if start_in_seconds is None else max(0, int(start_in_seconds))
    next_run = now + timedelta(seconds=delay)
    with db.connect() as con:
        if not con.execute("SELECT 1 FROM campaigns WHERE campaign_id=?", (campaign_id,)).fetchone():
            raise RuntimeError(f"Unknown campaign: {campaign_id}")
        con.execute('''INSERT INTO campaign_schedules(campaign_id,mode,interval_seconds,daily_times_json,days_json,timezone,next_run_at,enabled,updated_at)
                       VALUES(?, 'interval', ?, '[]', '[]', ?, ?, 1, ?)
                       ON CONFLICT(campaign_id) DO UPDATE SET mode='interval',interval_seconds=excluded.interval_seconds,
                       daily_times_json='[]',days_json='[]',timezone=excluded.timezone,next_run_at=excluded.next_run_at,enabled=1,updated_at=excluded.updated_at''',
                    (campaign_id, int(seconds), timezone_name, next_run.isoformat(timespec="seconds"), utcnow()))


def configure_daily(db: Database, campaign_id: str, times: list[str], days: list[str] | None, timezone_name: str):
    times = normalize_times(times)
    if not times:
        raise ValueError("At least one daily time is required")
    day_nums = normalize_days(days)
    next_run = next_daily_run(datetime.now(timezone.utc), times, day_nums, timezone_name)
    with db.connect() as con:
        if not con.execute("SELECT 1 FROM campaigns WHERE campaign_id=?", (campaign_id,)).fetchone():
            raise RuntimeError(f"Unknown campaign: {campaign_id}")
        con.execute('''INSERT INTO campaign_schedules(campaign_id,mode,interval_seconds,daily_times_json,days_json,timezone,next_run_at,enabled,updated_at)
                       VALUES(?, 'daily', NULL, ?, ?, ?, ?, 1, ?)
                       ON CONFLICT(campaign_id) DO UPDATE SET mode='daily',interval_seconds=NULL,daily_times_json=excluded.daily_times_json,
                       days_json=excluded.days_json,timezone=excluded.timezone,next_run_at=excluded.next_run_at,enabled=1,updated_at=excluded.updated_at''',
                    (campaign_id, json.dumps(times), json.dumps(day_nums), timezone_name, next_run.isoformat(timespec="seconds"), utcnow()))



def configure_once(db: Database, campaign_id: str, at_value: str, timezone_name: str):
    raw = datetime.fromisoformat(at_value)
    if raw.tzinfo is None:
        raw = raw.replace(tzinfo=ZoneInfo(timezone_name))
    due = raw.astimezone(timezone.utc)
    if due <= datetime.now(timezone.utc):
        raise ValueError("One-off schedule must be in the future")
    with db.connect() as con:
        if not con.execute("SELECT 1 FROM campaigns WHERE campaign_id=?", (campaign_id,)).fetchone():
            raise RuntimeError(f"Unknown campaign: {campaign_id}")
        con.execute('''INSERT INTO campaign_schedules(campaign_id,mode,interval_seconds,daily_times_json,days_json,timezone,next_run_at,enabled,updated_at)
                       VALUES(?, 'once', NULL, '[]', '[]', ?, ?, 1, ?)
                       ON CONFLICT(campaign_id) DO UPDATE SET mode='once',interval_seconds=NULL,daily_times_json='[]',days_json='[]',
                       timezone=excluded.timezone,next_run_at=excluded.next_run_at,last_run_at=NULL,enabled=1,updated_at=excluded.updated_at''',
                    (campaign_id, timezone_name, due.isoformat(timespec="seconds"), utcnow()))


def disable_schedule(db: Database, campaign_id: str):
    with db.connect() as con:
        con.execute("UPDATE campaign_schedules SET enabled=0,updated_at=? WHERE campaign_id=?", (utcnow(), campaign_id))


def _next_for_row(row, due: datetime) -> datetime | None:
    mode = row["mode"]
    if mode == "interval":
        seconds = int(row["interval_seconds"] or 0)
        if seconds <= 0:
            return None
        # Catch up to the first future slot without enqueueing a burst of missed cycles.
        nxt = due + timedelta(seconds=seconds)
        now = datetime.now(timezone.utc)
        while nxt <= now:
            nxt += timedelta(seconds=seconds)
        return nxt
    if mode == "once":
        return None
    if mode == "daily":
        reference = max(due, datetime.now(timezone.utc))
        return next_daily_run(
            reference,
            json.loads(row["daily_times_json"] or "[]"),
            json.loads(row["days_json"] or "[]") or list(range(7)),
            row["timezone"],
        )
    return None


class Scheduler:
    def __init__(self, db: Database, limits: dict | None = None):
        self.db = db
        self.limits = limits or None

    def tick(self) -> list[dict]:
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat(timespec="seconds")
        with self.db.connect() as con:
            rows = con.execute('''SELECT s.*,c.enabled AS campaign_enabled,c.lifecycle_state,c.start_at,c.end_at,c.max_cycles,c.completed_cycles
                                  FROM campaign_schedules s JOIN campaigns c ON c.campaign_id=s.campaign_id
                                  WHERE s.enabled=1 AND s.next_run_at IS NOT NULL AND s.next_run_at<=?
                                  ORDER BY s.next_run_at ASC''', (now_iso,)).fetchall()
        results = []
        for row in rows:
            campaign_id = row["campaign_id"]
            due = datetime.fromisoformat(row["next_run_at"])
            if due.tzinfo is None:
                due = due.replace(tzinfo=timezone.utc)

            if not row["campaign_enabled"] or row["lifecycle_state"] != "active":
                self.db.event("INFO", "schedule_skipped", "Campaign not ACTIVE; scheduled run skipped", campaign_id=campaign_id)
                next_run = _next_for_row(row, due)
                self._advance(campaign_id, due, next_run)
                continue
            if int(row["max_cycles"] or 0) and int(row["completed_cycles"] or 0) >= int(row["max_cycles"]):
                disable_schedule(self.db, campaign_id)
                self.db.event("INFO", "campaign_cycle_limit", f"Campaign cycle limit reached: {row['completed_cycles']}/{row['max_cycles']}; schedule disabled", campaign_id=campaign_id)
                continue
            if row["start_at"] and now_iso < row["start_at"]:
                # Preserve schedule but don't emit before campaign start.
                continue
            if row["end_at"] and now_iso > row["end_at"]:
                disable_schedule(self.db, campaign_id)
                with self.db.connect() as con:
                    con.execute("UPDATE campaigns SET enabled=0,lifecycle_state='archived',updated_at=? WHERE campaign_id=?", (utcnow(), campaign_id))
                self.db.event("INFO", "schedule_expired", "Campaign end time passed; campaign archived", campaign_id=campaign_id)
                continue

            run_key = f"schedule:{row['next_run_at']}"
            try:
                result = enqueue_campaign(self.db, campaign_id, dry_run=False, run_key=run_key, limits=self.limits)
                results.append({"campaign_id": campaign_id, **result})
                self.db.event("INFO", "schedule_enqueued", f"Scheduled run queued: {result['inserted']} jobs", campaign_id=campaign_id, details=json.dumps(result))
            except Exception as exc:
                self.db.event("ERROR", "schedule_error", str(exc)[:800], campaign_id=campaign_id)
            next_run = _next_for_row(row, due)
            self._advance(campaign_id, due, next_run)
        return results

    def _advance(self, campaign_id: str, last_run: datetime, next_run: datetime | None):
        with self.db.connect() as con:
            con.execute("UPDATE campaign_schedules SET last_run_at=?,next_run_at=?,enabled=?,updated_at=? WHERE campaign_id=?",
                        (last_run.isoformat(timespec="seconds"), next_run.isoformat(timespec="seconds") if next_run else None, int(next_run is not None), utcnow(), campaign_id))


def schedule_occurrences(row, start_utc: datetime, end_utc: datetime) -> list[datetime]:
    """Return future schedule occurrences in a window without mutating the DB."""
    out: list[datetime] = []
    mode = row["mode"]
    if not row["enabled"]:
        return out
    if mode == "interval":
        seconds = int(row["interval_seconds"] or 0)
        if seconds <= 0:
            return out
        raw = row["next_run_at"]
        if not raw:
            return out
        cur = datetime.fromisoformat(raw)
        if cur.tzinfo is None:
            cur = cur.replace(tzinfo=timezone.utc)
        while cur < start_utc:
            cur += timedelta(seconds=seconds)
        while cur <= end_utc:
            out.append(cur)
            cur += timedelta(seconds=seconds)
        return out
    if mode == "once":
        raw = row["next_run_at"]
        if raw:
            cur = datetime.fromisoformat(raw)
            if cur.tzinfo is None: cur = cur.replace(tzinfo=timezone.utc)
            if start_utc <= cur <= end_utc: out.append(cur)
        return out
    if mode == "daily":
        times = json.loads(row["daily_times_json"] or "[]")
        days = json.loads(row["days_json"] or "[]") or list(range(7))
        ref = start_utc - timedelta(seconds=1)
        for _ in range(1000):
            nxt = next_daily_run(ref, times, days, row["timezone"])
            if nxt > end_utc:
                break
            if nxt >= start_utc:
                out.append(nxt)
            ref = nxt
        return out
    return out


def simulate_schedules(db: Database, hours: int = 24) -> list[dict]:
    hours = max(1, min(int(hours), 24 * 31))
    start = datetime.now(timezone.utc)
    end = start + timedelta(hours=hours)
    with db.connect() as con:
        rows = con.execute('''SELECT s.*,c.name,c.enabled AS campaign_enabled,c.lifecycle_state,c.start_at,c.end_at,c.max_cycles,c.completed_cycles
                              FROM campaign_schedules s JOIN campaigns c ON c.campaign_id=s.campaign_id
                              WHERE s.enabled=1 ORDER BY c.priority DESC,c.campaign_id''').fetchall()
    out = []
    for row in rows:
        if not row["campaign_enabled"] or row["lifecycle_state"] != "active":
            continue
        if int(row["max_cycles"] or 0) and int(row["completed_cycles"] or 0) >= int(row["max_cycles"]):
            continue
        for occ in schedule_occurrences(row, start, end):
            iso = occ.isoformat(timespec="seconds")
            if row["start_at"] and iso < row["start_at"]:
                continue
            if row["end_at"] and iso > row["end_at"]:
                continue
            out.append({"at": iso, "campaign_id": row["campaign_id"], "name": row["name"], "mode": row["mode"]})
    return sorted(out, key=lambda x: (x["at"], x["campaign_id"]))
