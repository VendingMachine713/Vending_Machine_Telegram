from __future__ import annotations

from . import __version__
import asyncio
import json
from datetime import datetime, timezone

from .core import validate
from .account_guard import assert_distinct_authorized_accounts
from .scheduler import Scheduler
from .safety import SafetyController
from .worker import Worker
from .destination_sync import sync_destinations
from .notifications import NotificationManager
from .watchdog import Watchdog, network_available
from .maintenance import cleanup_storage, prune_database, database_integrity


class AutoPosterService:
    """Runs scheduler + queue worker + recovery + watchdog + optional admin control bot."""

    def __init__(self, db, pool, settings, poll_seconds=5, scheduler_seconds=15):
        self.db = db
        self.pool = pool
        self.settings = settings
        self.poll_seconds = max(1, int(poll_seconds))
        self.scheduler_seconds = max(5, int(scheduler_seconds))
        self.notifier = NotificationManager(db)
        self.safety = SafetyController(
            db,
            failure_threshold=settings.circuit_breaker_failures,
            window_minutes=settings.circuit_breaker_window_minutes,
            pause_minutes=settings.circuit_breaker_pause_minutes,
            failure_ratio=settings.circuit_breaker_failure_ratio,
        )
        self.worker = Worker(
            db,
            pool,
            poll_seconds=self.poll_seconds,
            timezone_name=settings.timezone,
            min_send_gap_seconds=settings.min_send_gap_seconds,
            send_timeout_seconds=settings.send_timeout_seconds,
            safety=self.safety,
            notifier=self.notifier,
        )
        limits = {
            "max_queue_size": settings.max_queue_size,
            "max_pending_per_campaign": settings.max_pending_per_campaign,
            "max_pending_per_destination": settings.max_pending_per_destination,
        }
        self.scheduler = Scheduler(db, limits=limits)
        self.watchdog = Watchdog(db, stale_seconds=settings.heartbeat_stale_seconds, notifier=self.notifier)
        self.stop_requested = False
        self.admin_task = None
        self.network_ok = True
        self._reconnect_backoff = settings.reconnect_initial_seconds

    def _auto_backup(self):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        dst = self.settings.backup_dir / f"smart_autoposter_auto_{stamp}.sqlite3"
        self.db.backup_to(dst)
        self.db.event("INFO", "auto_backup", f"Automatic database backup created: {dst.name}")
        keep = max(1, int(self.settings.auto_backup_keep))
        backups = sorted(self.settings.backup_dir.glob("smart_autoposter_auto_*.sqlite3"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in backups[keep:]:
            try: old.unlink()
            except OSError: pass
        self.watchdog.beat("backup", "ok", {"path": str(dst)})
        return dst

    def _daily_summary(self):
        from .operations import operational_summary
        summary = operational_summary(self.db, self.settings.daily_summary_hours)
        print("[DAILY SUMMARY] " + json.dumps(summary, ensure_ascii=False, default=str))
        self.db.event("INFO", "daily_summary", "Automatic operational summary", details=json.dumps(summary, default=str))
        q = summary.get("queue_status", {})
        dest = summary.get("destinations", {})
        text = (
            f"Sent: {q.get('sent',0)} | Failed: {q.get('failed',0)} | Deferred: {q.get('deferred',0)}\n"
            f"Active queue: {summary.get('active_queue',0)} | Success: {summary.get('success_rate',100):.2f}%\n"
            f"Destinations enabled: {dest.get('enabled',0)} | Review: {dest.get('review',0)} | Quarantined: {dest.get('quarantined',0)}"
        )
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.notifier.emit("IMPORTANT", "Smart Auto Poster daily report", text, dedupe_key=f"daily:{day}", event_type="daily_report_ready")
        return summary

    def _weekly_summary(self):
        from .analytics import analytics_snapshot
        data = analytics_snapshot(self.db, self.settings.weekly_summary_hours)
        queue = data.get("queue_status", {}) if isinstance(data, dict) else {}
        text = (
            f"Weekly window: {self.settings.weekly_summary_hours}h\n"
            f"Sent: {queue.get('sent',0)} | Failed: {queue.get('failed',0)} | Deferred: {queue.get('deferred',0)}\n"
            f"Campaigns tracked: {len(data.get('campaigns', [])) if isinstance(data, dict) else 0} | "
            f"Accounts tracked: {len(data.get('accounts', [])) if isinstance(data, dict) else 0}"
        )
        week = datetime.now(timezone.utc).strftime("%G-W%V")
        self.notifier.emit("IMPORTANT", "Smart Auto Poster weekly report", text,
                           dedupe_key=f"weekly:{week}", event_type="weekly_report_ready")
        self.db.event("INFO", "weekly_summary", "Automatic weekly analytics summary", details=json.dumps(data, default=str))
        return data

    def _maintenance(self):
        integrity = database_integrity(self.db)
        cleanup = cleanup_storage(
            log_dir=self.settings.log_dir, backup_dir=self.settings.backup_dir, diagnostics_dir=self.settings.diagnostics_dir,
            log_days=self.settings.log_retention_days, backup_keep=self.settings.auto_backup_keep,
        )
        pruned = prune_database(self.db, event_days=self.settings.event_retention_days, queue_days=self.settings.queue_history_days)
        details = {"integrity": integrity, "cleanup": cleanup, "database_prune": pruned}
        self.watchdog.beat("maintenance", "ok" if integrity["ok"] else "error", details)
        if not integrity["ok"]:
            self.notifier.emit("CRITICAL", "Database integrity problem", json.dumps(integrity)[:3000], dedupe_key="db_integrity_problem")
        return details

    async def _refresh_auth(self, previous: dict) -> dict:
        try:
            current = await self.pool.authorization()
            assert_distinct_authorized_accounts(current)
            self.worker.sync_accounts(current, self.settings.sessions)
            self.watchdog.beat("telegram_auth", "ok", current)
            if current != previous:
                self.db.event("INFO", "authorization_refresh", "Telegram account authorization state refreshed", details=json.dumps(current))
                print("[HEALTH] Authorization refreshed:", json.dumps(current))
            unauthorized = [k for k, v in current.items() if not v.get("authorized")]
            if unauthorized:
                self.notifier.emit("IMPORTANT", "Telegram account authorization", "Not authorized: " + ", ".join(unauthorized), dedupe_key="unauthorized:" + ",".join(unauthorized))
            return current
        except Exception as exc:
            self.watchdog.beat("telegram_auth", "error", str(exc))
            self.db.event("WARNING", "authorization_refresh_failed", str(exc)[:800])
            print(f"[WARNING] Authorization refresh failed: {exc}")
            return previous

    async def _recover_network(self, auth: dict) -> dict:
        ok = await asyncio.to_thread(network_available, self.settings.network_check_host, self.settings.network_check_port, 4.0)
        if ok:
            if not self.network_ok:
                print("[NETWORK] Connectivity restored; reconnecting Telegram clients")
                self.db.event("INFO", "network_restored", "Internet connectivity restored")
                self.watchdog.beat("network", "ok", {"host": self.settings.network_check_host})
                try:
                    await self.pool.reconnect()
                    auth = await self._refresh_auth(auth)
                    self._reconnect_backoff = self.settings.reconnect_initial_seconds
                    self.notifier.emit("WARNING", "Connectivity restored", "Telegram clients reconnected after an outage.", dedupe_key=f"network-restored:{datetime.now(timezone.utc).strftime('%Y%m%d%H')}")
                except Exception as exc:
                    self.db.event("WARNING", "network_reconnect_failed", str(exc)[:800])
            self.network_ok = True
            return auth

        if self.network_ok:
            self.db.event("WARNING", "network_down", f"Connectivity check failed: {self.settings.network_check_host}:{self.settings.network_check_port}")
            self.notifier.emit("IMPORTANT", "Internet connection unavailable", "Outbound posting is temporarily paused; queue state is preserved.", dedupe_key="network-down", dedupe_window_seconds=3600)
        self.network_ok = False
        self.watchdog.beat("network", "error", {"host": self.settings.network_check_host, "retry_seconds": self._reconnect_backoff})
        self._reconnect_backoff = min(self.settings.reconnect_max_seconds, max(self.settings.reconnect_initial_seconds, self._reconnect_backoff * 2))
        return auth

    async def _start_admin(self):
        if not self.settings.admin_bot_enabled:
            print("[ADMIN BOT] Disabled (set ADMIN_BOT_TOKEN + ADMIN_USER_IDS to enable).")
            return None
        from .admin_bot import TelegramAdminController
        controller = TelegramAdminController(self.db, self.settings, self.safety)
        task = await controller.start_background()
        print("[ADMIN BOT] Telegram control centre connecting...")
        try:
            await controller.wait_until_ready(timeout_seconds=30)
        except Exception as exc:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except BaseException:
                    pass
            self.db.event("ERROR", "admin_bot_start_failed", str(exc)[:800])
            self.notifier.emit("IMPORTANT", "Admin bot failed to start", str(exc)[:1000], dedupe_key="admin-bot-start-failed", dedupe_window_seconds=3600)
            raise RuntimeError(f"Configured Telegram Admin Bot failed managed startup: {exc}") from exc
        print("[ADMIN BOT] Telegram control centre connected and heartbeat verified.")
        return task

    async def run(self):
        problems = validate(self.db)
        if problems:
            raise RuntimeError("Pre-flight validation failed:\n - " + "\n - ".join(problems))
        integrity = database_integrity(self.db)
        if not integrity["ok"]:
            raise RuntimeError("Database integrity check failed before service start")

        auth = await self.pool.authorization()
        print("Authorization:", json.dumps(auth))
        assert_distinct_authorized_accounts(auth)
        self.worker.sync_accounts(auth, self.settings.sessions)
        recovered = self.worker.recover_interrupted_sends()
        if recovered:
            print(f"[RECOVERY] {recovered} interrupted send(s) marked UNCERTAIN")
        if not any(x.get("authorized") for x in auth.values()):
            raise RuntimeError("No authorized Telegram user sessions")

        self.watchdog.beat("service", "ok", {"started_at": datetime.now(timezone.utc).isoformat()})
        self.watchdog.beat("scheduler", "idle")
        self.watchdog.beat("worker", "idle")
        self.admin_task = await self._start_admin()
        print(f"[RUNNING] Smart Auto Poster V{__version__} active (scheduler + worker + recovery + watchdog). Ctrl+C to stop.")
        loop = asyncio.get_running_loop()
        last_schedule = 0.0
        last_safety = 0.0
        last_auth_refresh = loop.time()
        last_backup = loop.time()
        last_rescan = loop.time()
        last_summary = loop.time()
        last_weekly = loop.time()
        last_watchdog = 0.0
        last_network = 0.0
        last_maintenance = loop.time()
        last_pause_message = 0.0
        safety_interval = 10.0

        try:
            while not self.stop_requested:
                now = loop.time()
                self.watchdog.beat("service", "ok")

                if self.settings.admin_bot_enabled and self.admin_task and self.admin_task.done():
                    try:
                        exc = self.admin_task.exception()
                    except BaseException:
                        exc = None
                    self.db.event("WARNING", "admin_bot_stopped", str(exc or "Admin bot task stopped")[:800])
                    self.notifier.emit("IMPORTANT", "Admin bot stopped", str(exc or "The Telegram admin task stopped and is being restarted."),
                                       dedupe_key="admin-bot-stopped", dedupe_window_seconds=3600)
                    self.admin_task = await self._start_admin()

                if now - last_network >= self.settings.watchdog_seconds:
                    auth = await self._recover_network(auth)
                    last_network = now

                if now - last_schedule >= self.scheduler_seconds:
                    try:
                        results = self.scheduler.tick()
                        self.watchdog.beat("scheduler", "ok", {"runs": len(results)})
                        for result in results:
                            print(f"[SCHEDULE] {result['campaign_id']}: inserted={result['inserted']} duplicates={result['duplicates']}")
                        from .operations import finalize_cycle_limited_campaigns
                        finalized = finalize_cycle_limited_campaigns(self.db, actor="scheduler")
                        if finalized:
                            print(f"[SCHEDULE] Archived {finalized} cycle-limited campaign(s) after queue drain")
                    except Exception as exc:
                        self.watchdog.beat("scheduler", "error", str(exc))
                        self.db.event("ERROR", "scheduler_loop_error", str(exc)[:800])
                        self.notifier.emit("IMPORTANT", "Scheduler error", str(exc)[:1200], dedupe_key=f"scheduler:{type(exc).__name__}", dedupe_window_seconds=3600)
                    last_schedule = now

                if now - last_safety >= safety_interval:
                    state = self.safety.evaluate(); last_safety = now
                    if state.paused and not state.manual:
                        self.notifier.emit("CRITICAL", "Circuit breaker active", state.reason or "Outbound posting paused", dedupe_key="circuit-breaker-active", dedupe_window_seconds=3600)
                else:
                    state = self.safety.status()

                if now - last_auth_refresh >= self.settings.auth_refresh_seconds and self.network_ok:
                    auth = await self._refresh_auth(auth); last_auth_refresh = now

                if self.settings.auto_backup_hours > 0 and now - last_backup >= self.settings.auto_backup_hours * 3600:
                    try:
                        dst = self._auto_backup(); print(f"[BACKUP] {dst}")
                    except Exception as exc:
                        self.db.event("WARNING", "auto_backup_failed", str(exc)[:800])
                        self.notifier.emit("IMPORTANT", "Automatic backup failed", str(exc)[:1000], dedupe_key="auto-backup-failed", dedupe_window_seconds=21600)
                    last_backup = now

                if self.settings.auto_rescan_minutes > 0 and now - last_rescan >= self.settings.auto_rescan_minutes * 60 and self.network_ok:
                    try:
                        auth = await self._refresh_auth(auth)
                        result = await sync_destinations(self.db, self.pool, auth, fail_closed=True)
                        if self.settings.auto_apply_rules_on_scan:
                            from .rules import apply_rules
                            from .core import refresh_system_tags
                            rule_result = apply_rules(self.db, actor="auto-rescan")
                            refresh_system_tags(self.db)
                            result["rules"] = rule_result
                        print(f"[RESCAN] {json.dumps(result)}")
                        self.watchdog.beat("destination_scan", "ok", result)
                        self.db.event("INFO", "auto_rescan", "Automatic Telegram destination rescan complete", details=json.dumps(result))
                        if result.get("new", 0):
                            self.notifier.emit("IMPORTANT", "New Telegram destinations", f"{result['new']} new destination(s) are waiting in REVIEW + disabled.", dedupe_key=f"new-destinations:{datetime.now(timezone.utc).strftime('%Y%m%d%H')}")
                    except Exception as exc:
                        self.watchdog.beat("destination_scan", "error", str(exc))
                        self.db.event("WARNING", "auto_rescan_failed", str(exc)[:800])
                        print(f"[WARNING] Automatic rescan failed: {exc}")
                    last_rescan = now

                if now - last_summary >= self.settings.daily_summary_hours * 3600:
                    try: self._daily_summary()
                    except Exception as exc: self.db.event("WARNING", "daily_summary_failed", str(exc)[:800])
                    last_summary = now

                if now - last_weekly >= self.settings.weekly_summary_hours * 3600:
                    try: self._weekly_summary()
                    except Exception as exc: self.db.event("WARNING", "weekly_summary_failed", str(exc)[:800])
                    last_weekly = now

                if now - last_maintenance >= self.settings.maintenance_hours * 3600:
                    try: self._maintenance()
                    except Exception as exc:
                        self.db.event("WARNING", "maintenance_failed", str(exc)[:800])
                    last_maintenance = now

                if now - last_watchdog >= self.settings.watchdog_seconds:
                    # The service loop itself is the recovery supervisor. A stale child heartbeat is surfaced,
                    # while the next iteration naturally re-runs scheduler/worker rather than spawning duplicates.
                    self.watchdog.evaluate(("service", "scheduler", "worker"))
                    last_watchdog = now

                if state.paused:
                    self.watchdog.beat("worker", "paused", state.reason)
                    if now - last_pause_message >= 60:
                        until = state.until or "manual resume"
                        print(f"[SAFETY PAUSED] {state.reason or 'outbound paused'} | until: {until}")
                        last_pause_message = now
                    await asyncio.sleep(self.poll_seconds)
                    continue

                if not self.network_ok:
                    self.watchdog.beat("worker", "paused", "network unavailable")
                    await asyncio.sleep(min(self._reconnect_backoff, max(5, self.poll_seconds)))
                    continue

                try:
                    worked = await self.worker.run_once(auth)
                    self.watchdog.beat("worker", "ok" if worked else "idle", {"worked": bool(worked)})
                except Exception as exc:
                    self.watchdog.beat("worker", "error", str(exc))
                    self.db.event("ERROR", "worker_loop_error", str(exc)[:800])
                    self.notifier.emit("IMPORTANT", "Worker error", str(exc)[:1200], dedupe_key=f"worker:{type(exc).__name__}", dedupe_window_seconds=3600)
                    worked = False
                if not worked:
                    await asyncio.sleep(self.poll_seconds)
        finally:
            self.watchdog.beat("service", "stopped")
            if self.admin_task:
                self.admin_task.cancel()
                try: await self.admin_task
                except BaseException: pass
