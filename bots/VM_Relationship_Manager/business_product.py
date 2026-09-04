from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Any

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from business_memory import BusinessMemory, normalise_product_name
from config import Settings
from database import Database


def _contact_label(row) -> str:
    name = row["display_name"] or row["username"] or str(row["telegram_id"])
    if row["username"]:
        return f"{name} (@{row['username']})"
    return str(name)


class ProductBusinessView:
    """Read-only product-centric projection over Business Memory."""

    def __init__(self, db: Database, memory: BusinessMemory):
        self.db = db
        self.memory = memory

    def summary(self, product: str, *, limit: int = 10) -> dict[str, Any] | None:
        normalized = normalise_product_name(product)
        if not normalized:
            raise ValueError("Product name is required.")

        row = self.db.one(
            "SELECT * FROM business_products WHERE normalized_name=? AND active=1",
            (normalized,),
        )
        if not row:
            return None

        stats = self.db.one(
            """SELECT COUNT(*) AS transaction_count,
                      COUNT(DISTINCT CASE WHEN role='client' THEN telegram_id END) AS client_count,
                      COUNT(DISTINCT CASE WHEN role='supplier' THEN telegram_id END) AS supplier_count,
                      COALESCE(SUM(CASE WHEN role='client' THEN quantity ELSE 0 END),0) AS client_quantity,
                      COALESCE(SUM(CASE WHEN role='supplier' THEN quantity ELSE 0 END),0) AS supplier_quantity,
                      COALESCE(SUM(CASE WHEN currency='AUD' THEN total_minor_units ELSE 0 END),0) AS aud_minor,
                      MIN(occurred_at) AS first_transaction_at,
                      MAX(occurred_at) AS last_transaction_at
               FROM business_transactions
               WHERE product_id=?""",
            (row["id"],),
        )

        return {
            "product": dict(row),
            "stats": dict(stats),
            "clients": [dict(r) for r in self.memory.top_clients(product=row["name"], limit=limit)],
            "suppliers": [dict(r) for r in self.memory.top_suppliers(product=row["name"], limit=limit)],
        }


class ProductAdmin:
    """Private admin command for a combined client/supplier product view."""

    def __init__(self, settings: Settings, view: ProductBusinessView):
        self.settings = settings
        self.view = view

    def register(self, app: Application) -> None:
        app.add_handler(CommandHandler("product", self.product))

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
                    "Business memory is private. Use this command in a private chat with the bot."
                )
            return False
        return True

    def _local_date(self, iso_value: str | None) -> str:
        if not iso_value:
            return "unknown"
        try:
            return datetime.fromisoformat(iso_value).astimezone(self.settings.timezone).strftime("%d %b %Y")
        except Exception:
            return iso_value

    async def product(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._allowed(update):
            return

        query = " ".join(context.args).strip()
        if not query:
            await update.effective_message.reply_text("Usage: /product Product Name")
            return

        try:
            summary = self.view.summary(query, limit=10)
        except ValueError as exc:
            await update.effective_message.reply_text(str(exc))
            return

        if not summary:
            await update.effective_message.reply_text(
                f"No business history recorded for {query}."
            )
            return

        product = summary["product"]
        stats = summary["stats"]
        lines = [
            f"<b>📦 PRODUCT MEMORY — {escape(product['name'])}</b>\n",
            f"Deals: <b>{stats['transaction_count']}</b> · "
            f"Clients: <b>{stats['client_count']}</b> · "
            f"Suppliers: <b>{stats['supplier_count']}</b>",
            f"Client qty: {stats['client_quantity']:g} · Supplier qty: {stats['supplier_quantity']:g}",
            f"First: {escape(self._local_date(stats['first_transaction_at']))} · "
            f"Last: {escape(self._local_date(stats['last_transaction_at']))}",
        ]

        if int(stats["aud_minor"] or 0) > 0:
            lines.append(
                f"Recorded AUD value: AUD {int(stats['aud_minor']) / 100:,.2f} "
                "(informational only)"
            )

        lines.append("\n<b>Previous clients</b>")
        if summary["clients"]:
            for index, row in enumerate(summary["clients"], start=1):
                lines.append(
                    f"{index}. {escape(_contact_label(row))} · "
                    f"{row['transaction_count']} deal(s) · qty {row['total_quantity']:g} · "
                    f"last {escape(self._local_date(row['last_transaction_at']))}"
                )
        else:
            lines.append("None recorded.")

        lines.append("\n<b>Previous suppliers</b>")
        if summary["suppliers"]:
            for index, row in enumerate(summary["suppliers"], start=1):
                lines.append(
                    f"{index}. {escape(_contact_label(row))} · "
                    f"{row['transaction_count']} deal(s) · qty {row['total_quantity']:g} · "
                    f"last {escape(self._local_date(row['last_transaction_at']))}"
                )
        else:
            lines.append("None recorded.")

        lines.append("\nRead-only view. No Telegram message is sent to any contact.")
        await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
