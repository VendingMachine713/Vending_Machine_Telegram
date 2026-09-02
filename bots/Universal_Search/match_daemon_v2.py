import argparse
import asyncio
import logging
import time

from telegram import Bot

from core import Store
from marketplace import MarketplaceStore
from match_daemon import DaemonLease, admin_id, load_token, write_status
from match_engine_v2_runtime import HardenedMatchEngineV2
from match_ui import format_match_alert
from match_ui_v2 import format_wtb_expiry_alert


async def deliver_match_alerts(bot, engine, logger, *, limit=20):
    delivered = 0
    failed = 0
    for alert in engine.due_alerts(limit):
        match = engine.get_match(alert["id"])
        if not match:
            engine.cancel_stale_alerts(alert["id"])
            continue
        try:
            await bot.send_message(
                chat_id=alert["owner_user_id"],
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


async def deliver_wtb_expiry_alerts(bot, engine, logger, *, limit=20):
    delivered = 0
    failed = 0
    for listing, queue in engine.due_wtb_expiry_alerts(limit):
        try:
            await bot.send_message(
                chat_id=queue["owner_user_id"],
                text=format_wtb_expiry_alert(listing),
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            status, due = engine.mark_wtb_expiry_alert_retry(
                queue["alert_id"], exc, queue["attempts"]
            )
            logger.warning(
                "WTB expiry reminder failed logical=%s alert=%s status=%s due=%s error=%s",
                listing["logical_listing_id"], queue["alert_id"], status, due, type(exc).__name__,
            )
            failed += 1
        else:
            engine.mark_wtb_expiry_alert_sent(
                queue["alert_id"], listing["logical_listing_id"]
            )
            delivered += 1
    return delivered, failed


async def incremental_cycle(
    engine,
    bot,
    *,
    min_score,
    alert_score,
    event_limit,
    candidate_limit,
    logger,
):
    event_result = await asyncio.to_thread(
        engine.process_events,
        limit=event_limit,
        min_score=min_score,
        candidate_limit=candidate_limit,
    )
    owner = admin_id()
    wrong_owner_match = 0
    stale_expiry = 0
    queued_match = 0
    queued_expiry = 0
    delivered_match = 0
    failed_match = 0
    delivered_expiry = 0
    failed_expiry = 0

    if owner:
        wrong_owner_match = await asyncio.to_thread(
            engine.cancel_wrong_owner_alerts, owner
        )
        stale_expiry = await asyncio.to_thread(
            engine.cancel_stale_wtb_expiry_alerts, owner
        )
    else:
        stale_expiry = await asyncio.to_thread(
            engine.cancel_stale_wtb_expiry_alerts
        )

    if owner and engine.notifications_enabled():
        queued_match = await asyncio.to_thread(
            engine.enqueue_new_alerts, owner, min_score=alert_score, limit=50
        )
        queued_expiry = await asyncio.to_thread(
            engine.enqueue_due_wtb_expiry_alerts, owner, limit=50
        )
        delivered_match, failed_match = await deliver_match_alerts(
            bot, engine, logger
        )
        delivered_expiry, failed_expiry = await deliver_wtb_expiry_alerts(
            bot, engine, logger
        )

    totals, _ = await asyncio.to_thread(engine.stats)
    match_queue = await asyncio.to_thread(engine.queue_status)
    demand_stats = await asyncio.to_thread(
        engine.demand_stats, alert_threshold=alert_score
    )
    return {
        "state": "healthy",
        "engine_mode": "event_driven_v2",
        "admin_configured": bool(owner),
        "notifications_enabled": engine.notifications_enabled(),
        "events": event_result,
        "event_backlog": demand_stats["event_backlog"],
        "cancelled_wrong_owner_match_alerts": wrong_owner_match,
        "cancelled_stale_wtb_reminders": stale_expiry,
        "match_alerts_queued": queued_match,
        "match_alerts_delivered": delivered_match,
        "match_alerts_failed_this_cycle": failed_match,
        "wtb_reminders_queued": queued_expiry,
        "wtb_reminders_delivered": delivered_expiry,
        "wtb_reminders_failed_this_cycle": failed_expiry,
        "match_alert_queue": match_queue,
        "wtb_reminder_queue": demand_stats["expiry_alert_queue"],
        "matches_total": totals["total"] or 0,
        "matches_active": totals["active"] or 0,
        "matches_new": totals["new_count"] or 0,
        "matches_high_confidence": totals["high_confidence"] or 0,
        "demand": {
            "active_wtb": demand_stats["active_wtb"],
            "matched_wtb": demand_stats["matched_wtb"],
            "unmatched_wtb": demand_stats["unmatched_wtb"],
            "expiring_within_7d": demand_stats["expiring_within_7d"],
            "overdue_reminder": demand_stats["overdue_reminder"],
        },
        "calibration": demand_stats["calibration"],
    }


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Event-driven VM Universal Search Match Engine v2.")
    p.add_argument("--interval", type=int, default=15, help="Event-consumer interval in seconds (10-300).")
    p.add_argument("--min-score", type=float, default=45.0)
    p.add_argument("--alert-score", type=float, default=65.0)
    p.add_argument("--event-limit", type=int, default=250)
    p.add_argument("--candidate-limit", type=int, default=500)
    p.add_argument("--full-refresh-minutes", type=int, default=60)
    p.add_argument("--expiry-refresh-minutes", type=int, default=10)
    p.add_argument("--once", action="store_true")
    return p.parse_args(argv)


async def run(args):
    from match_daemon import DB

    interval = max(10, min(int(args.interval), 300))
    min_score = max(0.0, min(float(args.min_score), 100.0))
    alert_score = max(min_score, min(float(args.alert_score), 100.0))
    event_limit = max(1, min(int(args.event_limit), 2000))
    candidate_limit = max(10, min(int(args.candidate_limit), 2000))
    full_refresh_seconds = max(300, min(int(args.full_refresh_minutes) * 60, 86400))
    expiry_refresh_seconds = max(60, min(int(args.expiry_refresh_minutes) * 60, 21600))

    token = load_token()
    DB.parent.mkdir(parents=True, exist_ok=True)
    Store(DB)
    MarketplaceStore(DB)
    engine = HardenedMatchEngineV2(DB)

    lease = DaemonLease(DB)
    acquired, existing = lease.acquire()
    if not acquired:
        write_status(state="duplicate_blocked", engine_mode="event_driven_v2", existing_owner=existing)
        raise SystemExit(
            f"Another match daemon lease is active (pid={existing.get('pid') if existing else '?'})."
        )

    logger = logging.getLogger("universal_search.match_daemon_v2")
    bot = Bot(token=token)
    initialized = False
    last_full_refresh = 0.0
    last_expiry_refresh = 0.0
    try:
        await bot.initialize()
        initialized = True
        bootstrap = await asyncio.to_thread(engine.bootstrap_v2, min_score=min_score)
        # bootstrap_v2 already performs full pair and WTB-expiry reconciliation.
        # Start periodic timers here so startup does not immediately repeat both scans.
        reconciled_at = time.monotonic()
        last_full_refresh = reconciled_at
        last_expiry_refresh = reconciled_at

        current_owner = admin_id()
        if current_owner:
            await asyncio.to_thread(engine.cancel_wrong_owner_alerts, current_owner)
            await asyncio.to_thread(engine.cancel_stale_wtb_expiry_alerts, current_owner)
        else:
            await asyncio.to_thread(engine.cancel_stale_wtb_expiry_alerts)
        pruned_match = await asyncio.to_thread(engine.cleanup_alert_history)
        pruned_expiry = await asyncio.to_thread(engine.cleanup_wtb_expiry_alert_history)
        write_status(
            state="starting",
            engine_mode="event_driven_v2",
            baseline=bootstrap,
            event_backlog=engine.event_backlog_count(),
            pruned_match_alert_records=pruned_match,
            pruned_wtb_reminder_records=pruned_expiry,
            notifications_enabled=engine.notifications_enabled(),
        )

        while True:
            started = time.monotonic()
            if not lease.renew():
                raise RuntimeError("Match daemon lease ownership was lost")
            try:
                status = await incremental_cycle(
                    engine,
                    bot,
                    min_score=min_score,
                    alert_score=alert_score,
                    event_limit=event_limit,
                    candidate_limit=candidate_limit,
                    logger=logger,
                )
                now_mono = time.monotonic()
                if now_mono - last_expiry_refresh >= expiry_refresh_seconds:
                    status["wtb_expiry_refresh"] = await asyncio.to_thread(
                        engine.refresh_wtb_expiry
                    )
                    last_expiry_refresh = now_mono
                if now_mono - last_full_refresh >= full_refresh_seconds:
                    status["full_reconciliation"] = await asyncio.to_thread(
                        engine.refresh_all, min_score=min_score
                    )
                    status["pruned_match_alert_records"] = await asyncio.to_thread(
                        engine.cleanup_alert_history
                    )
                    status["pruned_wtb_reminder_records"] = await asyncio.to_thread(
                        engine.cleanup_wtb_expiry_alert_history
                    )
                    last_full_refresh = now_mono
                write_status(**status)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("Match Engine v2 cycle failed")
                write_status(
                    state="degraded",
                    engine_mode="event_driven_v2",
                    error_type=type(exc).__name__,
                    error=str(exc)[:1000],
                    event_backlog=engine.event_backlog_count(),
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
            write_status(state="stopped", engine_mode="event_driven_v2")


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
        write_status(
            state="crashed",
            engine_mode="event_driven_v2",
            error_type=type(exc).__name__,
            error=str(exc)[:1000],
        )
        raise


if __name__ == "__main__":
    main()
