import argparse
import asyncio
import json
import logging
import os
import sqlite3
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core import Store
from envutil import load_env
from marketplace import MarketplaceStore
from match_runtime import HardenedMatchEngine
from match_ui import format_match_alert

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.vm_core.security import central_owner_ids

DB = BASE / "data" / "universal_search.db"
STATE = BASE / "state"
STATUS_FILE = STATE / "match_engine_status.json"
ADMIN_FILE = STATE / "admin_id.txt"

LEASE_SCHEMA = """
CREATE TABLE IF NOT EXISTS marketplace_match_daemon_lease(
  singleton INTEGER PRIMARY KEY CHECK(singleton=1),
  owner TEXT NOT NULL,
  pid INTEGER NOT NULL,
  expires_utc TEXT NOT NULL,
  updated_utc TEXT NOT NULL
);
"""


def utc_now_dt():
    return datetime.now(timezone.utc)


def utc_now():
    return utc_now_dt().isoformat()


def parse_dt(value):
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def admin_id():
    """Legacy local-owner compatibility during central-owner migration."""
    try:
        return int(ADMIN_FILE.read_text(encoding="utf-8").strip())
    except Exception:
        return None


def authorized_owner_ids():
    owners = set(central_owner_ids(ROOT))
    local = admin_id()
    if local:
        owners.add(local)
    return tuple(sorted(int(value) for value in owners if int(value) > 0))


class DaemonLease:
    def __init__(self, db_path, *, ttl_seconds=90):
        self.db_path = Path(db_path)
        self.ttl_seconds = max(30, int(ttl_seconds))
        self.owner = f"{os.getpid()}-{uuid.uuid4().hex}"
        self.acquired = False

    @contextmanager
    def conn(self):
        """Yield a lease connection and always close the OS handle.

        sqlite3.Connection's own context manager commits/rolls back but does not
        close the connection. That is easy to miss on POSIX because an open file
        can still be unlinked, while Windows correctly exposes it as a locked DB.
        Lease connections use autocommit/explicit transactions, so this wrapper
        owns handle lifetime only.
        """
        c = sqlite3.connect(self.db_path, timeout=10, isolation_level=None)
        c.row_factory = sqlite3.Row
        try:
            yield c
        finally:
            c.close()

    def acquire(self):
        now = utc_now_dt()
        expires = (now + timedelta(seconds=self.ttl_seconds)).isoformat()
        with self.conn() as c:
            c.execute(LEASE_SCHEMA)
            c.execute("BEGIN IMMEDIATE")
            row = c.execute(
                "SELECT * FROM marketplace_match_daemon_lease WHERE singleton=1"
            ).fetchone()
            existing_expiry = parse_dt(row["expires_utc"]) if row else None
            if row and existing_expiry and existing_expiry > now and row["owner"] != self.owner:
                c.execute("ROLLBACK")
                return False, dict(row)
            c.execute(
                """INSERT INTO marketplace_match_daemon_lease(
                       singleton,owner,pid,expires_utc,updated_utc
                   ) VALUES(1,?,?,?,?)
                   ON CONFLICT(singleton) DO UPDATE SET
                     owner=excluded.owner,pid=excluded.pid,
                     expires_utc=excluded.expires_utc,updated_utc=excluded.updated_utc""",
                (self.owner, os.getpid(), expires, now.isoformat()),
            )
            c.execute("COMMIT")
        self.acquired = True
        return True, None

    def renew(self):
        if not self.acquired:
            return False
        now = utc_now_dt()
        expires = (now + timedelta(seconds=self.ttl_seconds)).isoformat()
        with self.conn() as c:
            cur = c.execute(
                """UPDATE marketplace_match_daemon_lease
                   SET expires_utc=?,updated_utc=?,pid=?
                   WHERE singleton=1 AND owner=?""",
                (expires, now.isoformat(), os.getpid(), self.owner),
            )
        return cur.rowcount == 1

    def release(self):
        if not self.acquired:
            return
        try:
            with self.conn() as c:
                c.execute(
                    "DELETE FROM marketplace_match_daemon_lease WHERE singleton=1 AND owner=?",
                    (self.owner,),
                )
        finally:
            self.acquired = False


def write_status(**payload):
    STATE.mkdir(parents=True, exist_ok=True)
    document = {"updated_utc": utc_now(), "pid": os.getpid(), **payload}
    temp = STATUS_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(document, indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(STATUS_FILE)


def load_token():
    env = load_env(BASE / ".env")
    token = env.get("BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("BOT_TOKEN is required in bots/Universal_Search/.env")
    return token


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Passive VM Universal Search demand-match daemon.")
    parser.add_argument("--interval", type=int, default=30, help="Refresh interval in seconds (10-600).")
    parser.add_argument("--min-score", type=float, default=45.0, help="Minimum score retained as a match.")
    parser.add_argument("--alert-score", type=float, default=65.0, help="Minimum score for private owner alerts.")
    parser.add_argument("--once", action="store_true", help="Run one safe refresh cycle and exit.")
    return parser.parse_args(argv)


async def deliver_due(bot, engine, logger, owners):
    delivered = 0
    failed = 0
    for alert in engine.due_alerts_for_owners(owners, 20):
        match = engine.get_match(alert["id"])
        if not match:
            engine.cancel_stale_alerts(alert["id"])
            continue
        owner = int(alert["owner_user_id"])
        if owner not in owners:
            # The owner set may have changed between the queue read and send.
            engine.reconcile_alert_owners(authorized_owner_ids())
            continue
        try:
            await bot.send_message(
                chat_id=owner,
                text=format_match_alert(match),
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            status, due = engine.mark_alert_retry(alert["alert_id"], exc, alert["attempts"])
            logger.warning(
                "Match alert failed match=%s alert=%s status=%s due=%s error=%s",
                alert["id"], alert["alert_id"], status, due, type(exc).__name__,
            )
            failed += 1
        else:
            engine.mark_alert_sent(alert["alert_id"], alert["id"])
            delivered += 1
    return delivered, failed


async def cycle(engine, bot, *, min_score, alert_score, logger):
    refresh = await asyncio.to_thread(engine.refresh_all, min_score=min_score)
    owners = authorized_owner_ids()
    cancelled_wrong_owner = await asyncio.to_thread(
        engine.reconcile_alert_owners, owners
    )
    queued = 0
    delivered = 0
    failed = 0
    if owners and engine.notifications_enabled():
        queued = await asyncio.to_thread(
            engine.enqueue_new_alerts_for_owners,
            owners,
            min_score=alert_score,
            limit=50,
        )
        delivered, failed = await deliver_due(bot, engine, logger, set(owners))
    totals, _ = await asyncio.to_thread(engine.stats)
    queue = await asyncio.to_thread(engine.queue_status)
    return {
        "state": "healthy",
        "admin_configured": bool(owners),
        "authorized_owner_count": len(owners),
        "central_owner_configured": bool(central_owner_ids(ROOT)),
        "notifications_enabled": engine.notifications_enabled(),
        "refresh": refresh,
        "cancelled_wrong_owner_alerts": cancelled_wrong_owner,
        "alerts_queued": queued,
        "alerts_delivered": delivered,
        "alerts_failed_this_cycle": failed,
        "alert_queue": queue,
        "matches_total": totals["total"] or 0,
        "matches_active": totals["active"] or 0,
        "matches_new": totals["new_count"] or 0,
        "matches_high_confidence": totals["high_confidence"] or 0,
    }


async def run(args):
    from telegram import Bot

    interval = max(10, min(int(args.interval), 600))
    min_score = max(0.0, min(float(args.min_score), 100.0))
    alert_score = max(min_score, min(float(args.alert_score), 100.0))
    token = load_token()

    # The sidecar must be able to start safely before the main bot in a fresh
    # process/session. Open the core and marketplace stores first so all joined
    # tables exist before the matching engine refreshes them.
    DB.parent.mkdir(parents=True, exist_ok=True)
    Store(DB)
    MarketplaceStore(DB)
    engine = HardenedMatchEngine(DB)

    lease = DaemonLease(DB)
    acquired, lease_owner = lease.acquire()
    if not acquired:
        write_status(state="duplicate_blocked", existing_owner=lease_owner)
        raise SystemExit(
            f"Another match daemon lease is active (pid={lease_owner.get('pid') if lease_owner else '?'})."
        )

    logger = logging.getLogger("universal_search.match_daemon")
    bot = Bot(token=token)
    initialized = False
    try:
        await bot.initialize()
        initialized = True
        bootstrap = await asyncio.to_thread(engine.bootstrap, min_score=min_score)
        cancelled = await asyncio.to_thread(engine.cancel_stale_alerts)
        owners = authorized_owner_ids()
        cancelled_wrong_owner = await asyncio.to_thread(
            engine.reconcile_alert_owners, owners
        )
        pruned = await asyncio.to_thread(engine.cleanup_alert_history)
        write_status(
            state="starting",
            baseline=bootstrap,
            cancelled_stale_alerts=cancelled,
            cancelled_wrong_owner_alerts=cancelled_wrong_owner,
            pruned_alert_records=pruned,
            admin_configured=bool(owners),
            authorized_owner_count=len(owners),
            central_owner_configured=bool(central_owner_ids(ROOT)),
            notifications_enabled=engine.notifications_enabled(),
            alert_queue=engine.queue_status(),
        )
        cleanup_counter = 0
        while True:
            started = time.monotonic()
            if not lease.renew():
                raise RuntimeError("Match daemon lease ownership was lost")
            try:
                status = await cycle(
                    engine,
                    bot,
                    min_score=min_score,
                    alert_score=alert_score,
                    logger=logger,
                )
                cleanup_counter += 1
                if cleanup_counter >= max(1, int(3600 / interval)):
                    status["pruned_alert_records"] = await asyncio.to_thread(
                        engine.cleanup_alert_history
                    )
                    cleanup_counter = 0
                write_status(**status)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("Match daemon cycle failed")
                write_status(
                    state="degraded",
                    error_type=type(exc).__name__,
                    error=str(exc)[:1000],
                    authorized_owner_count=len(authorized_owner_ids()),
                )
            if args.once:
                return
            elapsed = time.monotonic() - started
            await asyncio.sleep(max(1.0, interval - elapsed))
    finally:
        lease.release()
        try:
            if initialized:
                await bot.shutdown()
        finally:
            write_status(state="stopped")


def main(argv=None):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    args = parse_args(argv)
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        write_status(state="crashed", error_type=type(exc).__name__, error=str(exc)[:1000])
        raise


if __name__ == "__main__":
    main()
