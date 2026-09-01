from __future__ import annotations

import asyncio
import inspect
import json
import time
from datetime import datetime, timedelta, timezone

from .db import Database, utcnow
from .core import record_content_sent, _select_content, refresh_system_tags
from .telegram_io import classify_exception
from .time_rules import quiet_until


class Worker:
    def __init__(self, db: Database, pool, poll_seconds=5, timezone_name="Australia/Adelaide", min_send_gap_seconds=3, send_timeout_seconds=45, safety=None, notifier=None):
        self.db = db
        self.pool = pool
        self.poll_seconds = poll_seconds
        self.timezone_name = timezone_name
        self.min_send_gap_seconds = max(0, int(min_send_gap_seconds))
        self.send_timeout_seconds = max(15, int(send_timeout_seconds))
        self.safety = safety
        self.notifier = notifier
        self.stop_requested = False

    def set_phase(self, job, phase: str, percent: int, detail: str | None = None,
                  *, account: str | None = None, status: str | None = None,
                  progress_current: int | None = None, progress_total: int | None = None,
                  progress_unit: str | None = None):
        """Persist the live per-post pipeline phase and optional transfer counters.

        These columns are deliberately observable-only: progress readers never mutate
        queue state, and phase updates never create/retry a post.
        """
        now = utcnow()
        pct = max(0, min(100, int(percent)))
        current = max(0, int(progress_current)) if progress_current is not None else None
        total = max(0, int(progress_total)) if progress_total is not None else None
        unit = (str(progress_unit or "")[:24] or None)
        with self.db.connect() as con:
            sql = ("UPDATE queue SET phase=?,phase_percent=?,phase_detail=?,phase_updated_at=?,"
                   "progress_current=?,progress_total=?,progress_unit=?,updated_at=?")
            params: list[object] = [phase[:64], pct, (detail or "")[:500] or None, now,
                                    current, total, unit, now]
            if account is not None:
                sql += ",account_key=?"; params.append(account)
            if status is not None:
                sql += ",status=?"; params.append(status)
            sql += " WHERE id=?"; params.append(job["id"])
            con.execute(sql, params)
        job["phase"] = phase
        job["phase_percent"] = pct
        job["phase_detail"] = detail
        job["progress_current"] = current
        job["progress_total"] = total
        job["progress_unit"] = unit
        if account is not None:
            job["account_key"] = account
        if status is not None:
            job["status"] = status

    @staticmethod
    def _content_compatible(job) -> bool:
        mode = str(job.get("mode") or "").lower()
        if mode == "text":
            return bool(str(job.get("caption") or "").strip())
        if mode == "photo":
            try:
                media = json.loads(job.get("media_json") or "[]")
            except Exception:
                return False
            return isinstance(media, list) and 1 <= len(media) <= 10
        return False

    def ensure_compatible_content(self, job):
        """Repair a stale content/mode pairing before any Telegram request starts."""
        if self._content_compatible(job):
            return job
        with self.db.connect() as con:
            camp = con.execute("SELECT * FROM campaigns WHERE campaign_id=?", (job["campaign_id"],)).fetchone()
            if not camp:
                raise RuntimeError("campaign_missing")
            content_id = _select_content(con, camp, int(job["group_id"]), str(job.get("mode") or ""))
            row = con.execute("SELECT caption,media_json FROM content WHERE content_id=?", (content_id,)).fetchone()
            if not row:
                raise RuntimeError("compatible_content_missing")
            con.execute("UPDATE queue SET content_id=?,updated_at=? WHERE id=?", (content_id, utcnow(), job["id"]))
        old = job.get("content_id")
        job["content_id"] = content_id
        job["caption"] = row["caption"]
        job["media_json"] = row["media_json"]
        self.db.event("INFO", "content_rerouted", f"Content {old} -> {content_id} for {job.get('mode')} delivery",
                      group_id=job["group_id"], campaign_id=job["campaign_id"])
        return job

    async def _send_with_progress(self, account, job, media, upload_progress, stage_callback):
        """Call current or legacy pool.send implementations without weakening errors."""
        send = self.pool.send
        try:
            params = inspect.signature(send).parameters.values()
            supports_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params)
            names = {p.name for p in params}
        except (TypeError, ValueError):
            supports_kwargs = True
            names = {"progress_callback", "stage_callback"}
        if supports_kwargs or {"progress_callback", "stage_callback"}.issubset(names):
            return await send(account, job["group_id"], job["caption"], media, job["mode"], job["topic_id"],
                              progress_callback=upload_progress, stage_callback=stage_callback)
        return await send(account, job["group_id"], job["caption"], media, job["mode"], job["topic_id"])

    def _record_attempt(self, job, *, outcome: str, account: str | None = None, kind: str | None = None,
                        retry_at: str | None = None, duration_ms: int | None = None,
                        message_ids=None, details: str | None = None):
        with self.db.connect() as con:
            con.execute('''INSERT INTO delivery_attempts(created_at,queue_id,run_key,campaign_id,group_id,account_key,
                           attempt_number,outcome,error_kind,retry_at,duration_ms,telegram_message_ids,details)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                        (utcnow(), job["id"], job.get("run_key"), job["campaign_id"], job["group_id"], account,
                         int(job.get("attempts", 0)) + 1, outcome, kind, retry_at, duration_ms,
                         json.dumps(message_ids) if message_ids is not None else None, (details or "")[:1000] or None))

    def recover_interrupted_sends(self):
        """Never blindly retry a job that was in-flight when the process stopped.

        Telegram may have accepted it just before the local process died. Marking it
        uncertain avoids accidental duplicate posting.
        """
        now = utcnow()
        with self.db.connect() as con:
            rows = con.execute("SELECT id,campaign_id,group_id FROM queue WHERE status='sending'").fetchall()
            if rows:
                con.execute("""UPDATE queue SET status='uncertain',error_kind='interrupted_send',
                            last_error='process interrupted during send; verify before retry',phase='uncertain',phase_percent=95,
                            phase_detail='runtime stopped after Telegram send began; verification required',phase_updated_at=?,updated_at=?
                            WHERE status='sending'""", (now, now))
            processing = con.execute("SELECT id,campaign_id,group_id FROM queue WHERE status='processing'").fetchall()
            if processing:
                con.execute("""UPDATE queue SET status='retry',pass_no=pass_no+1,error_kind='interrupted_processing',
                            last_error='runtime stopped before Telegram send began; safe retry queued',due_at=?,
                            phase='retry_wait',phase_percent=35,phase_detail='safe pre-send recovery',phase_updated_at=?,updated_at=?
                            WHERE status='processing'""", (now, now, now))
        for r in rows:
            self.db.event("WARNING", "uncertain_send", "Process stopped while this job was sending; automatic retry suppressed", group_id=r["group_id"], campaign_id=r["campaign_id"])
        for r in processing:
            self.db.event("INFO", "processing_recovered", "Process stopped before Telegram send; same job moved to next retry pass", group_id=r["group_id"], campaign_id=r["campaign_id"])
        return len(rows) + len(processing)

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
        now = utcnow()
        with self.db.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute('''SELECT q.*, d.group_name, d.mode, d.topic_id, d.preferred_account,
                                        d.primary_access,d.secondary_access,d.quarantine_until,d.next_eligible_at,
                                        d.quiet_start,d.quiet_end,d.text_allowed,d.photo_allowed,d.capability_source,
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
                                 AND NOT EXISTS (SELECT 1 FROM queue qx
                                     WHERE qx.group_id=q.group_id AND qx.id<>q.id
                                       AND qx.status IN ('sending','uncertain'))
                                 AND q.id=(SELECT MIN(q3.id) FROM queue q3
                                     WHERE q3.group_id=q.group_id
                                       AND q3.status IN ('pending','retry','deferred','processing','sending','uncertain'))
                                 AND q.pass_no=(SELECT MIN(q2.pass_no) FROM queue q2
                                     WHERE q2.campaign_id=q.campaign_id
                                       AND (q2.run_key=q.run_key OR (q2.run_key IS NULL AND q.run_key IS NULL))
                                       AND q2.status IN ('pending','retry','deferred','processing','sending'))
                                 ORDER BY c.priority DESC,
                                          q.pass_no ASC,
                                          CASE q.status WHEN 'pending' THEN 0 WHEN 'deferred' THEN 1 WHEN 'retry' THEN 2 ELSE 3 END,
                                          q.due_at ASC, q.id ASC LIMIT 1''', (now, now, now, now, now)).fetchone()
            if not row:
                return None
            changed = con.execute("""UPDATE queue SET status='processing',phase='validating_destination',phase_percent=12,
                                  phase_detail='claimed by worker; no Telegram send started',phase_updated_at=?,updated_at=?
                                  WHERE id=? AND status IN ('pending','retry','deferred')""", (now, now, row["id"]))
            if changed.rowcount != 1:
                return None
            out = dict(row)
            out["status"] = "processing"; out["phase"] = "validating_destination"; out["phase_percent"] = 12
            return out

    def _account_rows(self):
        with self.db.connect() as con:
            rows = con.execute("SELECT * FROM accounts").fetchall()
        return {r["account_key"]: dict(r) for r in rows}

    def _account_capabilities(self, group_id: int) -> dict[str, dict]:
        with self.db.connect() as con:
            rows = con.execute(
                "SELECT account_key,text_allowed,photo_allowed,source,observed_at FROM destination_account_capabilities WHERE group_id=?",
                (int(group_id),),
            ).fetchall()
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
            caps = self._account_capabilities(int(job["group_id"])).get(key, {}) if job.get("group_id") is not None else {}
            mode = str(job.get("mode") or "").lower()
            if mode == "photo" and caps.get("photo_allowed") == 0:
                continue
            if mode == "text" and caps.get("text_allowed") == 0:
                continue
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

    def defer_job(self, job, due_at: str, reason: str, account: str | None = None, *, kind: str = "deferred"):
        now = utcnow()
        with self.db.connect() as con:
            con.execute("""UPDATE queue SET status='deferred',account_key=COALESCE(?,account_key),due_at=?,error_kind=?,last_error=?,
                        pass_no=pass_no+1,deferral_count=deferral_count+1,phase='deferred',phase_percent=35,
                        phase_detail=?,phase_updated_at=?,updated_at=? WHERE id=?""",
                        (account, due_at, kind, reason[:1000], reason[:500], now, now, job["id"]))
        job["pass_no"] = int(job.get("pass_no") or 1) + 1
        job["status"] = "deferred"
        self.db.event("INFO", "job_deferred", reason[:800], account_key=account, group_id=job["group_id"], campaign_id=job["campaign_id"])

    def defer_format_fallback(self, job, kind: str, account: str | None = None) -> bool:
        """Learn format restrictions without over-generalising one account's rights.

        V5 first tries the same format through another accessible account. Only when
        every observed accessible account rejects that format does it change the
        destination-wide mode and select compatible fallback content. The same queue
        row is always reused.
        """
        current_mode = str(job.get("mode") or "").lower()
        if kind not in {"media_forbidden", "text_forbidden"}:
            return False
        target_mode = "text" if kind == "media_forbidden" else "photo"
        current_cap_col = "photo_allowed" if kind == "media_forbidden" else "text_allowed"
        target_cap_col = "text_allowed" if target_mode == "text" else "photo_allowed"
        now = utcnow(); due = (datetime.now(timezone.utc) + timedelta(seconds=max(3, self.min_send_gap_seconds))).isoformat(timespec="seconds")
        outcome = None; message = None
        try:
            with self.db.connect() as con:
                if account:
                    existing = con.execute("SELECT text_allowed,photo_allowed FROM destination_account_capabilities WHERE group_id=? AND account_key=?", (job["group_id"],account)).fetchone()
                    text_val = existing["text_allowed"] if existing else None
                    photo_val = existing["photo_allowed"] if existing else None
                    if current_cap_col == "text_allowed": text_val = 0
                    else: photo_val = 0
                    con.execute("""INSERT INTO destination_account_capabilities(group_id,account_key,text_allowed,photo_allowed,source,observed_at)
                                   VALUES(?,?,?,?,?,?) ON CONFLICT(group_id,account_key) DO UPDATE SET
                                   text_allowed=excluded.text_allowed,photo_allowed=excluded.photo_allowed,source=excluded.source,observed_at=excluded.observed_at""",
                                (job["group_id"],account,text_val,photo_val,"telegram_error",now))

                # Can another accessible account still send the current format? Unknown
                # capability is allowed here and will be verified by Telegram on send.
                access = {"primary": bool(job.get("primary_access")), "secondary": bool(job.get("secondary_access"))}
                alternatives=[]
                for key in ("primary","secondary"):
                    if key == account or not access.get(key): continue
                    cap = con.execute(f"SELECT {current_cap_col} allowed FROM destination_account_capabilities WHERE group_id=? AND account_key=?",(job["group_id"],key)).fetchone()
                    if cap is None or cap["allowed"] != 0:
                        alternatives.append(key)
                if alternatives:
                    outcome="deferred"
                    message=f"{account or 'selected account'} rejected {current_mode}; retrying same payload through another accessible account"
                    con.execute("""UPDATE queue SET status='deferred',account_key=NULL,due_at=?,error_kind=?,last_error=?,
                                   pass_no=pass_no+1,deferral_count=deferral_count+1,phase='account_format_fallback',phase_percent=38,
                                   phase_detail=?,phase_updated_at=?,progress_current=NULL,progress_total=NULL,progress_unit=NULL,updated_at=? WHERE id=?""",
                                (due,kind,message,message,now,now,job["id"]))
                else:
                    # Every accessible account is now known to reject the current mode.
                    con.execute(f"UPDATE destinations SET {current_cap_col}=0,capability_source='telegram_account_union',capability_updated_at=?,updated_at=? WHERE group_id=?",(now,now,job["group_id"]))
                    dest=con.execute("SELECT text_allowed,photo_allowed FROM destinations WHERE group_id=?",(job["group_id"],)).fetchone()
                    target_known_forbidden=bool(dest and dest[target_cap_col] == 0)
                    if target_known_forbidden:
                        outcome="no_supported_format"; message="Telegram rejects both text and photo delivery across accessible accounts; destination requires review"
                        con.execute("UPDATE destinations SET enabled=0,needs_review=1,updated_at=? WHERE group_id=?",(now,job["group_id"]))
                        con.execute("""UPDATE queue SET status='failed',account_key=NULL,error_kind='no_supported_format',last_error=?,resolved_at=?,
                                       phase='failed',phase_percent=100,phase_detail=?,phase_updated_at=?,updated_at=? WHERE id=?""",
                                    (message,now,message,now,now,job["id"]))
                    else:
                        camp=con.execute("SELECT * FROM campaigns WHERE campaign_id=?",(job["campaign_id"],)).fetchone()
                        try:
                            content_id=_select_content(con,camp,int(job["group_id"]),target_mode) if camp else None
                        except RuntimeError as exc:
                            content_id=None; message=f"Telegram requires {target_mode} delivery but campaign has no compatible content: {exc}"
                        if not content_id:
                            outcome="no_compatible_fallback"; message=message or f"no compatible {target_mode} content"
                            con.execute("""UPDATE queue SET status='failed',account_key=NULL,error_kind='no_compatible_fallback',last_error=?,resolved_at=?,
                                           phase='failed',phase_percent=100,phase_detail=?,phase_updated_at=?,updated_at=? WHERE id=?""",
                                        (message,now,message,now,now,job["id"]))
                        else:
                            outcome="deferred"; message=f"all accessible accounts rejected {current_mode}; learned {target_mode}-only delivery"
                            con.execute(f"UPDATE destinations SET mode=?,{target_cap_col}=1,capability_source='telegram_account_union',capability_updated_at=?,updated_at=? WHERE group_id=?",(target_mode,now,now,job["group_id"]))
                            con.execute("""UPDATE queue SET status='deferred',content_id=?,account_key=NULL,due_at=?,error_kind=?,last_error=?,
                                           pass_no=pass_no+1,deferral_count=deferral_count+1,phase='format_fallback',phase_percent=38,phase_detail=?,
                                           phase_updated_at=?,progress_current=NULL,progress_total=NULL,progress_unit=NULL,updated_at=? WHERE id=?""",
                                        (content_id,due,kind,message,message,now,now,job["id"]))
            refresh_system_tags(self.db)
            if outcome == "deferred":
                self._record_attempt(job,outcome="deferred",account=account,kind=kind,retry_at=due,details=message)
                self.db.event("INFO","destination_mode_learned",message or kind,account_key=account,group_id=job["group_id"],campaign_id=job["campaign_id"])
            elif outcome in {"no_supported_format","no_compatible_fallback"}:
                self._record_attempt(job,outcome="failed",account=account,kind=outcome,details=message)
                self.db.event("WARNING", "destination_failure", message or outcome, account_key=account, group_id=job["group_id"], campaign_id=job["campaign_id"])
            return outcome is not None
        except Exception as exc:
            self.db.event("WARNING","format_fallback_failed",str(exc)[:800],account_key=account,group_id=job["group_id"],campaign_id=job["campaign_id"])
            return False

    def predictive_timing_hold(self, job):
        """Return a future safe time learned from prior Telegram timing signals.

        This is advisory but conservative: it only delays a send and never advances one.
        The same queue row is reused, preserving the one-obligation invariant.
        """
        now = datetime.now(timezone.utc)
        with self.db.connect() as con:
            row = con.execute("SELECT next_safe_at,observed_min_interval_seconds FROM destination_timing_profiles WHERE group_id=?", (job["group_id"],)).fetchone()
            d = con.execute("SELECT last_post_at,next_eligible_at,min_interval_seconds FROM destinations WHERE group_id=?", (job["group_id"],)).fetchone()
        candidates=[]
        for raw in ((row["next_safe_at"] if row else None), (d["next_eligible_at"] if d else None)):
            if raw:
                try:
                    dt=datetime.fromisoformat(str(raw).replace("Z","+00:00")); dt=dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
                    candidates.append(dt)
                except Exception:
                    pass
        observed=int((row["observed_min_interval_seconds"] if row else 0) or 0)
        if d and d["last_post_at"] and observed>0:
            try:
                last=datetime.fromisoformat(str(d["last_post_at"]).replace("Z","+00:00")); last=last if last.tzinfo else last.replace(tzinfo=timezone.utc)
                candidates.append(last+timedelta(seconds=observed))
            except Exception:
                pass
        future=[x for x in candidates if x>now]
        return max(future) if future else None

    async def run_once(self, auth):
        if self.safety is not None and self.safety.status().paused:
            return False
        job = self.claim()
        if not job:
            return False

        started = time.monotonic()
        self.set_phase(job, "checking_timing", 18, "checking quiet hours and predictive destination eligibility")
        predicted = self.predictive_timing_hold(job)
        if predicted:
            self.defer_job(job, predicted.isoformat(timespec="seconds"), "V6 predictive timing hold: learned destination window", kind="predictive_timing")
            return True
        try:
            quiet_end = quiet_until(datetime.now(timezone.utc), job.get("quiet_start"), job.get("quiet_end"), self.timezone_name)
        except Exception as exc:
            self.finish_error(job, f"quiet_hours_invalid: {exc}", permanent=True, kind="quiet_hours_invalid")
            return True
        if quiet_end:
            self.defer_job(job, quiet_end.isoformat(timespec="seconds"), "destination quiet hours", kind="quiet_hours")
            return True

        self.set_phase(job, "validating_content", 25, f"checking {job.get('mode')} payload compatibility")
        try:
            self.ensure_compatible_content(job)
        except Exception as exc:
            self.finish_error(job, f"content_incompatible: {exc}", permanent=True, kind="content_incompatible")
            return True

        self.set_phase(job, "selecting_account", 32, "selecting an authorized account with destination access")
        account, defer_until, reason = self.choose_account(job, auth)
        if not account:
            if defer_until:
                self.defer_job(job, defer_until, reason or "account cooldown", kind=reason or "account_cooldown")
            else:
                due = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(timespec="seconds")
                self.defer_job(job, due, reason or "no_authorized_account", kind=reason or "no_authorized_account")
                if self.notifier is not None and reason == "no_authorized_account":
                    self.notifier.emit("IMPORTANT", "No Telegram account available", f"Job #{job['id']} deferred because no authorized account can reach {job['group_name']}.", dedupe_key="no_authorized_account", dedupe_window_seconds=3600)
            return True

        try:
            media = json.loads(job["media_json"] or "[]")
            self.set_phase(job, "preparing_payload", 42,
                           f"{len(media)} media item(s)" if job.get("mode") == "photo" else "text-only payload",
                           account=account)

            last_upload_pct = {"value": -1}
            def stage_callback(phase, percent, detail=None):
                self.set_phase(job, str(phase), int(percent), detail, account=account)

            def upload_progress(current, total):
                try:
                    ratio = 0.0 if not total else max(0.0, min(1.0, float(current) / float(total)))
                    upload_pct = int(round(ratio * 100))
                    # Throttle DB writes to 5% upload steps while still showing a
                    # genuinely moving per-post bar for large albums.
                    bucket = upload_pct // 5
                    if bucket == last_upload_pct["value"]:
                        return
                    last_upload_pct["value"] = bucket
                    overall = 55 + int(round(ratio * 30))
                    self.set_phase(job, "uploading_media", overall, f"upload {upload_pct}%", account=account,
                                   progress_current=int(current or 0), progress_total=int(total or 0), progress_unit="bytes")
                except Exception:
                    pass

            # Sending is the ambiguity boundary. A crash before this state is a
            # safe retry; a crash after it becomes UNCERTAIN to prevent duplicates.
            self.set_phase(job, "starting_telegram_send", 52, "Telegram request boundary", account=account, status="sending")
            try:
                ids = await asyncio.wait_for(
                    self._send_with_progress(account, job, media, upload_progress, stage_callback),
                    timeout=self.send_timeout_seconds,
                )
            except asyncio.TimeoutError as exc:
                # A timed-out MTProto media request has an ambiguous delivery outcome: Telegram
                # may have accepted the album even though the local coroutine did not receive the
                # acknowledgement. Move it out of the fast lane as UNCERTAIN and continue with
                # untouched destinations; never blindly resend it.
                self.finish_error(
                    job,
                    f"send_timeout_uncertain: no conclusive Telegram acknowledgement within {self.send_timeout_seconds}s",
                    permanent=False,
                    retry_at=None,
                    account=account,
                    kind="send_timeout_uncertain",
                    duration_ms=int((time.monotonic() - started) * 1000),
                )
                return True
            self.set_phase(job, "telegram_acknowledged", 95, f"Telegram returned {len(ids)} message id(s)", account=account)
            now = utcnow()
            interval = max(int(job.get("min_interval_seconds") or 0), int(job.get("campaign_interval") or 0))
            next_eligible = (datetime.now(timezone.utc) + timedelta(seconds=interval)).isoformat(timespec="seconds") if interval > 0 else None
            with self.db.connect() as con:
                con.execute("""UPDATE queue SET status='sent',account_key=?,attempts=attempts+1,telegram_message_ids=?,error_kind=NULL,last_error=NULL,
                            resolved_at=?,phase='sent',phase_percent=100,phase_detail='Telegram acknowledgement recorded',phase_updated_at=?,
                            progress_current=NULL,progress_total=NULL,progress_unit=NULL,updated_at=? WHERE id=?""",
                            (account, json.dumps(ids), now, now, now, job["id"]))
                con.execute("UPDATE destinations SET last_post_at=?,next_eligible_at=?,consecutive_failures=0,quarantine_until=NULL,updated_at=? WHERE group_id=?",
                            (now, next_eligible, now, job["group_id"]))
                con.execute("UPDATE accounts SET cooldown_until=NULL,consecutive_failures=0,last_error=NULL,last_success_at=?,last_heartbeat_at=?,health_score=MIN(100,health_score+2),updated_at=? WHERE account_key=?",
                            (now, now, now, account))
                # V4 legacy-queue guard: once one post is definitively SENT, suppress any
                # other pre-send unresolved rows for the same group. Modern enqueue logic
                # already prevents these rows; this protects upgrades from old stacked queues.
                con.execute("""UPDATE queue SET status='cancelled',error_kind='duplicate_suppressed',
                            last_error='V4 anti-spam: another post for this group was already sent',resolved_at=?,
                            phase='cancelled',phase_percent=100,phase_detail='duplicate unresolved post suppressed after definitive send',
                            phase_updated_at=?,updated_at=?
                            WHERE group_id=? AND id<>? AND status IN ('pending','retry','deferred','processing')""",
                            (now, now, now, job["group_id"], job["id"]))
            record_content_sent(self.db, job["campaign_id"], job["group_id"], job["content_id"], now)
            self._record_attempt(job, outcome="sent", account=account,
                                 duration_ms=int((time.monotonic() - started) * 1000), message_ids=ids)
            self.db.event("INFO", "send_success", f"Sent {job['campaign_id']} / {job['content_id']} to {job['group_name']}", account_key=account, group_id=job["group_id"], campaign_id=job["campaign_id"])
            # Fast-pass pacing is deliberate rather than queue-deferring the next healthy job.
            # This keeps clean destinations flowing a few seconds apart while preserving the
            # per-account Telegram pacing guard.
            if self.min_send_gap_seconds:
                await asyncio.sleep(self.min_send_gap_seconds)
        except Exception as exc:
            kind, retry_at, permanent = classify_exception(exc)
            if kind in {"media_forbidden", "text_forbidden"} and self.defer_format_fallback(job, kind, account):
                return True
            self.finish_error(job, f"{kind}: {exc}", permanent=permanent, retry_at=retry_at, account=account, kind=kind,
                              duration_ms=int((time.monotonic() - started) * 1000))
        return True

    def _record_timing_profile(self, job, kind: str | None, retry_at: str | None):
        if kind not in {"slow_mode", "flood_wait", "worker_busy"}:
            return
        now_dt = datetime.now(timezone.utc)
        wait_seconds = None
        if retry_at:
            try:
                dt = datetime.fromisoformat(str(retry_at).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                wait_seconds = max(0, int((dt - now_dt).total_seconds()))
            except Exception:
                wait_seconds = None
        now = utcnow()
        with self.db.connect() as con:
            con.execute("""INSERT INTO destination_timing_profiles
                (group_id,slow_mode_events,flood_wait_events,transient_events,last_wait_seconds,max_wait_seconds,observed_min_interval_seconds,next_safe_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(group_id) DO UPDATE SET
                slow_mode_events=destination_timing_profiles.slow_mode_events+excluded.slow_mode_events,
                flood_wait_events=destination_timing_profiles.flood_wait_events+excluded.flood_wait_events,
                transient_events=destination_timing_profiles.transient_events+excluded.transient_events,
                last_wait_seconds=COALESCE(excluded.last_wait_seconds,destination_timing_profiles.last_wait_seconds),
                max_wait_seconds=MAX(destination_timing_profiles.max_wait_seconds,COALESCE(excluded.last_wait_seconds,0)),
                observed_min_interval_seconds=MAX(destination_timing_profiles.observed_min_interval_seconds,COALESCE(excluded.last_wait_seconds,0)),
                next_safe_at=COALESCE(excluded.next_safe_at,destination_timing_profiles.next_safe_at),
                updated_at=excluded.updated_at""",
                (job["group_id"], int(kind=="slow_mode"), int(kind=="flood_wait"), int(kind=="worker_busy"),
                 wait_seconds, int(wait_seconds or 0), int(wait_seconds or 0), retry_at, now))

    def finish_error(self, job, error, permanent=False, retry_at=None, account=None, kind: str | None = None,
                     duration_ms: int | None = None):
        now = utcnow()
        self._record_timing_profile(job, kind, retry_at)
        with self.db.connect() as con:
            # Telegram FloodWait/SlowMode are timing rules rather than failed send
            # attempts. Preserve retry budget so long cooldowns cannot turn a
            # healthy job into a false permanent failure.
            timing_rule = kind in {"slow_mode", "flood_wait", "worker_busy"}
            uncertain_ack = kind in {"uncertain_telegram_ack", "send_timeout_uncertain"}
            attempts = int(job.get("attempts", 0)) + (0 if timing_rule else 1)
            max_attempts = int(job.get("max_attempts", 4))
            if uncertain_ack:
                # A response-level Telegram failure after SendMultiMediaRequest may mean the
                # album was accepted but the acknowledgement was lost. Never auto-retry this
                # state: doing so can duplicate an already-delivered album.
                status, due = "uncertain", job["due_at"]
            elif permanent or (not timing_rule and attempts >= max_attempts):
                status, due = "failed", job["due_at"]
            elif timing_rule:
                status = "deferred"
                due = retry_at or (datetime.now(timezone.utc) + timedelta(seconds=120)).isoformat(timespec="seconds")
            else:
                status = "retry"
                due = retry_at or (datetime.now(timezone.utc) + timedelta(seconds=120)).isoformat(timespec="seconds")
            phase = {
                "uncertain": "uncertain", "failed": "failed", "deferred": "deferred", "retry": "retry_wait",
            }.get(status, status)
            phase_pct = {"uncertain": 95, "failed": 100, "deferred": 35, "retry": 35}.get(status, 35)
            next_pass = int(job.get("pass_no") or 1) + (1 if status in {"deferred", "retry"} else 0)
            con.execute("""UPDATE queue SET status=?,account_key=?,attempts=?,due_at=?,error_kind=?,last_error=?,resolved_at=?,
                        pass_no=?,deferral_count=deferral_count+?,phase=?,phase_percent=?,phase_detail=?,phase_updated_at=?,
                        progress_current=NULL,progress_total=NULL,progress_unit=NULL,updated_at=? WHERE id=?""",
                        (status, account, attempts, due, kind, error[:1000], now if status in {'failed','quarantined','cancelled','expired'} else None,
                         next_pass, 1 if status == "deferred" else 0, phase, phase_pct, error[:500], now, now, job["id"]))
            # Slow mode is a destination timing rule, not a broken destination.
            if kind == "slow_mode" and retry_at:
                con.execute("UPDATE destinations SET next_eligible_at=?,updated_at=? WHERE group_id=?", (retry_at, now, job["group_id"]))
            penalize_destination = kind not in {"network", "worker_busy", "uncertain_telegram_ack", "send_timeout_uncertain", "flood_wait", "slow_mode", "media_forbidden", "text_forbidden", "no_authorized_account", "account_disabled", "account_cooldown", "account_cooldown_or_pacing"}
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
                # Destination slow-mode and Telegram worker-busy are not account-health failures.
                # Preserve account score/attempt budget for these platform timing conditions.
                if kind not in {"slow_mode", "worker_busy", "uncertain_telegram_ack", "send_timeout_uncertain", "media_forbidden", "text_forbidden"}:
                    cooldown = retry_at if kind == "flood_wait" else None
                    con.execute('''UPDATE accounts SET consecutive_failures=consecutive_failures+1,last_error=?,last_failure_at=?,
                                   cooldown_until=COALESCE(?,cooldown_until),health_score=MAX(0,health_score-?),last_heartbeat_at=?,updated_at=? WHERE account_key=?''',
                                (error[:1000], now, cooldown, 12 if kind in {'flood_wait','network'} else 6, now, now, account))
        local_failure_kinds = {
            "ChatWriteForbiddenError", "ChatSendMediaForbiddenError", "ChatSendPhotosForbiddenError",
            "ChatSendPlainForbiddenError", "UserBannedInChannelError", "ChannelPrivateError",
            "ChatAdminRequiredError", "PeerIdInvalidError", "TopicDeletedError", "MessageIdInvalidError",
            "invalid_topic", "invalid_media", "content_incompatible", "quiet_hours_invalid",
            "no_supported_format", "media_forbidden", "text_forbidden",
        }
        if kind in {"uncertain_telegram_ack", "send_timeout_uncertain"}:
            event_type = "uncertain_send"
        elif timing_rule:
            # Expected Telegram timing/back-pressure is not a failed send outcome.
            event_type = kind or "send_timing"
        elif permanent and kind in local_failure_kinds:
            # One broken/restricted group must not pause healthy destinations globally.
            event_type = "destination_failure"
        else:
            # Network/auth/unknown failures remain breaker-relevant because they can be systemic.
            event_type = "send_failure"
        self._record_attempt(job, outcome=status, account=account, kind=kind, retry_at=due if status in {"retry", "deferred"} else None,
                             duration_ms=duration_ms, details=error)
        self.db.event("ERROR" if permanent else "WARNING", event_type, error[:800], account_key=account, group_id=job["group_id"], campaign_id=job["campaign_id"])

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
