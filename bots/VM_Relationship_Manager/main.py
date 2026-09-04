from __future__ import annotations

import asyncio
import logging
import signal
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler

from admin_bot import AdminBot
from business_admin import BusinessAdmin
from business_memory import BusinessMemory
from config import load_settings
from database import Database, utcnow
from jobs import BackgroundJobs
from monitor import TelegramMonitor
from relationship_engine import RelationshipEngine

BOT_DIR=Path(__file__).resolve().parent
ROOT=BOT_DIR.parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from shared.vm_core.publisher import BotEventPublisher
publisher=BotEventPublisher("VM_Relationship_Manager",ROOT)


def configure_logging(log_dir):
    log_dir.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    file_handler = RotatingFileHandler(
        log_dir / "relationship_manager.log",
        maxBytes=2_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


async def main():
    settings = load_settings()
    configure_logging(settings.log_dir)

    log = logging.getLogger("vm_relationship_manager")
    db = Database(settings.database_path)
    engine = RelationshipEngine(db)
    monitor = TelegramMonitor(settings, engine)
    admin_bot = AdminBot(settings, db, engine, monitor=monitor)

    business_memory = BusinessMemory(db)
    business_admin = BusinessAdmin(
        settings,
        db,
        business_memory,
        monitor=monitor,
    )
    business_admin.register(admin_bot.app)

    jobs = BackgroundJobs(settings, db, engine)

    def health(component: str, status: str, details: str):
        db.execute(
            """INSERT INTO bot_health
               (component, status, details, created_at)
               VALUES (?, ?, ?, ?)""",
            (component, status, details, utcnow()),
        )
        publisher.heartbeat(status=status, component=component, details=details)

    health("system", "starting", "VM Relationship Manager starting")
    health("business_memory", "online", "Business CRM schema initialized")
    publisher.started(database=str(settings.database_path))

    stop_event = asyncio.Event()

    def ask_stop():
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, ask_stop)
        except (NotImplementedError, RuntimeError):
            pass

    await admin_bot.start()
    health("admin_bot", "online", "Admin control bot polling started")

    monitor_task = asyncio.create_task(monitor.start(), name="telegram-monitor")
    jobs_task = asyncio.create_task(jobs.run(), name="background-jobs")
    stop_task = asyncio.create_task(stop_event.wait(), name="stop-waiter")

    health("system", "online", "VM Relationship Manager online")
    log.info("VM Relationship Manager online")
    log.info("Database: %s", settings.database_path)
    log.info("Backups: %s", settings.backup_dir)
    log.info("Logs: %s", settings.log_dir)

    try:
        done, _ = await asyncio.wait(
            {monitor_task, jobs_task, stop_task},
            return_when=asyncio.FIRST_COMPLETED,
        )

        if monitor_task in done and not stop_event.is_set():
            exc = monitor_task.exception()
            details = f"Telegram monitor stopped unexpectedly: {exc!r}"
            health("telegram_monitor", "error", details)
            publisher.incident("monitor_stopped",details,severity="ERROR",component="telegram_monitor")
            log.error(details)
            await admin_bot.notify_admins(
                "<b>🔴 VM Relationship Manager monitor stopped</b>\n"
                "The Telegram monitoring layer exited unexpectedly. Check /health and the log file."
            )
            raise RuntimeError(details) from exc

        if jobs_task in done and not stop_event.is_set():
            exc = jobs_task.exception()
            details = f"Background jobs stopped unexpectedly: {exc!r}"
            health("scheduler", "error", details)
            publisher.incident("scheduler_stopped",details,severity="ERROR",component="scheduler")
            log.error(details)
            await admin_bot.notify_admins(
                "<b>🔴 VM Relationship Manager scheduler stopped</b>\n"
                "Background maintenance exited unexpectedly. Check /health and the log file."
            )
            raise RuntimeError(details) from exc

    finally:
        stop_event.set()
        await jobs.stop()
        try:
            await monitor.stop()
        except Exception:
            log.exception("Error while disconnecting Telethon monitor")
        try:
            await admin_bot.stop()
        except Exception:
            log.exception("Error while stopping admin bot")

        for task in (monitor_task, jobs_task, stop_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(monitor_task, jobs_task, stop_task, return_exceptions=True)

        health("system", "offline", "VM Relationship Manager stopped")
        publisher.stopped("normal")
        log.info("VM Relationship Manager stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
