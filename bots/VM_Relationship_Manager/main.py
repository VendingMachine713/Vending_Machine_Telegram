from __future__ import annotations

import asyncio
import logging
import signal
from pathlib import Path
from logging.handlers import RotatingFileHandler

from admin_bot import AdminBot
from backup_manager import BackupManager
from config import load_settings
from database import Database, utcnow
from jobs import BackgroundJobs
from monitor import TelegramMonitor
from relationship_engine import RelationshipEngine
from startup_utils import pre_upgrade_backup
from instance_lock import SingleInstanceLock, AlreadyRunningError


class SecretRedactionFilter(logging.Filter):
    def __init__(self, secrets):
        super().__init__()
        self.secrets=[str(x) for x in secrets if x]

    def filter(self, record):
        try:
            message=record.getMessage()
            for secret in self.secrets:
                message=message.replace(secret,"[REDACTED]")
            record.msg=message
            record.args=()
        except Exception:
            pass
        return True


def configure_logging(log_dir, secrets=()):
    log_dir.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    redactor=SecretRedactionFilter(secrets)
    console = logging.StreamHandler(); console.setFormatter(formatter); console.addFilter(redactor); root.addHandler(console)
    file_handler = RotatingFileHandler(log_dir / "relationship_manager.log", maxBytes=3_000_000, backupCount=7, encoding="utf-8")
    file_handler.setFormatter(formatter); file_handler.addFilter(redactor); root.addHandler(file_handler)
    # Never log Bot API URLs/tokens during routine polling.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


async def main():
    settings = load_settings()
    configure_logging(settings.log_dir, (settings.bot_token, settings.api_hash, settings.phone))
    log = logging.getLogger("vm_relationship_manager")

    instance_lock = SingleInstanceLock(Path(__file__).resolve().parent / "runtime" / "vm_relationship_manager.instance.lock")
    try:
        instance_lock.acquire()
    except AlreadyRunningError:
        log.warning("Another VM Relationship Manager instance is already running; exiting duplicate launch cleanly.")
        return

    safety_backup = pre_upgrade_backup(settings, "6.0.0")
    if safety_backup:
        log.info("Pre-v6 safety backup: %s", safety_backup)

    db = Database(settings.database_path)
    if safety_backup and not db.meta("v6_post_upgrade_backup_at"):
        post = BackupManager(db, settings.backup_dir).create("post_v6_upgrade")
        if post["status"] != "verified":
            raise RuntimeError(f"Post-v6 upgrade backup verification failed: {post}")
        db.set_meta("v6_post_upgrade_backup_at", utcnow())
        log.info("Post-v6 verified backup: %s", post["path"])
    engine = RelationshipEngine(db)
    if not db.meta("v6_policy_bootstrap_done"):
        calibration = engine.calibration.refresh()
        bootstrap_cls = engine.classification.compute_all(auto_apply=True)
        engine.priority.refresh_all()
        bootstrap_actions = engine.actions.compute_all()
        engine.segments.compute_all()
        policy = engine.exception_policy.summary()
        engine.integration.export_all()
        db.set_meta("v6_policy_bootstrap_done", utcnow())
        log.info(
            "v6 policy bootstrap: contacts=%s newly_classified=%s action_signals=%s calibration_types=%s selected_exceptions=%s",
            bootstrap_cls["computed"], bootstrap_cls["newly_applied"], bootstrap_actions["active_signals"], len(calibration), policy["selected"],
        )
    admin_bot = AdminBot(settings, db, engine, monitor=None)
    stop_event = asyncio.Event()

    def health(component: str, status: str, details: str):
        db.execute("INSERT INTO bot_health(component,status,details,created_at) VALUES (?,?,?,?)", (component,status,details[:1200],utcnow()))

    def ask_stop():
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, ask_stop)
        except (NotImplementedError, RuntimeError):
            pass

    async def monitor_supervisor():
        backoff=2
        restarts=0
        while not stop_event.is_set():
            monitor=TelegramMonitor(settings, engine)
            admin_bot.monitor=monitor
            try:
                health("telegram_monitor","starting",f"Monitor start attempt {restarts+1}")
                task=asyncio.create_task(monitor.start(), name=f"telegram-monitor-{restarts}")
                ready=asyncio.create_task(monitor.ready.wait(), name=f"monitor-ready-{restarts}")
                done,_=await asyncio.wait({task,ready}, return_when=asyncio.FIRST_COMPLETED)
                if ready in done and monitor.ready.is_set():
                    health("telegram_monitor","online","Telethon monitoring account authorised and receiving updates")
                    backoff=2
                if task in done:
                    exc=task.exception()
                    if stop_event.is_set():
                        return
                    raise RuntimeError(f"Telegram monitor stopped unexpectedly: {exc!r}") from exc
                await task
                if not stop_event.is_set():
                    raise RuntimeError("Telegram monitor returned unexpectedly")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                restarts += 1
                health("telegram_monitor","error",f"{exc!r}; auto-restart in {backoff}s")
                log.exception("Telegram monitor failed; restarting")
                await admin_bot.notify_admins(
                    f"<b>ðŸŸ  Relationship monitor restarting</b>\nAutomatic recovery attempt {restarts}."
                )
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=backoff)
                except asyncio.TimeoutError:
                    pass
                backoff=min(60,backoff*2)
            finally:
                try:
                    await monitor.stop()
                except Exception:
                    pass

    async def jobs_supervisor():
        backoff=2
        restarts=0
        while not stop_event.is_set():
            jobs=BackgroundJobs(settings, db, engine)
            try:
                health("scheduler","starting",f"Scheduler start attempt {restarts+1}")
                await jobs.run()
                if not stop_event.is_set():
                    raise RuntimeError("Background scheduler returned unexpectedly")
            except asyncio.CancelledError:
                await jobs.stop(); raise
            except Exception as exc:
                restarts += 1
                health("scheduler","error",f"{exc!r}; auto-restart in {backoff}s")
                log.exception("Background jobs failed; restarting")
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=backoff)
                except asyncio.TimeoutError:
                    pass
                backoff=min(60,backoff*2)
            finally:
                await jobs.stop()

    async def heartbeat():
        while not stop_event.is_set():
            db.set_meta("last_heartbeat", utcnow())
            health("system_heartbeat","ok","Relationship Manager process alive")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=300)
            except asyncio.TimeoutError:
                pass

    health("system","starting","VM Relationship Manager v6 starting")
    await admin_bot.start()
    health("admin_bot","online","Admin control bot polling started")
    monitor_task=asyncio.create_task(monitor_supervisor(), name="monitor-supervisor")
    jobs_task=asyncio.create_task(jobs_supervisor(), name="jobs-supervisor")
    heartbeat_task=asyncio.create_task(heartbeat(), name="system-heartbeat")

    health("system","online","VM Relationship Manager v6 online")
    log.info("VM Relationship Manager v6 online")
    log.info("Database: %s", settings.database_path)
    log.info("Backups: %s", settings.backup_dir)
    log.info("Logs: %s", settings.log_dir)

    try:
        await stop_event.wait()
    finally:
        stop_event.set()
        for t in (monitor_task,jobs_task,heartbeat_task):
            if not t.done(): t.cancel()
        await asyncio.gather(monitor_task,jobs_task,heartbeat_task,return_exceptions=True)
        try:
            await admin_bot.stop()
        except Exception:
            log.exception("Error while stopping admin bot")
        health("system","offline","VM Relationship Manager stopped")
        db.checkpoint(truncate=False)
        instance_lock.release()
        log.info("VM Relationship Manager stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
