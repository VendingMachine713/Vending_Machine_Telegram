import html
import re

from telegram import Update
from telegram.ext import CommandHandler, MessageHandler, filters

from marketplace import MarketplaceStore, parse_market_query


def _money(cents, currency):
    if cents is None:
        return "price unknown"
    if (currency or "AUD") == "AUD":
        return f"${cents / 100:,.2f} AUD"
    return f"{currency or ''} {cents / 100:,.2f}".strip()


def _message_link(row):
    username = (row["chat_username"] or "").lstrip("@")
    if username and re.fullmatch(r"[A-Za-z0-9_]+", username):
        return f"https://t.me/{username}/{row['message_id']}"
    chat_id = str(row["chat_id"])
    if chat_id.startswith("-100") and len(chat_id) > 4:
        return f"https://t.me/c/{chat_id[4:]}/{row['message_id']}"
    return None


def _short(value, limit):
    value = str(value or "")
    return value if len(value) <= limit else value[: limit - 1] + "…"


def format_listing(row, *, detailed=False):
    title = html.escape(_short(row["title"] or "Untitled listing", 120))
    chat = html.escape(_short(row["chat_title"] or row["chat_id"], 70))
    seller = row["sender_username"] or row["display_name"] or row["sender_id"] or "unknown"
    seller = html.escape(_short(seller, 55))
    if row["sender_username"]:
        seller = "@" + seller.lstrip("@")
    price = html.escape(_money(row["price_cents"], row["currency"]))
    parts = [
        f"<b>#{row['id']} {title}</b>",
        f"{html.escape(row['listing_type'])} · {html.escape(row['status'])} · {html.escape(row['category'])}",
        f"<b>{price}</b>",
        f"{chat} — {seller}",
    ]
    details = []
    if row["condition"]:
        details.append(f"condition={row['condition']}")
    if row["location_hint"]:
        details.append(f"location={row['location_hint']}")
    if row["repost_count"] and row["repost_count"] > 1:
        details.append(f"reposts={row['repost_count']}")
    if details:
        parts.append(html.escape(" · ".join(details)))
    if detailed:
        parts.append(f"confidence={float(row['confidence']):.2f}")
        text = _short((row["text"] or "").replace("\n", " "), 650)
        if text:
            parts.append(html.escape(text))
    link = _message_link(row)
    if link:
        parts.append(f'<a href="{html.escape(link, quote=True)}">Open original message</a>')
    return "\n".join(parts)


class MarketplaceController:
    def __init__(self, db_path):
        self.store = MarketplaceStore(db_path)
        self._is_admin = None

    def register(self, app, is_admin):
        self._is_admin = is_admin
        app.add_handler(CommandHandler("marketsearch", self.market_search))
        app.add_handler(CommandHandler("listing", self.listing))
        app.add_handler(CommandHandler("pricehistory", self.price_history))
        app.add_handler(CommandHandler("marketstats", self.market_stats))
        # Core live indexing is group 0. Group 1 enriches the already-persisted message
        # without competing with normal commands/search handlers.
        app.add_handler(
            MessageHandler(filters.ALL & ~filters.COMMAND, self.index_live),
            group=1,
        )

    def is_admin(self, update):
        return bool(self._is_admin and self._is_admin(update))

    async def index_live(self, update, context):
        message = update.effective_message
        chat = update.effective_chat
        if not message or not chat:
            return
        text = message.text or message.caption or ""
        if not text:
            # Media-only messages have no useful marketplace text to extract.
            self.store.remove_for_message(chat.id, message.message_id)
            return
        user = update.effective_user
        sender_id = user.id if user else None
        date_utc = message.date.isoformat() if message.date else None
        self.store.ingest(chat.id, message.message_id, sender_id, date_utc, text)

    async def market_search(self, update: Update, context):
        if not update.effective_chat:
            return
        raw = " ".join(context.args).strip()
        global_requested = bool(re.search(r"(?:^|\s)--global(?:\s|$)", raw, flags=re.I))
        if global_requested and not self.is_admin(update):
            await update.effective_message.reply_text("Global marketplace search is admin only.")
            return
        chat_scope = None if global_requested else update.effective_chat.id
        if update.effective_chat.type == "private" and not global_requested:
            if not self.is_admin(update):
                await update.effective_message.reply_text(
                    "Run marketplace search in the source group. Global marketplace search is admin only."
                )
                return
            chat_scope = None

        q = parse_market_query(raw)
        q.limit = min(q.limit, 10)
        rows, has_more = self.store.search(q, chat_scope)
        if not rows:
            await update.effective_message.reply_text("No structured marketplace matches.")
            return
        body = "\n\n".join(format_listing(row) for row in rows)
        suffix = ""
        if has_more:
            suffix = f"\n\nMore results available: add --page {q.page + 1}."
        text = f"<b>Marketplace results — page {q.page}</b>\n\n{body}{suffix}"
        if len(text) > 3900:
            text = text[:3850] + "\n\nResult display shortened."
        await update.effective_message.reply_text(text, parse_mode="HTML")

    async def _authorised_listing(self, update, listing_id):
        row = self.store.get_listing(listing_id)
        if not row:
            await update.effective_message.reply_text("Listing not found.")
            return None
        if self.is_admin(update):
            return row
        if not update.effective_chat or update.effective_chat.id != row["chat_id"]:
            await update.effective_message.reply_text("That listing is outside this chat's search scope.")
            return None
        return row

    async def listing(self, update: Update, context):
        if not context.args or not context.args[0].isdigit():
            await update.effective_message.reply_text("Use /listing <listing_id>")
            return
        row = await self._authorised_listing(update, int(context.args[0]))
        if row:
            await update.effective_message.reply_text(
                format_listing(row, detailed=True),
                parse_mode="HTML",
            )

    async def price_history(self, update: Update, context):
        if not context.args or not context.args[0].isdigit():
            await update.effective_message.reply_text("Use /pricehistory <listing_id>")
            return
        listing_id = int(context.args[0])
        authorised = await self._authorised_listing(update, listing_id)
        if not authorised:
            return
        listing, rows = self.store.price_history_for_listing(listing_id)
        lines = [f"Price history for #{listing_id} — {listing['title'] or 'Untitled listing'}"]
        if not rows:
            lines.append("No recorded prices.")
        else:
            for row in rows[-20:]:
                lines.append(
                    f"{row['observed_utc']}: {_money(row['price_cents'], row['currency'])} "
                    f"(chat {row['chat_id']}, message {row['message_id']})"
                )
        await update.effective_message.reply_text("\n".join(lines)[:3900])

    async def market_stats(self, update: Update, context):
        if not update.effective_chat:
            return
        global_requested = bool(
            context.args and any(arg.lower() == "--global" for arg in context.args)
        )
        if global_requested and not self.is_admin(update):
            await update.effective_message.reply_text("Global marketplace statistics are admin only.")
            return
        chat_scope = None if global_requested else update.effective_chat.id
        if update.effective_chat.type == "private" and not global_requested:
            if not self.is_admin(update):
                await update.effective_message.reply_text("Run this in the source group.")
                return
            chat_scope = None
        totals, categories = self.store.stats(chat_scope)
        lines = [
            "Marketplace intelligence:",
            f"total={totals['total'] or 0} | available={totals['available'] or 0} | wanted={totals['wanted'] or 0}",
        ]
        if categories:
            lines.append("Top categories: " + ", ".join(f"{r['category']}={r['count']}" for r in categories))
        await update.effective_message.reply_text("\n".join(lines)[:3900])
