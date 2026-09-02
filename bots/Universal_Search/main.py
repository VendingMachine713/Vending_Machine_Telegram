import logging
import secrets
import sys
from datetime import timezone
from pathlib import Path

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from core import Store, parse_query
from envutil import load_env

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.vm_core.publisher import BotEventPublisher

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
    a = admin_id()
    return bool(a and update.effective_user and update.effective_user.id == a)


async def claim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if admin_id():
        await update.effective_message.reply_text("Admin already claimed.")
        return
    supplied = " ".join(context.args).strip().upper()
    if supplied and supplied == claim_code():
        ADMIN_FILE.write_text(str(update.effective_user.id))
        CLAIM_FILE.unlink(missing_ok=True)
        await update.effective_message.reply_text("✅ Universal Search admin claimed.")
    else:
        await update.effective_message.reply_text("Invalid claim code.")


def fmt_row(r):
    who = "@" + r["sender_username"] if r["sender_username"] else (
        r["display_name"] or str(r["sender_id"] or "?")
    )
    chat = r["chat_title"] or str(r["chat_id"])
    text = (r["text"] or "").replace("\n", " ")
    if len(text) > 220:
        text = text[:217] + "..."
    return f"• {chat} — {who}\n{text}"


async def search_cmd(update, context, cross=False, force_ads=False):
    raw = " ".join(context.args)
    if force_ads:
        raw = (raw + " --ads --available").strip()
    q = parse_query(raw)
    if not q.text and not q.ads:
        await update.effective_message.reply_text(
            "Use /search words [--user @name] [--days 7] [--limit 10]"
        )
        return
    rows = store.search(q, None if cross else update.effective_chat.id)
    publisher.signal(
        "search_activity",
        subject_type="chat",
        subject_id=update.effective_chat.id,
        score=min(100, len(rows) * 10),
        confidence=0.9,
        rationale="Universal Search query completed",
        result_count=len(rows),
        cross_chat=bool(cross),
        ads_mode=bool(force_ads),
    )
    if not rows:
        await update.effective_message.reply_text("No matches.")
        return
    await update.effective_message.reply_text("\n\n".join(fmt_row(r) for r in rows)[:3900])


async def cmd_search(update, context):
    await search_cmd(update, context, False, False)


async def cmd_cross(update, context):
    if not is_admin(update):
        await update.effective_message.reply_text("Admin only.")
        return
    await search_cmd(update, context, True, False)


async def cmd_ads(update, context):
    await search_cmd(update, context, True, True)


async def health(update, context):
    total = store.count()
    live = store.count("live")
    historical = store.count("backfill")
    await update.effective_message.reply_text(
        f"✅ Universal Search v1.1\n"
        f"Indexed: {total} messages\n"
        f"Live: {live} | Historical: {historical}"
    )


async def backfill_status_cmd(update, context):
    if not is_admin(update):
        await update.effective_message.reply_text("Admin only.")
        return
    rows = store.backfill_status()
    if not rows:
        await update.effective_message.reply_text(
            "No historical backfill has run yet.\n"
            "Run BACKFILL.ps1 from the Universal_Search folder to begin."
        )
        return
    lines = ["Historical backfill:"]
    for r in rows[:25]:
        title = r["chat_title"] or str(r["chat_id"])
        lines.append(
            f"• {title}: {r['status']} | scanned={r['scanned_messages']} "
            f"| oldest={r['oldest_message_id'] or '-'}"
        )
    if len(rows) > 25:
        lines.append(f"…and {len(rows) - 25} more chats.")
    await update.effective_message.reply_text("\n".join(lines)[:3900])


async def index_message(update, context):
    m = update.effective_message
    if not m or not update.effective_chat:
        return
    u = update.effective_user
    text = m.text or m.caption or ""
    if not text and not m.effective_attachment:
        return
    dt = m.date.astimezone(timezone.utc).isoformat() if m.date else ""
    store.upsert(
        update.effective_chat.id,
        getattr(update.effective_chat, "title", None),
        getattr(update.effective_chat, "username", None),
        u.id if u else None,
        u.username if u else None,
        u.full_name if u else None,
        m.message_id,
        dt,
        text,
        bool(m.effective_attachment),
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
    app.add_handler(CommandHandler("health", health))
    app.add_handler(CommandHandler("backfillstatus", backfill_status_cmd))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, index_message))
    if not admin_id():
        print(f"[CLAIM CODE] Send /claim {claim_code()} to this bot from your Telegram account.")
    print("[READY] VM Universal Search v1.1")
    publisher.started(indexed_messages=store.count())
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
