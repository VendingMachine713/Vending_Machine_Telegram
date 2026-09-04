from __future__ import annotations

from datetime import datetime
from html import escape

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from business_memory import BusinessMemory
from config import Settings
from database import Database


def _contact_label(row) -> str:
    name = row["display_name"] or row["username"] or str(row["telegram_id"])
    if row["username"]:
        return f"{name} (@{row['username']})"
    return str(name)


def _money(minor_units, currency: str = "AUD") -> str:
    if minor_units is None:
        return "amount not recorded"
    return f"{currency} {int(minor_units) / 100:,.2f}"


class BusinessAdmin:
    """Owner-only Telegram commands for the Relationship Manager business memory."""

    def __init__(
        self,
        settings: Settings,
        db: Database,
        memory: BusinessMemory,
        monitor=None,
    ):
        self.settings = settings
        self.db = db
        self.memory = memory
        self.monitor = monitor

    def register(self, app: Application) -> None:
        app.add_handler(CommandHandler("business", self.business))
        app.add_handler(CommandHandler("deal", self.deal))
        app.add_handler(CommandHandler("history", self.history))
        app.add_handler(CommandHandler("clients", self.clients))
        app.add_handler(CommandHandler("suppliers", self.suppliers))
        app.add_handler(CommandHandler("reload", self.reload))
        app.add_handler(CommandHandler("touchbase", self.touchbase))

    async def _allowed(self, update: Update) -> bool:
        user = update.effective_user
        chat = update.effective_chat
        if not user or user.id not in self.settings.admin_ids:
            if update.effective_message:
                await update.effective_message.reply_text("Unauthorised.")
            return False
        if not chat or chat.type != "private":
            if update.effective_message:
                await update.effective_message.reply_text(
                    "Business memory is private. Use these commands in a private chat with the bot."
                )
            return False
        return True

    async def _resolve_contact(self, query: str):
        q = query.strip().lstrip("@")
        if not q:
            return None, "Contact is required."

        if q.lstrip("-").isdigit():
            row = self.db.one("SELECT * FROM contacts WHERE telegram_id=?", (int(q),))
            if row:
                return row, None
        else:
            row = self.db.one(
                "SELECT * FROM contacts WHERE username=? COLLATE NOCASE",
                (q,),
            )
            if row:
                return row, None

            matches = self.db.all(
                """SELECT * FROM contacts
                   WHERE display_name LIKE ? COLLATE NOCASE
                   ORDER BY relationship_score DESC, last_seen DESC
                   LIMIT 3""",
                (f"%{q}%",),
            )
            if len(matches) == 1:
                return matches[0], None
            if len(matches) > 1:
                labels = ", ".join(
                    f"{_contact_label(r)} [{r['telegram_id']}]" for r in matches
                )
                return None, f"More than one contact matched: {labels}"

        if self.monitor is not None:
            try:
                resolved = await self.monitor.resolve_contact(query.strip())
            except Exception:
                resolved = None
            if resolved:
                row = self.db.one(
                    "SELECT * FROM contacts WHERE telegram_id=?",
                    (int(resolved["telegram_id"]),),
                )
                if row:
                    return row, None

        return None, "No matching contact found. Try /person first or run /rescan."

    def _local_date(self, iso_value: str | None) -> str:
        if not iso_value:
            return "unknown"
        try:
            return datetime.fromisoformat(iso_value).astimezone(self.settings.timezone).strftime(
                "%d %b %Y"
            )
        except Exception:
            return iso_value

    async def business(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._allowed(update):
            return
        overview = self.memory.overview()
        text = (
            "<b>💼 VM BUSINESS MEMORY</b>\n\n"
            f"Clients recorded: <b>{overview['clients']}</b>\n"
            f"Suppliers recorded: <b>{overview['suppliers']}</b>\n"
            f"Products tracked: <b>{overview['products']}</b>\n"
            f"Transactions recorded: <b>{overview['transactions']}</b>\n\n"
            "<b>Record a deal</b>\n"
            "<code>/deal client @user | Product | 2 | 120.00 | optional note</code>\n"
            "<code>/deal supplier @user | Product | 10 | 500.00 | optional note</code>\n\n"
            "Amount and note are optional. Amount is the total transaction value in AUD.\n\n"
            "<b>Lookups</b>\n"
            "<code>/history @user</code>\n"
            "<code>/clients [product]</code>\n"
            "<code>/suppliers [product]</code>\n"
            "<code>/reload product</code>\n"
            "<code>/touchbase [days]</code>"
        )
        await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)

    async def deal(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._allowed(update):
            return

        raw = (update.effective_message.text or "").partition(" ")[2].strip()
        parts = [part.strip() for part in raw.split("|")]
        if len(parts) < 2:
            await update.effective_message.reply_text(
                "Usage: /deal client @user | Product | quantity | total AUD | note\n"
                "Only role, contact and product are required."
            )
            return

        head = parts[0].split(maxsplit=1)
        if len(head) != 2 or head[0].lower() not in {"client", "supplier"}:
            await update.effective_message.reply_text(
                "Start with either: /deal client CONTACT | PRODUCT or /deal supplier CONTACT | PRODUCT"
            )
            return

        role, contact_query = head[0].lower(), head[1]
        product = parts[1]
        quantity_raw = parts[2] if len(parts) >= 3 and parts[2] else "1"
        total = parts[3] if len(parts) >= 4 and parts[3] else None
        note = " | ".join(parts[4:]).strip() if len(parts) >= 5 else None

        contact, error = await self._resolve_contact(contact_query)
        if not contact:
            await update.effective_message.reply_text(error or "Contact not found.")
            return

        try:
            quantity = float(quantity_raw)
            tx_id = self.memory.record(
                int(contact["telegram_id"]),
                role,
                product,
                quantity=quantity,
                total=total,
                currency="AUD",
                note=note,
                recorded_by=update.effective_user.id,
            )
        except ValueError as exc:
            await update.effective_message.reply_text(str(exc))
            return

        tx = self.memory.transaction(tx_id)
        summary = self.memory.contact_summary(int(contact["telegram_id"]))
        role_summary = summary["roles"].get(role, {})
        await update.effective_message.reply_text(
            (
                f"<b>✅ Business record #{tx_id}</b>\n"
                f"{escape(_contact_label(contact))}\n"
                f"Role: <b>{escape(role.title())}</b>\n"
                f"Product: <b>{escape(tx['product_name'])}</b>\n"
                f"Quantity: {tx['quantity']:g} {escape(tx['unit'])}\n"
                f"Value: {escape(_money(tx['total_minor_units'], tx['currency']))}\n\n"
                f"Recorded {role} transactions with this contact: "
                f"<b>{role_summary.get('transaction_count', 0)}</b>"
            ),
            parse_mode=ParseMode.HTML,
        )

    async def history(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._allowed(update):
            return
        if not context.args:
            await update.effective_message.reply_text("Usage: /history @username | TelegramID | name")
            return

        contact, error = await self._resolve_contact(" ".join(context.args))
        if not contact:
            await update.effective_message.reply_text(error or "Contact not found.")
            return

        rows = self.memory.history(int(contact["telegram_id"]), limit=15)
        if not rows:
            await update.effective_message.reply_text(
                f"No business history recorded for {_contact_label(contact)} yet."
            )
            return

        lines = [f"<b>📚 BUSINESS HISTORY — {escape(_contact_label(contact))}</b>\n"]
        for row in rows:
            lines.append(
                f"• <b>{escape(row['role'].title())}</b> · {escape(row['product_name'])} · "
                f"{row['quantity']:g} {escape(row['unit'])}\n"
                f"  {escape(_money(row['total_minor_units'], row['currency']))} · "
                f"{escape(self._local_date(row['occurred_at']))}"
            )
        await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

    async def clients(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._allowed(update):
            return
        product = " ".join(context.args).strip() or None
        rows = self.memory.top_clients(product=product, limit=15)
        await self._send_ranked(update, "🏆 TOP CLIENTS", rows, product)

    async def suppliers(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._allowed(update):
            return
        product = " ".join(context.args).strip() or None
        rows = self.memory.top_suppliers(product=product, limit=15)
        await self._send_ranked(update, "📦 TOP SUPPLIERS", rows, product)

    async def _send_ranked(self, update: Update, title: str, rows, product: str | None):
        if not rows:
            suffix = f" for {product}" if product else ""
            await update.effective_message.reply_text(f"No records found{suffix}.")
            return

        heading = title + (f" — {escape(product)}" if product else "")
        lines = [f"<b>{heading}</b>\n"]
        for index, row in enumerate(rows, start=1):
            lines.append(
                f"<b>{index}.</b> {escape(_contact_label(row))}\n"
                f"   Deals: {row['transaction_count']} · Qty: {row['total_quantity']:g} · "
                f"Last: {escape(self._local_date(row['last_transaction_at']))}"
            )
        await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

    async def reload(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._allowed(update):
            return
        product = " ".join(context.args).strip()
        if not product:
            await update.effective_message.reply_text("Usage: /reload Product Name")
            return

        rows = self.memory.reload_candidates(product, limit=20)
        if not rows:
            await update.effective_message.reply_text(
                f"No previous clients recorded for {product}."
            )
            return

        lines = [
            f"<b>🔄 RELOAD CONTACT LIST — {escape(product)}</b>\n",
            "Previous clients ranked by repeat history. Review before messaging; nothing is sent automatically.\n",
        ]
        for index, row in enumerate(rows, start=1):
            lines.append(
                f"<b>{index}.</b> {escape(_contact_label(row))} · "
                f"{row['transaction_count']} deal(s) · qty {row['total_quantity']:g} · "
                f"last {escape(self._local_date(row['last_transaction_at']))}"
            )
        await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

    async def touchbase(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._allowed(update):
            return

        days = 30
        if context.args:
            try:
                days = max(1, min(int(context.args[0]), 3650))
            except ValueError:
                await update.effective_message.reply_text("Usage: /touchbase [days]")
                return

        rows = self.memory.touchbase_candidates(inactive_days=days, limit=20)
        if not rows:
            await update.effective_message.reply_text(
                f"No previous clients have been inactive for {days}+ days."
            )
            return

        lines = [
            f"<b>👋 TOUCH-BASE CANDIDATES — {days}+ DAYS</b>\n",
            "Ranked from established/repeat history. Review individually before contacting.\n",
        ]
        for index, row in enumerate(rows, start=1):
            lines.append(
                f"<b>{index}.</b> {escape(_contact_label(row))} · "
                f"{row['transaction_count']} deal(s) · {row['product_count']} product(s) · "
                f"last {escape(self._local_date(row['last_transaction_at']))}"
            )
        await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
