from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

from .db import Database, utcnow
from .core import record_content_sent
from .telegram_io import classify_exception
from .time_rules import quiet_until


class Worker:
    def __init__(self, db: Database, pool, poll_seconds=5, timezone_name="Australia/Adelaide", min_send_gap_seconds=3, safety=None, notifier=None):
        self.db = db
        self.pool = pool
        self.poll_seconds = poll_seconds
        self.timezone_name = timezone_name
        self.min_send_gap_seconds = max(0, int(min_send_gap_seconds))
        self.safety = safety
        self.notifier = notifier
        self.stop_requested = False

    def recover_interrupted_sends(self):
        """Never blindly retry a job that was in-flight when the process stopped.

        Telegram may have accepted it just before the local process died. Marking it
        uncertain avoids accidental duplicate posting.
        """
        now = utcnow()
        with self.db.connect() as con:
            rows = con.execute("SELECT id,campaign_id,group_id FROM queue WHERE status='sending'").fetchall()
            if rows:
                con.execute("UPDATE queue SET status='uncertain',error_kind='interrupted_send',last_error='process interrupted during send; verify before retry',updated_at=? WHERE status='sending'", (now,))
        for r in rows:
            self.db.event("WARNING", "uncertain_send", "Process stopped while this job was sending; automatic retry suppressed", group_id=r["group_id"], campaign_id=r["campaign_id"])
        return len(rows)

    def sync_accounts(self, auth: dict, session_names: dict[str, str] | None = None):
        session_names = session_names or {}
        now = utcnow()
        with self.db.connect() as con:
            for key, state in auth.items():
                con.execute('''INSERT INTO accounts(account_key,session_name,enabled,authorized,identity,telegram_user_id,last_heartbeat_at,updated_at)
                               VALUES(?,?,?,?,?,?,?,?)
                               ON CONFLICT(account_key) DO UPDATE SET session_name=excluded.session_name,
                               authorized=excluded.authorized,identity=excluded.identity,telegram_user_id=excluded.telegram_user_id,last_heartbeat_at=excluded.last_heartbeat_at,updated_at=excluded.updated_at''',
                            (key, session_names.get(key, key), 1, int(bool(state.get("authorized"))), state.get("identity"), state.get("user_id"), now, now))

    def claim(self):
        """Atomically claim the next eligible queue item.

        Fresh pending work is deliberately preferred over retry/deferred work, and
        destinations with a clean recent history are preferred over repeatedly failing
        destinations. This keeps one problematic group from holding up the healthy
        path while preserving campaign priority and due-time ordering.
        """
        now = utcnow()
        with self.db.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute('''SELECT q.*, d.group_name, d.mode, d.topic_id, d.preferred_account,
                                        d.primary_access,d.secondary_access,d.quarantine_until,d.next_eligible_at,
                                        d.quiet_start,d.quiet_end,
                                        COALESCE(q.content_id,c.content_id) AS content_id, c.min_destination_interval_seconds AS campaign_interval,
                                        ct.caption, ct.media_json, d.min_interval_seconds
                                 FROM queue q
                                 JOIN destinations d ON d.group_id=q.group_id
                                 JOIN campaigns c ON c.campaign_id=q.campaign_id
                                 JOIN content ct ON ct.content_id=COALESCE(q.content_id,c.content_id)
                                 WHERE q.status IN ('pending','retry','deferred') AND q.due_at<=?
                                 AND c.enabled=1 AND c.lifecycle_state='active'
                                 AND (c.start_at IS NULL OR c.start_at<=?)
                                 AND (c.end_at IS NULL OR c.end_at>=?)
                                 AND d.enabled=1 AND d.needs_review=0
                                 AND (d.quarantine_until IS NULL OR d.quarantine_until<=?)
                                 AND (d.next_eligible_at IS NULL OR d.next_eligible_at<=?)
                                 ORDER BY c.priority DESC,
                                          CASE q.status WHEN 'pending' THEN 0 WHEN 'retry' THEN 1 ELSE 2 END ASC,
                                          d.consecutive_failures ASC,
                                          q.due_at ASC,
                                          q.id ASC
                                 LIMIT 1''', (now, now, now, now, now)).fetchone()
            if not row:
                return None
            changed = con.execute("UPDATE queue SET status='sending',updated_at=? WHERE id=? AND status IN ('pending','retry','deferred')", (now, row["id"]))
            if changed.rowcount != 1:
                return None
            return dict(row)

    def _account_rows(self):
        with self.db.connect() as con:
            rows = con.execute("SELECT * FROM accounts").fetchall()
        return {r["account_key"]: dict(r) for r in rows}

    def choose_account(self, job, auth):
        rows = self._account_rows()
        now = datetime.now(timezone.utc)

        if job.get("account_key"):
            candidates = [job["account_key"]]
        else:
            preferred = (job["preferred_account"] or "primary").lower()
            candidates = []
            if preferred in {"primary", "secondary"}:
                candidates.append(preferred)
            elif preferred == "both":
                # V3.0 safe load balancing: among dual-access accounts, prefer higher health then the least recently used.
                def balance_key(key):
                    r = rows.get(key, {})
                    health = int(r.get("health_score") or 0)
                    last = r.get("last_success_at") or ""
                    return (-health, last, key)
                candidates.extend(sorted(["primary", "secondary"], key=balance_key))
            for key in ["primary", "secondary"]:
                if key not in candidates:
                    candidates.append(key)

        cooling = []
        accessible_authorized = False
        for key in candidates:
            if key not in {"primary", "secondary"}:
                continue
            if not bool(job.get(f"{key}_access")):
                continue
            if not auth.get(key, {}).get("authorized"):
                continue
            accessible_authorized = True
            account = rows.get(key, {})
            if not bool(account.get("enabled", 1)):
                continue
            raw = account.get("cooldown_until")
            if raw:
                try:
                    until = datetime.fromisoformat(raw)
                    if until.tzinfo is None:
                        until = until.replace(tzinfo=timezone.utc)
                    if until > now:
                        cooling.append(until)
                        continue
                except Exception:
                    pass
            if self.min_send_gap_seconds and account.get("last_success_at"):
                try:
                    last = datetime.fromisoformat(account["last_success_at"])
                    if last.tzinfo is None:
                        last = last.replace(tzinfo=timezone.utc)
                    pace_until = last + timedelta(seconds=self.min_send_gap_seconds)
                    if pace_until > now:
                        cooling.append(pace_until)
                        continue
                except Exception:
                    pass
            return key, None, None

        if cooling:
            return None, min(cooling).isoformat(timespec="seconds"), "account_cooldown_or_pacing"
        if accessible_authorized:
            return None, None, "account_disabled"
        return None, None, "no_authorized_account"

    @staticmethod
    def retry_delay_seconds(attempts: int, kind: str | None = None) -> int:
        """Return bounded exponential retry delay for transient failures.

        `attempts` is the number of failed attempts including the failure currently
        being handled. Telegram-provided flood/slow-mode retry times still take
        precedence; this fallback is for failures without an authoritative retry_at.
        """
        attempt = max(1, int(attempts))
        base = {
            "worker_busy": 5,
            "network": 15,
            "flood_wait": 30,
            "slow_mode": 30,
        }.get(kind, 30)
        return min(900, base * (2 ** min(attempt - 1, 5)))

    def defer_job(self, job, due_at: str, reason: str, account: str | None = None):
        with self.db.connect() as con:
            con.execute("UPDATE queue SET status='deferred',account_key=COALESCE(?,account_key),due_at=?,error_kind='deferred',last_error=?,updated_at=? WHERE id=?",
                        (account, due_at, reason[:1000], utcnow(), job["id"]))
        self.db.event("INFO", "job_deferred", reason[:800], account_key=account, group_id=job["group_id"], campaign_id=job["campaign_id"])

    async def run_once(self, auth):
        if self.safety is not None and self.safety.status().paused:
            return False
        job = self.claim()
        if not job:
            return False

        try:
            quiet_end = quiet_until(datetime.now(timezone.utc), job.get("quiet_start"), job.get("quiet_end"), self.timezone_name)
        except Exception as exc:
            self.finish_error(job, f"quiet_hours_invalid: {exc}", permanent=True)
            return True
        if quiet_end:
            self.defer_job(job, quiet_end.isoformat(timespec="seconds"), "destination quiet hours")
            return True

        account, defer_until, reason = self.choose_account(job, auth)
        if not account:
            if defer_until:
                self.defer_job(job, defer_until, reason or "account cooldown")
            else:
                due = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(timespec="seconds")
                self.defer_job(job, due, reason or "no_authorized_account")
                if self.notifier is not None and reason == "no_authorized_account":
                    self.notifier.emit("IMPORTANT", "No Telegram account available", f"Job #{job['id']} deferred because no authorized account can reach {job['group_name']}.", dedupe_key="no_authorized_account", dedupe_window_seconds=3600)
            return True

        try:
            media = json.loads(job["media_json"] or "[]")
            ids = await self.pool.send(account, job["group_id"], job["caption"], media, job["mode"], job["topic_id"])
            now = utcnow()
            interval = max(int(job.get("min_interval_seconds") or 0), int(job.get("campaign_interval") or 0))
            next_eligible = (datetime.now(timezone.utc) + timedelta(seconds=interval)).isoformat(timespec="seconds") if interval > 0 else None
            with self.db.connect() as con:
                con.execute("UPDATE queue SET status='sent',account_key=?,attempts=attempts+1,telegram_message_ids=?,error_kind=NULL,last_error=NULL,resolved_at=?,updated_at=? WHERE id=?",
                            (account, json.dumps(ids), now, now, job["id"]))
                con.execute("UPDATE destinations SET last_post_at=?,next_eligible_at=?,consecutive_failures=0,quarantine_until=NULL,updated_at=? WHERE group_id=?",
                            (now, next_eligible, now, job["group_id"]))
                con.execute("UPDATE accounts SET cooldown_until=NULL,consecutive_failures=0,last_error=NULL,last_success_at=?,last_heartbeat_at=?,health_score=MIN(100,health_score+2),updated_at=? WHERE account_key=?",
                            (now, now, now, account))
            record_content_sent(self.db, job["campaign_id"], job["group_id"], job["content_id"], now)
            self.db.event("INFO", "send_success", f"Sent {job['campaign_id']} / {job['content_id']} to {job['group_name']}", account_key=account, group_id=job["group_id"], campaign_id=job["campaign_id"])
        except Exception as exc:
            kind, retry_at, permanent = classify_exception(exc)
            self.finish_error(job, f"{kind}: {exc}", permanent=permanent, retry_at=retry_at, account=account, kind=kind)
        return True

    def finish_error(self, job, error, permanent=False, retry_at=None, account=None, kind: str | None = None):
        now = utcnow()
        with self.db.connect() as con:
            attempts = int(job.get("attempts", 0)) + 1
            max_attempts = int(job.get("max_attempts", 4))
            if permanent or attempts >= max_attempts:
                status, due = "failed", job["due_at"]
            else:
                status = "retry"
                due = retry_at or (datetime.now(timezone.utc) + timedelta(seconds=self.retry_delay_seconds(attempts, kind))).isoformat(timespec="seconds")
            con.execute("UPDATE queue SET status=?,account_key=?,attempts=?,due_at=?,error_kind=?,last_error=?,resolved_at=?,updated_at=? WHERE id=?",
                        (status, account, attempts, due, kind, error[:1000], now if status in {'failed','quarantined','cancelled','expired'} else None, now, job["id"]))
            # Slow mode is a destination timing rule, not a broken destination.
            if kind == "slow_mode" and retry_at:
                con.execute("UPDATE destinations SET next_eligible_at=?,updated_at=? WHERE group_id=?", (retry_at, now, job["group_id"]))
            penalize_destination = kind not in {"network", "worker_busy", "flood_wait", "slow_mode", "no_authorized_account", "account_disabled", "account_cooldown", "account_cooldown_or_pacing"}
            if penalize_destination:
                con.execute("UPDATE destinations SET consecutive_failures=consecutive_failures+1,updated_at=? WHERE group_id=?", (now, job["group_id"]))
                failures = con.execute("SELECT consecutive_failures FROM destinations WHERE group_id=?", (job["group_id"],)).fetchone()[0]
                if failures >= 5:
                    quarantine = (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat(timespec="seconds")
                    con.execute("UPDATE destinations SET quarantine_until=? WHERE group_id=?", (quarantine, job["group_id"]))
                    if status == "failed":
                        con.execute("UPDATE queue SET status='quarantined',error_kind=COALESCE(error_kind,'destination_quarantined') WHERE id=?", (job["id"],))
                    if self.notifier is not None:
                        self.notifier.emit("WARNING", "Destination quarantined", f"{job['group_name']} was quarantined after repeated failures.", dedupe_key=f"quarantine:{job['group_id']}", dedupe_window_seconds=86400)
            if account:
                cooldown = retry_at if kind == "flood_wait" else None
                con.execute('''UPDATE accounts SET consecutive_failures=consecutive_failures+1,last_error=?,last_failure_at=?,
                               cooldown_until=COALESCE(?,cooldown_until),health_score=MAX(0,health_score-?),last_heartbeat_at=?,updated_at=? WHERE account_key=?''',
                            (error[:1000], now, cooldown, 12 if kind in {'flood_wait','network'} else 6, now, now, account))
        self.db.event("ERROR" if permanent else "WARNING", "send_failure", error[:800], account_key=account, group_id=job["group_id"], campaign_id=job["campaign_id"])

    async def run_forever(self, auth, session_names=None):
        recovered = self.recover_interrupted_sends()
        if recovered:
            print(f"[RECOVERY] {recovered} interrupted send(s) marked UNCERTAIN; duplicate retry suppressed")
        self.sync_accounts(auth, session_names)
        if not any(x["authorized"] for x in auth.values()):
            raise RuntimeError("No authorized Telegram user sessions")
        while not self.stop_requested:
            worked = await self.run_once(auth)
            if not worked:
                await asyncio.sleep(self.poll_seconds)
