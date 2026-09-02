from __future__ import annotations

import asyncio
import inspect
import json
from datetime import datetime, timedelta, timezone

from .db import Database, utcnow
from .core import record_content_sent
from .delivery_ledger import (
    finish_attempt,
    mark_acknowledged,
    reconcile_open_attempts_from_queue,
    start_attempt,
)
from .progress import TerminalProgressReporter
from .telegram_io import classify_exception
from .time_rules import quiet_until


class Worker:
    def __init__(self, db: Database, pool, poll_seconds=5, timezone_name="Australia/Adelaide", min_send_gap_seconds=3, safety=None, notifier=None, progress_reporter=None):
        self.db = db
        self.pool = pool
        self.poll_seconds = poll_seconds
        self.timezone_name = timezone_name
        self.min_send_gap_seconds = max(0, int(min_send_gap_seconds))
        self.safety = safety
        self.notifier = notifier
        self.progress = progress_reporter or TerminalProgressReporter(db)
        self.stop_requested = False
        self._startup_recovery_done = False
        self.last_recovery_summary = None

    def recover_interrupted_sends(self):
        """Perform one fail-closed startup recovery pass.

        Any job left in ``sending`` may already have reached Telegram, so it is moved
        to UNCERTAIN and never blindly retried. Work belonging to terminal campaigns
        is expired, while pending/retry/deferred jobs for active *or paused* campaigns
        are deliberately preserved so a restart/resume continues from existing state.

        The pass is idempotent within a Worker instance because the CLI worker path can
        invoke startup recovery before ``run_forever`` invokes it again.
        """
        if self._startup_recovery_done:
            return 0

        now = utcnow()
        with self.db.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            interrupted = con.execute(
                "SELECT id,campaign_id,group_id FROM queue WHERE status='sending' ORDER BY id"
            ).fetchall()
            if interrupted:
                con.execute(
                    """UPDATE queue
                       SET status='uncertain',error_kind='interrupted_send',
                           last_error='process interrupted during send; verify before retry',
                           resolved_at=NULL,updated_at=?
                       WHERE status='sending'""",
                    (now,),
                )

            expired = con.execute(
                """UPDATE queue
                   SET status='expired',error_kind='campaign_ineligible',
                       last_error='campaign archived or end date passed',
                       resolved_at=?,updated_at=?
                   WHERE status IN ('pending','retry','deferred')
                     AND campaign_id IN (
                        SELECT campaign_id FROM campaigns
                        WHERE lifecycle_state='archived'
                           OR (end_at IS NOT NULL AND end_at<?)
                     )""",
                (now, now, now),
            ).rowcount

            counts = {
                r["status"]: int(r["n"])
                for r in con.execute(
                    "SELECT status,COUNT(*) AS n FROM queue GROUP BY status"
                ).fetchall()
            }
            resumable_active = con.execute(
                """SELECT COUNT(*) FROM queue q JOIN campaigns c ON c.campaign_id=q.campaign_id
                   WHERE q.status IN ('pending','retry','deferred')
                     AND c.lifecycle_state='active' AND c.enabled=1"""
            ).fetchone()[0]
            preserved_paused = con.execute(
                """SELECT COUNT(*) FROM queue q JOIN campaigns c ON c.campaign_id=q.campaign_id
                   WHERE q.status IN ('pending','retry','deferred')
                     AND c.lifecycle_state='paused'"""
            ).fetchone()[0]
            uncertain_total = con.execute(
                "SELECT COUNT(*) FROM queue WHERE status='uncertain'"
            ).fetchone()[0]

        ledger_reconciled = reconcile_open_attempts_from_queue(self.db)

        for row in interrupted:
            self.db.event(
                "WARNING",
                "uncertain_send",
                "Process stopped while this job was sending; automatic retry suppressed",
                group_id=row["group_id"],
                campaign_id=row["campaign_id"],
            )

        summary = {
            "interrupted_to_uncertain": len(interrupted),
            "terminal_campaign_jobs_expired": int(expired),
            "resumable_active_jobs": int(resumable_active),
            "preserved_paused_jobs": int(preserved_paused),
            "uncertain_total": int(uncertain_total),
            "delivery_attempts_reconciled": ledger_reconciled,
            "queue_status": counts,
        }
        self.last_recovery_summary = summary
        self._startup_recovery_done = True
        if interrupted or expired or any(ledger_reconciled.values()):
            self.db.event(
                "WARNING" if interrupted else "INFO",
                "startup_recovery",
                "Startup queue recovery completed",
                details=json.dumps(summary, sort_keys=True),
            )
        return len(interrupted)

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
        """Return bounded exponential retry delay for transient failures."""
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
        self.progress.update(job, "deferred", 0, error=reason[:300])
        self.db.event("INFO", "job_deferred", reason[:800], account_key=account, group_id=job["group_id"], campaign_id=job["campaign_id"])

    def mark_post_send_uncertain(self, job, account: str, message_ids, exc: Exception, attempt_id: int | None = None):
        """Suppress automatic retry when Telegram succeeded but local persistence did not."""
        now = utcnow()
        detail = f"post-send persistence failed; Telegram acknowledged delivery: {exc}"
        try:
            with self.db.connect() as con:
                con.execute('''UPDATE queue SET status='uncertain',account_key=?,attempts=attempts+1,
                               telegram_message_ids=?,error_kind='post_send_persistence',last_error=?,
                               resolved_at=NULL,updated_at=? WHERE id=? AND status='sending' ''',
                            (account, json.dumps(message_ids), detail[:1000], now, job["id"]))
        except Exception:
            pass
        self.progress.update(job, "uncertain", 100, error=detail[:300])
        if attempt_id is not None:
            try:
                finish_attempt(
                    self.db,
                    attempt_id,
                    "uncertain",
                    error_kind="post_send_persistence",
                    error_text=detail,
                    message_ids=message_ids,
                )
            except Exception:
                pass
        try:
            self.db.event("WARNING", "uncertain_send", detail[:800], account_key=account,
                          group_id=job["group_id"], campaign_id=job["campaign_id"],
                          details=json.dumps({"job_id": job["id"], "telegram_message_ids": message_ids, "delivery_attempt_id": attempt_id}))
        except Exception:
            pass
        if self.notifier is not None:
            try:
                self.notifier.emit(
                    "IMPORTANT",
                    "Telegram send needs reconciliation",
                    f"{job['group_name']} was acknowledged by Telegram but local confirmation failed. Automatic retry is suppressed.",
                    dedupe_key=f"uncertain:{job['id']}",
                    dedupe_window_seconds=86400,
                )
            except Exception:
                pass

    def _ledger_warning(self, job, account, message: str):
        try:
            self.db.event(
                "WARNING",
                "delivery_ledger_warning",
                message[:800],
                account_key=account,
                group_id=job["group_id"],
                campaign_id=job["campaign_id"],
            )
        except Exception:
            pass

    def _send_progress_kwargs(self, job, stage: str) -> dict:
        """Pass progress callbacks only to pool implementations that support them.

        Older test doubles and compatible pool adapters pre-date the optional callback.
        Detecting support before sending is important: retrying after a TypeError could
        duplicate a Telegram delivery if the exception happened after network I/O.
        """
        try:
            parameters = inspect.signature(self.pool.send).parameters.values()
        except (AttributeError, TypeError, ValueError):
            return {}
        supports_progress = any(
            parameter.name == "progress_callback" or parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in parameters
        )
        if not supports_progress:
            return {}
        return {"progress_callback": self.progress.callback(job, stage)}

    async def run_once(self, auth):
        if self.safety is not None and self.safety.status().paused:
            return False
        job = self.claim()
        if not job:
            return False

        self.progress.update(job, "claimed", 0)
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

        self.progress.update(job, "preparing", 0)
        try:
            attempt = start_attempt(self.db, job["id"], account)
            attempt_id = int(attempt["id"])
        except Exception as exc:
            due = (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat(timespec="seconds")
            self.defer_job(job, due, f"delivery ledger unavailable before send: {exc}")
            return True

        try:
            media = json.loads(job["media_json"] or "[]")
            stage = "sending_text" if job["mode"] == "text" else "uploading"
            self.progress.update(job, stage, 0)
            ids = await self.pool.send(
                account,
                job["group_id"],
                job["caption"],
                media,
                job["mode"],
                job["topic_id"],
                **self._send_progress_kwargs(job, stage),
            )
            self.progress.update(job, "awaiting_confirmation", 100)
        except Exception as exc:
            kind, retry_at, permanent = classify_exception(exc)
            try:
                finish_attempt(self.db, attempt_id, "failed", error_kind=kind, error_text=str(exc))
            except Exception as ledger_exc:
                self._ledger_warning(job, account, f"Could not finalize failed delivery attempt #{attempt_id}: {ledger_exc}")
            self.finish_error(job, f"{kind}: {exc}", permanent=permanent, retry_at=retry_at, account=account, kind=kind)
            return True

        try:
            mark_acknowledged(self.db, attempt_id, ids)
        except Exception as exc:
            self.mark_post_send_uncertain(job, account, ids, exc, attempt_id)
            return True

        self.progress.update(job, "recording_delivery", 100)
        now = utcnow()
        interval = max(int(job.get("min_interval_seconds") or 0), int(job.get("campaign_interval") or 0))
        next_eligible = (datetime.now(timezone.utc) + timedelta(seconds=interval)).isoformat(timespec="seconds") if interval > 0 else None
        try:
            with self.db.connect() as con:
                changed = con.execute("UPDATE queue SET status='sent',account_key=?,attempts=attempts+1,telegram_message_ids=?,error_kind=NULL,last_error=NULL,resolved_at=?,updated_at=? WHERE id=? AND status='sending'",
                                      (account, json.dumps(ids), now, now, job["id"]))
                if changed.rowcount != 1:
                    raise RuntimeError("queue row was no longer in sending state after Telegram acknowledged delivery")
                con.execute("UPDATE destinations SET last_post_at=?,next_eligible_at=?,consecutive_failures=0,quarantine_until=NULL,updated_at=? WHERE group_id=?",
                            (now, next_eligible, now, job["group_id"]))
                con.execute("UPDATE accounts SET cooldown_until=NULL,consecutive_failures=0,last_error=NULL,last_success_at=?,last_heartbeat_at=?,health_score=MIN(100,health_score+2),updated_at=? WHERE account_key=?",
                            (now, now, now, account))
        except Exception as exc:
            self.mark_post_send_uncertain(job, account, ids, exc, attempt_id)
            return True

        try:
            finish_attempt(self.db, attempt_id, "sent", message_ids=ids)
        except Exception as exc:
            self._ledger_warning(job, account, f"Queue is SENT but delivery attempt #{attempt_id} could not be finalized: {exc}")

        try:
            record_content_sent(self.db, job["campaign_id"], job["group_id"], job["content_id"], now)
        except Exception as exc:
            self._ledger_warning(job, account, f"Send confirmed but content usage bookkeeping failed: {exc}")

        self.progress.update(job, "sent", 100)
        try:
            self.db.event("INFO", "send_success", f"Sent {job['campaign_id']} / {job['content_id']} to {job['group_name']}", account_key=account, group_id=job["group_id"], campaign_id=job["campaign_id"], details=json.dumps({"delivery_attempt_id": attempt_id, "telegram_message_ids": ids}))
        except Exception:
            pass
        return True

    def finish_error(self, job, error, permanent=False, retry_at=None, account=None, kind: str | None = None):
        now = utcnow()
        final_status = "failed"
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
                        final_status = "quarantined"
                    if self.notifier is not None:
                        self.notifier.emit("WARNING", "Destination quarantined", f"{job['group_name']} was quarantined after repeated failures.", dedupe_key=f"quarantine:{job['group_id']}", dedupe_window_seconds=86400)
            if account:
                cooldown = retry_at if kind == "flood_wait" else None
                con.execute('''UPDATE accounts SET consecutive_failures=consecutive_failures+1,last_error=?,last_failure_at=?,
                               cooldown_until=COALESCE(?,cooldown_until),health_score=MAX(0,health_score-?),last_heartbeat_at=?,updated_at=? WHERE account_key=?''',
                            (error[:1000], now, cooldown, 12 if kind in {'flood_wait','network'} else 6, now, now, account))
            if final_status != "quarantined":
                final_status = status
        self.progress.update(job, "retrying" if final_status == "retry" else final_status, 0, error=error[:300])
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
