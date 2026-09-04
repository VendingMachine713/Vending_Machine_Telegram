import asyncio
import html
import logging
import re
import secrets
import sys
from contextlib import suppress
from datetime import timezone
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from core import Store, parse_query
from envutil import load_env
from watches import WatchStore

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.vm_core.publisher import BotEventPublisher
from shared.vm_core.security import owner_authorized, central_owner_ids

publisher = BotEventPublisher("Universal_Search", ROOT)
logger = logging.getLogger("universal_search")

ENV = load_env(BASE / ".env")
TOKEN = ENV.get("BOT_TOKEN", "").strip()
if not TOKEN:
    raise SystemExit("BOT_TOKEN missing. Run CONFIGURE_MISSING_BOTS.bat from the project root.")

STATE = BASE / "state"
STATE.mkdir(exist_ok=True)
ADMIN_FILE = STATE / "admin_id.txt"
CLAIM_FILE = STATE / "claim_code.txt"
DB = BASE / "data" / "universal_search.db"
store = Store(DB)
watch_store = WatchStore(DB)


def admin_id():
    try:
        return int(ADMIN_FILE.read_text().strip())
    except Exception:
        return None


def claim_code():
    if CLAIM_FILE.exists():
        return CLAIM_FILE.read_text().strip()
    code = secrets.token_hex(3).upper()
    CLAIM_FILE.write_text(code)
    return code


def authorized_owner_ids():
    owners = set(central_owner_ids(ROOT))
    local = admin_id()
    if local:
        owners.add(local)
    return owners


def is_admin(update):
    if not update.effective_user:
        return False
    uid = update.effective_user.id
    return bool((admin_id() and uid == admin_id()) or owner_authorized(uid, ROOT))


def private_admin(update):
    return bool(
        update.effective_chat
        and update.effective_chat.type == "private"
        and is_admin(update)
    )


async def deny(update):
    # Shared groups should not expose admin/control state to ordinary members.
    if update.effective_chat and update.effective_chat.type == "private" and update.effective_message:
        await update.effective_message.reply_text("Not authorised.")


async def claim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat or update.effective_chat.type != "private":
        return
    if central_owner_ids(ROOT):
        await update.effective_message.reply_text("Central VM owner identity is configured; local claim is disabled.")
        return
    if admin_id():
        await update.effective_message.reply_text("Admin already claimed.")
        return
    if not update.effective_user:
        return
    supplied = " ".join(context.args).strip().upper()
    if supplied and supplied == claim_code():
        ADMIN_FILE.write_text(str(update.effective_user.id))
        CLAIM_FILE.unlink(missing_ok=True)
        watch_store.reconcile_owners(authorized_owner_ids())
        await update.effective_message.reply_text("✅ Universal Search admin claimed.")
    else:
        await update.effective_message.reply_text("Invalid claim code.")


def _short(value, limit):
    value = str(value or "")
    return value if len(value) <= limit else value[: limit - 1] + "…"


def message_link(row):
    username = (row["chat_username"] or "").lstrip("@")
    if username and re.fullmatch(r"[A-Za-z0-9_]+", username):
        return f"https://t.me/{username}/{row['message_id']}"
    chat_id = str(row["chat_id"])
    if chat_id.startswith("-100") and len(chat_id) > 4:
        return f"https://t.me/c/{chat_id[4:]}/{row['message_id']}"
    return None


def fmt_row(row):
    who = "@" + row["sender_username"] if row["sender_username"] else (
        row["display_name"] or str(row["sender_id"] or "?")
    )
    chat = row["chat_title"] or str(row["chat_id"])
    text = (row["text"] or "").replace("\n", " ").strip()
    chat = _short(chat, 60)
    who = _short(who, 45)
    text = _short(text, 180)
    link = message_link(row)
    source = "history" if row["source"] == "backfill" else "live"
    lines = [
        f"<b>{html.escape(chat)}</b> — {html.escape(who)}",
        html.escape(text) if text else "<i>Media message</i>",
        f"<i>{source}</i>",
    ]
    if link:
        lines.append(f'<a href="{html.escape(link, quote=True)}">Open original message</a>')
    return "\n".join(lines)


def render_page(rows, page):
    heading = f"<b>Search results — page {page}</b>"
    blocks = [fmt_row(row) for row in rows]
    text = heading + ("\n\n" + "\n\n".join(blocks) if blocks else "")
    if len(text) <= 3900:
        return text
    kept = []
    for block in blocks:
        candidate = heading + "\n\n" + "\n\n".join(kept + [block])
        if len(candidate) > 3700:
            break
        kept.append(block)
    suffix = "\n\n<i>Result text shortened by Telegram message-size limits.</i>"
    return heading + "\n\n" + "\n\n".join(kept) + suffix


def search_keyboard(token, page, has_more):
    buttons = []
    if page > 1:
        buttons.append(InlineKeyboardButton("◀ Previous", callback_data=f"us:{token}:{page - 1}"))
    if has_more:
        buttons.append(InlineKeyboardButton("Next ▶", callback_data=f"us:{token}:{page + 1}"))
    return InlineKeyboardMarkup([buttons]) if buttons else None


async def _send_search_page(
    update,
    *,
    raw,
    chat_scope,
    cross,
    force_ads,
    session_token=None,
    page_override=None,
    record_search=True,
):
    user = update.effective_user
    if not user:
        return

    effective_raw = raw
    if force_ads:
        effective_raw = (effective_raw + " --ads --available").strip()
    q = parse_query(effective_raw)
    q.limit = min(q.limit, 10)
    if page_override is not None:
        q.page = max(1, int(page_override))

    if not q.has_text_query and not q.ads:
        text = (
            "Use /search words [\"exact phrase\"] [-exclude] [OR other] "
            "[--user @name] [--days 7] [--media] "
            "[--sort relevant|newest|oldest] [--limit 10]"
        )
        if update.callback_query:
            await update.callback_query.answer(text[:180], show_alert=True)
        else:
            await update.effective_message.reply_text(text)
        return

    rows, has_more = store.search(q, chat_scope)
    if record_search:
        store.record_search(user.id, raw)

    if not session_token:
        session_token = secrets.token_urlsafe(6)
        store.save_search_session(session_token, user.id, chat_scope, raw, cross, force_ads)

    publisher.signal(
        "search_activity",
        subject_type="chat",
        subject_id=update.effective_chat.id if update.effective_chat else None,
        score=min(100, len(rows) * 10),
        confidence=0.9,
        rationale="Universal Search query completed",
        result_count=len(rows),
        cross_chat=bool(cross),
        ads_mode=bool(force_ads),
        page=q.page,
        sort=q.sort,
        fts_enabled=bool(store.fts_enabled),
    )

    text = render_page(rows, q.page) if rows else f"No matches on page {q.page}."
    keyboard = search_keyboard(session_token, q.page, has_more)
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            text,
            parse_mode="HTML",
            reply_markup=keyboard,
        )
    else:
        await update.effective_message.reply_text(
            text,
            parse_mode="HTML",
            reply_markup=keyboard,
        )


async def search_cmd(update, context, cross=False, force_ads=False):
    if not private_admin(update):
        return await deny(update)
    raw = " ".join(context.args).strip()
    chat_scope = None if cross else update.effective_chat.id
    await _send_search_page(
        update,
        raw=raw,
        chat_scope=chat_scope,
        cross=cross,
        force_ads=force_ads,
    )


async def cmd_search(update, context):
    await search_cmd(update, context, False, False)


async def cmd_cross(update, context):
    await search_cmd(update, context, True, False)


async def cmd_ads(update, context):
    await search_cmd(update, context, True, True)


async def search_page_callback(update, context):
    query = update.callback_query
    if not private_admin(update):
        if query:
            await query.answer("Not authorised.", show_alert=True)
        return
    match = re.fullmatch(r"us:([A-Za-z0-9_-]+):(\d+)", query.data or "")
    if not match:
        await query.answer("Invalid search session.", show_alert=True)
        return
    token, page_text = match.groups()
    session = store.get_search_session(token)
    if not session:
        await query.answer("This search session expired. Run the search again.", show_alert=True)
        return
    if not update.effective_user or update.effective_user.id != session["user_id"]:
        await query.answer("This search belongs to another user.", show_alert=True)
        return
    await _send_search_page(
        update,
        raw=session["raw_query"],
        chat_scope=session["chat_scope"],
        cross=bool(session["cross_chat"]),
        force_ads=bool(session["force_ads"]),
        session_token=token,
        page_override=int(page_text),
        record_search=False,
    )


async def recent_searches_cmd(update, context):
    if not private_admin(update):
        return await deny(update)
    rows = store.recent_searches(update.effective_user.id, 10)
    if not rows:
        await update.effective_message.reply_text("No recent searches yet.")
        return
    lines = ["Recent searches:"]
    for idx, row in enumerate(rows, 1):
        query = row["query"] or "(empty)"
        lines.append(f"{idx}. {query}")
    await update.effective_message.reply_text("\n".join(lines)[:3900])


def _watch_query_valid(raw_query):
    q = parse_query(raw_query)
    return bool(q.has_text_query or q.ads or q.media or q.user or q.available)


async def watch_cmd(update, context):
    if not private_admin(update):
        return await deny(update)
    raw = " ".join(context.args).strip()
    global_requested = bool(re.search(r"(?:^|\s)--global(?:\s|$)", raw, flags=re.I))
    raw = re.sub(r"(?:^|\s)--global(?:\s|$)", " ", raw, flags=re.I).strip()
    if "::" not in raw:
        await update.effective_message.reply_text(
            "Use /watch name :: query\nExample: /watch iphone-deals :: \"iphone 15\" --ads"
        )
        return
    name, raw_query = (part.strip() for part in raw.split("::", 1))
    if not name or len(name) > 40 or any(ord(ch) < 32 for ch in name):
        await update.effective_message.reply_text("Watch name must be 1-40 normal characters.")
        return
    if not _watch_query_valid(raw_query):
        await update.effective_message.reply_text("The watch needs a searchable term or supported filter.")
        return

    # Private-owner control means watches are global across the indexed corpus.
    # --global remains accepted for backwards compatibility/documentation clarity.
    chat_scope = None
    if global_requested:
        chat_scope = None

    if watch_store.count_for_owner(update.effective_user.id) >= 50:
        existing = {row["name"] for row in watch_store.list_for_owner(update.effective_user.id)}
        if name not in existing:
            await update.effective_message.reply_text("Watch limit reached (50). Delete an old watch first.")
            return

    watch_store.reconcile_owners(authorized_owner_ids())
    row = watch_store.save(update.effective_user.id, name, raw_query, chat_scope)
    await update.effective_message.reply_text(
        f"✅ Watch #{row['id']} saved: {row['name']}\n"
        "Scope: all indexed chats\n"
        f"Query: {row['raw_query']}\n\n"
        "Matching new messages will be delivered as private bot alerts."
    )


async def watches_cmd(update, context):
    if not private_admin(update):
        return await deny(update)
    rows = watch_store.list_for_owner(update.effective_user.id)
    if not rows:
        await update.effective_message.reply_text("No saved watches. Use /watch name :: query")
        return
    lines = ["Saved watches:"]
    for row in rows[:50]:
        state = "ON" if row["enabled"] else "PAUSED"
        scope = "GLOBAL" if row["chat_scope"] is None else str(row["chat_scope"])
        failures = f" | failures={row['failure_count']}" if row["failure_count"] else ""
        lines.append(
            f"#{row['id']} [{state}] {row['name']} | scope={scope}{failures}\n  {row['raw_query']}"
        )
    await update.effective_message.reply_text("\n".join(lines)[:3900])


async def _watch_state_cmd(update, context, enabled):
    if not private_admin(update):
        return await deny(update)
    if not context.args or not context.args[0].isdigit():
        await update.effective_message.reply_text(
            "Provide the watch ID, e.g. /pausewatch 3" if not enabled else "Provide the watch ID, e.g. /resumewatch 3"
        )
        return
    watch_id = int(context.args[0])
    changed = watch_store.set_enabled(update.effective_user.id, watch_id, enabled)
    if not changed:
        await update.effective_message.reply_text("Watch not found or not owned by you.")
        return
    await update.effective_message.reply_text(
        f"✅ Watch #{watch_id} {'resumed' if enabled else 'paused'}."
    )


async def pause_watch_cmd(update, context):
    await _watch_state_cmd(update, context, False)


async def resume_watch_cmd(update, context):
    await _watch_state_cmd(update, context, True)


async def delete_watch_cmd(update, context):
    if not private_admin(update):
        return await deny(update)
    if not context.args or not context.args[0].isdigit():
        await update.effective_message.reply_text("Provide the watch ID, e.g. /deletewatch 3")
        return
    watch_id = int(context.args[0])
    if watch_store.delete(update.effective_user.id, watch_id):
        await update.effective_message.reply_text(f"✅ Watch #{watch_id} deleted.")
    else:
        await update.effective_message.reply_text("Watch not found or not owned by you.")


async def alert_status_cmd(update, context):
    if not private_admin(update):
        return await deny(update)
    rows = watch_store.queue_status_for_owner(update.effective_user.id)
    counts = {row["status"]: row["count"] for row in rows}
    await update.effective_message.reply_text(
        "Alert queue:\n"
        f"pending={counts.get('pending', 0)} | retry={counts.get('retry', 0)} | "
        f"sent={counts.get('sent', 0)} | failed={counts.get('failed', 0)} | "
        f"cancelled={counts.get('cancelled', 0)}"
    )


async def search_help_cmd(update, context):
    if not private_admin(update):
        return await deny(update)
    await update.effective_message.reply_text(
        "Universal Search v1.4 private-owner guide:\n\n"
        "/search iphone 15\n"
        "/search \"iphone 15 pro\"\n"
        "/search iphone OR samsung\n"
        "/search hilux -wanted\n"
        "/search wheels --user @seller --days 30\n"
        "/search exhaust --media --sort newest\n"
        "/crosssearch query\n"
        "/findads query\n\n"
        "Passive alerts:\n"
        "/watch name :: query\n"
        "/watches\n/pausewatch ID\n/resumewatch ID\n/deletewatch ID\n/alertstatus\n\n"
        "All control/search/watch commands work only in your private chat with this bot. "
        "Group messages are indexed passively."
    )


async def health(update, context):
    if not private_admin(update):
        return await deny(update)
    total = store.count()
    live = store.count("live")
    historical = store.count("backfill")
    watches = watch_store.count_for_owner(update.effective_user.id)
    await update.effective_message.reply_text(
        f"✅ Universal Search v1.4\n"
        f"Indexed: {total} messages\n"
        f"Live: {live} | Historical: {historical}\n"
        f"FTS5 ranking: {'enabled' if store.fts_enabled else 'fallback LIKE mode'}\n"
        f"Saved watches: {watches}\n"
        f"Central owner configured: {'yes' if central_owner_ids(ROOT) else 'no'}\n"
        "Control scope: private owner only"
    )


async def market_cmd(update, context):
    if not private_admin(update):
        return await deny(update)
    kinds = {"sale", "wanted", "trade", "service"}
    kind = next((a.lower() for a in context.args if a.lower() in kinds), None)
    status = None; min_price = max_price = None
    for i, arg in enumerate(context.args[:-1]):
        if arg == "--status": status = context.args[i + 1].lower()
        elif arg == "--min":
            with suppress(ValueError): min_price = float(context.args[i + 1])
        elif arg == "--max":
            with suppress(ValueError): max_price = float(context.args[i + 1])
    if status not in {None, "active", "available", "pending", "sold"}: status = None
    rows = store.market_search(kind=kind, status=status, min_price=min_price, max_price=max_price)
    lines = ["Marketplace listings (passive/read-only):"]
    for row in rows:
        price = f"{row['currency']} ${row['price_cents'] / 100:.2f}" if row['price_cents'] is not None else "price n/a"
        lines.append(f"{row['kind']} | {row['status']} | {price} | confidence={row['confidence']:.2f} | group={row['group_key']}")
    await update.effective_message.reply_text("\n".join(lines)[:3900])
    publisher.signal("marketplace_search", subject_type="user", subject_id=update.effective_user.id, score=min(100, len(rows) * 5), confidence=0.95, rationale="Owner-only marketplace read query completed", result_count=len(rows), kind=kind, status=status)


async def listing_cmd(update, context):
    if not private_admin(update): return await deny(update)
    if len(context.args) != 2:
        await update.effective_message.reply_text("Use /listing CHAT_ID MESSAGE_ID"); return
    try: row = store.market_listing(int(context.args[0]), int(context.args[1]))
    except ValueError: row = None
    if not row:
        await update.effective_message.reply_text("Listing not found."); return
    price = f"{row['currency'] or 'AUD'} ${row['price_cents'] / 100:.2f}" if row['price_cents'] is not None else "-"
    await update.effective_message.reply_text("\n".join((f"Listing {row['listing_key']}", f"Kind: {row['kind']}", f"Status: {row['status']}", f"Price: {price}", f"Condition: {row['condition'] or '-'}", f"Location: {row['location'] or '-'}", f"Confidence: {row['confidence']:.2f}", f"Repost group: {row['group_key']}")))


async def pricehistory_cmd(update, context):
    if not private_admin(update): return await deny(update)
    if len(context.args) != 1:
        await update.effective_message.reply_text("Use /pricehistory GROUP_KEY"); return
    rows = store.market_price_history(context.args[0])
    await update.effective_message.reply_text("Price history:\n" + ("\n".join(f"{r['currency']} ${r['price_cents'] / 100:.2f} — {r['observed_utc']}" for r in rows) or "No price history found.")[:3800])


async def marketstats_cmd(update, context):
    if not private_admin(update): return await deny(update)
    rows = store.market_stats()
    await update.effective_message.reply_text("Marketplace stats:\n" + ("\n".join(f"{r['kind']} / {r['status']}: {r['count']}" for r in rows) or "No structured listings yet."))


async def backfill_status_cmd(update, context):
    if not private_admin(update):
        return await deny(update)
    rows = store.backfill_status()
    if not rows:
        await update.effective_message.reply_text(
            "No historical backfill has run yet.\n"
            "Run BACKFILL.ps1 from the Universal_Search folder to begin."
        )
        return
    lines = ["Historical backfill:"]
    for row in rows[:25]:
        title = row["chat_title"] or str(row["chat_id"])
        lines.append(
            f"• {title}: {row['status']} | scanned={row['scanned_messages']} "
            f"| oldest={row['oldest_message_id'] or '-'}"
        )
    if len(rows) > 25:
        lines.append(f"…and {len(rows) - 25} more chats.")
    await update.effective_message.reply_text("\n".join(lines)[:3900])


async def index_message(update, context):
    message = update.effective_message
    if not message or not update.effective_chat:
        return
    user = update.effective_user
    text = message.text or message.caption or ""
    if not text and not message.effective_attachment:
        return
    dt = message.date.astimezone(timezone.utc).isoformat() if message.date else ""
    store.upsert(
        update.effective_chat.id,
        getattr(update.effective_chat, "title", None),
        getattr(update.effective_chat, "username", None),
        user.id if user else None,
        user.username if user else None,
        user.full_name if user else None,
        message.message_id,
        dt,
        text,
        bool(message.effective_attachment),
        source="live",
    )
    row = watch_store.get_message(update.effective_chat.id, message.message_id)
    queued = watch_store.enqueue_matches(row)
    if queued:
        publisher.signal(
            "saved_search_matches_queued",
            subject_type="chat",
            subject_id=update.effective_chat.id,
            score=min(100, queued * 20),
            confidence=0.95,
            rationale="New Telegram message matched saved Universal Search watches",
            queued_alerts=queued,
            message_id=message.message_id,
        )


async def alert_worker(application):
    while True:
        try:
            owners = authorized_owner_ids()
            watch_store.reconcile_owners(owners)
            if not owners:
                await asyncio.sleep(10)
                continue
            alerts = watch_store.due_alerts(20)
            if not alerts:
                await asyncio.sleep(10)
                continue
            for alert in alerts:
                owner = int(alert["owner_user_id"])
                if owner not in owners:
                    continue
                title = html.escape(_short(alert["watch_name"], 60))
                body = f"🔔 <b>Watch matched: {title}</b>\n\n{fmt_row(alert)}"
                try:
                    await application.bot.send_message(
                        chat_id=owner,
                        text=body,
                        parse_mode="HTML",
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    status, due = watch_store.mark_retry(
                        alert["alert_id"], exc, alert["attempts"]
                    )
                    logger.warning(
                        "Saved-search alert delivery failed alert=%s status=%s due=%s error=%s",
                        alert["alert_id"], status, due, type(exc).__name__,
                    )
                    if status == "failed":
                        publisher.incident(
                            "saved_search_alert_failed",
                            "Saved-search alert exhausted retries",
                            severity="WARNING",
                            alert_id=alert["alert_id"],
                            watch_id=alert["watch_id"],
                            error_type=type(exc).__name__,
                        )
                else:
                    watch_store.mark_sent(alert["alert_id"], alert["watch_id"])
                    publisher.signal(
                        "saved_search_alert_sent",
                        subject_type="user",
                        subject_id=owner,
                        score=50,
                        confidence=1.0,
                        rationale="Passive Universal Search watch delivered",
                        watch_id=alert["watch_id"],
                        source_chat_id=alert["chat_id"],
                        source_message_id=alert["message_id"],
                    )
            await asyncio.sleep(1)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Saved-search alert worker loop failed")
            publisher.incident(
                "saved_search_worker_error",
                "Universal Search passive alert worker recovered from an error",
                severity="ERROR",
                error_type=type(exc).__name__,
            )
            await asyncio.sleep(15)


async def post_init(application):
    watch_store.reconcile_owners(authorized_owner_ids())
    pruned = watch_store.cleanup_alert_history()
    if pruned:
        logger.info("Pruned %s expired passive-alert delivery records", pruned)
    application.bot_data["alert_worker_task"] = asyncio.create_task(
        alert_worker(application), name="universal-search-alert-worker"
    )


async def post_shutdown(application):
    task = application.bot_data.get("alert_worker_task")
    if task:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    app = (
        Application.builder()
        .token(TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    app.add_handler(CommandHandler("claim", claim))
    app.add_handler(CommandHandler("search", cmd_search))
    app.add_handler(CommandHandler("crosssearch", cmd_cross))
    app.add_handler(CommandHandler("findads", cmd_ads))
    app.add_handler(CommandHandler("recentsearches", recent_searches_cmd))
    app.add_handler(CommandHandler("watch", watch_cmd))
    app.add_handler(CommandHandler("watches", watches_cmd))
    app.add_handler(CommandHandler("pausewatch", pause_watch_cmd))
    app.add_handler(CommandHandler("resumewatch", resume_watch_cmd))
    app.add_handler(CommandHandler("deletewatch", delete_watch_cmd))
    app.add_handler(CommandHandler("alertstatus", alert_status_cmd))
    app.add_handler(CommandHandler("searchhelp", search_help_cmd))
    app.add_handler(CommandHandler("health", health))
    app.add_handler(CommandHandler("backfillstatus", backfill_status_cmd))
    app.add_handler(CommandHandler("market", market_cmd))
    app.add_handler(CommandHandler("listing", listing_cmd))
    app.add_handler(CommandHandler("pricehistory", pricehistory_cmd))
    app.add_handler(CommandHandler("marketstats", marketstats_cmd))
    app.add_handler(CallbackQueryHandler(search_page_callback, pattern=r"^us:"))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, index_message))
    if not admin_id() and not central_owner_ids(ROOT):
        print(f"[CLAIM CODE] Send /claim {claim_code()} to this bot in a PRIVATE chat from your Telegram account.")
    print("[READY] VM Universal Search v1.4 — passive marketplace enrichment, private-owner control only")
    publisher.started(
        indexed_messages=store.count(),
        fts_enabled=store.fts_enabled,
        passive_alerts=True,
        control_scope="private_owner_only",
        central_owner_configured=bool(central_owner_ids(ROOT)),
    )
    try:
        app.run_polling(allowed_updates=Update.ALL_TYPES)
    except BaseException as exc:
        publisher.incident(
            "process_crash",
            "Universal Search exited unexpectedly",
            severity="CRITICAL",
            error_type=type(exc).__name__,
        )
        raise
    finally:
        publisher.stopped("polling_stopped")


if __name__ == "__main__":
    main()
