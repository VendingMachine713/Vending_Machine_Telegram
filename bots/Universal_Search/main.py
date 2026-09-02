import html
import logging
import re
import secrets
import sys
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

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.vm_core.publisher import BotEventPublisher
from shared.vm_core.security import owner_authorized, central_owner_ids

publisher = BotEventPublisher("Universal_Search", ROOT)

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
        await update.callback_query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)
    else:
        await update.effective_message.reply_text(text, parse_mode="HTML", reply_markup=keyboard)


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


async def search_help_cmd(update, context):
    if not private_admin(update):
        return await deny(update)
    await update.effective_message.reply_text(
        "Universal Search v1.4 private-owner query guide:\n\n"
        "/search iphone 15\n"
        "/search \"iphone 15 pro\"\n"
        "/search iphone OR samsung\n"
        "/search hilux -wanted\n"
        "/search wheels --user @seller --days 30\n"
        "/search exhaust --media --sort newest\n"
        "/crosssearch query\n"
        "/findads query\n\n"
        "Control/search commands work only in your private chat with this bot."
    )


async def health(update, context):
    if not private_admin(update):
        return await deny(update)
    total = store.count()
    live = store.count("live")
    historical = store.count("backfill")
    await update.effective_message.reply_text(
        f"✅ Universal Search v1.4\n"
        f"Indexed: {total} messages\n"
        f"Live: {live} | Historical: {historical}\n"
        f"FTS5 ranking: {'enabled' if store.fts_enabled else 'fallback LIKE mode'}"
    )


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


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("claim", claim))
    app.add_handler(CommandHandler("search", cmd_search))
    app.add_handler(CommandHandler("crosssearch", cmd_cross))
    app.add_handler(CommandHandler("findads", cmd_ads))
    app.add_handler(CommandHandler("recentsearches", recent_searches_cmd))
    app.add_handler(CommandHandler("searchhelp", search_help_cmd))
    app.add_handler(CommandHandler("health", health))
    app.add_handler(CommandHandler("backfillstatus", backfill_status_cmd))
    app.add_handler(CallbackQueryHandler(search_page_callback, pattern=r"^us:"))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, index_message))
    if not admin_id() and not central_owner_ids(ROOT):
        print(f"[CLAIM CODE] Send /claim {claim_code()} to this bot in a PRIVATE chat from your Telegram account.")
    print("[READY] VM Universal Search v1.4 — passive indexing in groups, central/private-owner control only")
    publisher.started(indexed_messages=store.count(), fts_enabled=store.fts_enabled, control_scope="private_owner_only", central_owner_configured=bool(central_owner_ids(ROOT)))
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
