from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html import escape

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode

from admin_bot import AdminBot
from business_memory import BusinessMemory
from business_quick_capture import BusinessQuickCapture
from business_signals import BusinessOperatorBrief, BusinessSignals


QUICK_CAPTURE_TTL_SECONDS = 300


@dataclass(frozen=True)
class BusinessDashboardSnapshot:
    clients: int
    suppliers: int
    products: int
    transactions: int
    repeat_clients: int
    repeat_suppliers: int
    reconnect_candidates: int
    reconnect_days: int
    available_products: int


@dataclass(frozen=True)
class BusinessProfileSnapshot:
    telegram_id: int
    roles: tuple[str, ...]
    role_patterns: tuple[str, ...]
    transaction_count: int
    product_count: int
    product_names: tuple[str, ...]
    first_transaction_at: str
    last_transaction_at: str
    aud_minor: int
    recorded_aud_values: int


class BusinessViewData:
    """Read-only business projections for Relationship Manager UI surfaces."""

    def __init__(self, memory: BusinessMemory):
        self.memory = memory
        self.db = memory.db
        self.signals = BusinessSignals(self.db)

    def dashboard_snapshot(
        self,
        *,
        reconnect_days: int = 30,
        now: datetime | None = None,
    ) -> BusinessDashboardSnapshot:
        reconnect_days = max(1, int(reconnect_days))
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            raise ValueError("now must include a timezone")
        cutoff = current.astimezone(timezone.utc) - timedelta(days=reconnect_days)

        overview = self.memory.overview()
        repeat_clients = self.db.one(
            """SELECT COUNT(*) AS n FROM (
                   SELECT telegram_id
                   FROM business_transactions
                   WHERE role='client'
                   GROUP BY telegram_id
                   HAVING COUNT(*) >= 2
               )"""
        )["n"]
        repeat_suppliers = self.db.one(
            """SELECT COUNT(*) AS n FROM (
                   SELECT telegram_id
                   FROM business_transactions
                   WHERE role='supplier'
                   GROUP BY telegram_id
                   HAVING COUNT(*) >= 2
               )"""
        )["n"]
        reconnect_candidates = self.db.one(
            """SELECT COUNT(*) AS n FROM (
                   SELECT telegram_id
                   FROM business_transactions
                   WHERE role='client'
                   GROUP BY telegram_id
                   HAVING MAX(occurred_at) <= ?
               )""",
            (cutoff.isoformat(),),
        )["n"]

        return BusinessDashboardSnapshot(
            clients=int(overview["clients"]),
            suppliers=int(overview["suppliers"]),
            products=int(overview["products"]),
            transactions=int(overview["transactions"]),
            repeat_clients=int(repeat_clients),
            repeat_suppliers=int(repeat_suppliers),
            reconnect_candidates=int(reconnect_candidates),
            reconnect_days=reconnect_days,
            available_products=len(self.signals.available_products()),
        )

    def profile_snapshot(self, telegram_id: int) -> BusinessProfileSnapshot | None:
        self.memory.contact_summary(telegram_id)

        aggregate = self.db.one(
            """SELECT COUNT(*) AS transaction_count,
                      COUNT(DISTINCT product_id) AS product_count,
                      MIN(occurred_at) AS first_transaction_at,
                      MAX(occurred_at) AS last_transaction_at,
                      COALESCE(SUM(CASE WHEN currency='AUD' THEN total_minor_units ELSE 0 END),0) AS aud_minor,
                      SUM(CASE WHEN currency='AUD' AND total_minor_units IS NOT NULL THEN 1 ELSE 0 END) AS recorded_aud_values
               FROM business_transactions
               WHERE telegram_id=?""",
            (telegram_id,),
        )
        if not aggregate or int(aggregate["transaction_count"] or 0) == 0:
            return None

        role_rows = self.db.all(
            """SELECT role, COUNT(*) AS transaction_count
               FROM business_transactions
               WHERE telegram_id=?
               GROUP BY role
               ORDER BY CASE role WHEN 'client' THEN 0 ELSE 1 END, role""",
            (telegram_id,),
        )
        product_rows = self.db.all(
            """SELECT p.name, COUNT(*) AS transaction_count, MAX(t.occurred_at) AS last_transaction_at
               FROM business_transactions t
               JOIN business_products p ON p.id=t.product_id
               WHERE t.telegram_id=?
               GROUP BY p.id
               ORDER BY transaction_count DESC, last_transaction_at DESC, p.name COLLATE NOCASE""",
            (telegram_id,),
        )

        roles = tuple(str(row["role"]) for row in role_rows)
        patterns = tuple(
            ("Repeat " if int(row["transaction_count"]) >= 2 else "One-off ")
            + str(row["role"])
            for row in role_rows
        )

        return BusinessProfileSnapshot(
            telegram_id=int(telegram_id),
            roles=roles,
            role_patterns=patterns,
            transaction_count=int(aggregate["transaction_count"]),
            product_count=int(aggregate["product_count"]),
            product_names=tuple(str(row["name"]) for row in product_rows),
            first_transaction_at=str(aggregate["first_transaction_at"]),
            last_transaction_at=str(aggregate["last_transaction_at"]),
            aud_minor=int(aggregate["aud_minor"] or 0),
            recorded_aud_values=int(aggregate["recorded_aud_values"] or 0),
        )


def _local_date(value: str, tz) -> str:
    try:
        return datetime.fromisoformat(value).astimezone(tz).strftime("%d %b %Y")
    except Exception:
        return value


def _contact_label(row) -> str:
    if hasattr(row, "keys"):
        keys = set(row.keys())
        display_name = row["display_name"] if "display_name" in keys else None
        username = row["username"] if "username" in keys else None
        telegram_id = row["telegram_id"] if "telegram_id" in keys else None
    else:
        display_name = row.get("display_name")
        username = row.get("username")
        telegram_id = row.get("telegram_id")
    name = display_name or username or str(telegram_id or "Unknown")
    return f"{name} (@{username})" if username else str(name)


def format_dashboard_section(snapshot: BusinessDashboardSnapshot) -> str:
    return (
        "\n\n<b>💼 Business Memory</b>\n"
        f"Clients: <b>{snapshot.clients}</b> · Suppliers: <b>{snapshot.suppliers}</b>\n"
        f"Products: <b>{snapshot.products}</b> · Deals: <b>{snapshot.transactions}</b>\n"
        f"Available products: <b>{snapshot.available_products}</b>\n"
        f"Repeat clients: <b>{snapshot.repeat_clients}</b> · "
        f"Repeat suppliers: <b>{snapshot.repeat_suppliers}</b>\n"
        f"Reconnect {snapshot.reconnect_days}d+: <b>{snapshot.reconnect_candidates}</b>\n"
        "Open a contact profile to add a deal with buttons, or use <code>/business</code> for full controls."
    )


def format_profile_section(snapshot: BusinessProfileSnapshot, tz) -> str:
    role_text = ", ".join(role.title() for role in snapshot.roles)
    pattern_text = " · ".join(pattern.title() for pattern in snapshot.role_patterns)

    preview = list(snapshot.product_names[:4])
    product_text = ", ".join(escape(name) for name in preview)
    remaining = snapshot.product_count - len(preview)
    if remaining > 0:
        product_text += f" +{remaining} more"

    text = (
        "\n\n<b>💼 Business Memory</b>\n"
        f"Roles: <b>{escape(role_text)}</b>\n"
        f"Pattern: <b>{escape(pattern_text)}</b>\n"
        f"Transactions: <b>{snapshot.transaction_count}</b>\n"
        f"Products: <b>{snapshot.product_count}</b> — {product_text}\n"
        f"First business: {escape(_local_date(snapshot.first_transaction_at, tz))}\n"
        f"Last business: {escape(_local_date(snapshot.last_transaction_at, tz))}"
    )
    if snapshot.recorded_aud_values:
        text += f"\nRecorded AUD value: <b>${snapshot.aud_minor / 100:,.2f}</b>"
    return text


def format_operator_brief_section(brief: BusinessOperatorBrief, tz) -> str:
    text = (
        "\n\n<b>💼 Business actions</b>\n"
        f"Available products: <b>{brief.available_products}</b> · "
        f"Reload candidates: <b>{brief.reload_candidates}</b>\n"
        f"Dormant clients {brief.inactive_days}d+: <b>{brief.dormant_clients}</b> · "
        f"Repeat dormant: <b>{brief.repeat_dormant_clients}</b>"
    )
    if brief.top_reload:
        text += "\n\n<b>Top reload opportunities</b>"
        for row in brief.top_reload:
            text += (
                f"\n• {escape(_contact_label(row))} · {escape(str(row['product_name']))} · "
                f"{int(row['transaction_count'])} deal(s) · "
                f"last {escape(_local_date(str(row['last_transaction_at']), tz))}"
            )
    if brief.top_dormant:
        text += "\n\n<b>Top reconnect candidates</b>"
        for row in brief.top_dormant:
            text += (
                f"\n• {escape(_contact_label(row))} · {int(row['transaction_count'])} deal(s) · "
                f"last {escape(_local_date(str(row['last_transaction_at']), tz))}"
            )
    text += "\n\nReview first; no contact is messaged automatically."
    return text


class _MessageSuffixProxy:
    def __init__(self, message, suffix: str = "", extra_button_rows=None):
        self._message = message
        self._suffix = suffix
        self._extra_button_rows = list(extra_button_rows or [])

    def __getattr__(self, name):
        return getattr(self._message, name)

    async def reply_text(self, text, *args, **kwargs):
        if self._extra_button_rows:
            current = kwargs.get("reply_markup")
            existing_rows = list(current.inline_keyboard) if isinstance(current, InlineKeyboardMarkup) else []
            kwargs["reply_markup"] = InlineKeyboardMarkup(existing_rows + self._extra_button_rows)
        return await self._message.reply_text(text + self._suffix, *args, **kwargs)


class _UpdateProxy:
    def __init__(self, update: Update, suffix: str):
        self._update = update
        self.effective_user = update.effective_user
        self.effective_chat = update.effective_chat
        self.effective_message = _MessageSuffixProxy(update.effective_message, suffix)

    def __getattr__(self, name):
        return getattr(self._update, name)


class BusinessIntegratedAdminBot(AdminBot):
    """AdminBot with private Business Memory projections and low-touch capture."""

    def __init__(self, settings, db, engine, business_memory: BusinessMemory, monitor=None):
        self.business_memory = business_memory
        self.business_views = BusinessViewData(business_memory)
        self.business_signals = self.business_views.signals
        self.business_quick = BusinessQuickCapture(db, business_memory)
        super().__init__(settings, db, engine, monitor=monitor)

    async def dashboard(self, update: Update, context):
        chat = update.effective_chat
        if not chat or chat.type != "private":
            return await super().dashboard(update, context)

        snapshot = self.business_views.dashboard_snapshot(reconnect_days=30)
        suffix = format_dashboard_section(snapshot)
        return await super().dashboard(_UpdateProxy(update, suffix), context)

    def _profile_quick_buttons(self, telegram_id: int):
        rows = [[
            InlineKeyboardButton("💼 + Client deal", callback_data=f"bq:role:{telegram_id}:client"),
            InlineKeyboardButton("📦 + Supplier deal", callback_data=f"bq:role:{telegram_id}:supplier"),
        ]]
        if self.business_quick.last_transaction(telegram_id) is not None:
            rows.append([
                InlineKeyboardButton("🔁 Repeat last business deal", callback_data=f"bq:repeat:{telegram_id}")
            ])
        return rows

    async def _send_profile_to(self, message, c):
        chat = getattr(message, "chat", None)
        if not chat or getattr(chat, "type", None) != "private":
            return await super()._send_profile_to(message, c)

        telegram_id = int(c["telegram_id"])
        snapshot = self.business_views.profile_snapshot(telegram_id)
        suffix = format_profile_section(snapshot, self.settings.timezone) if snapshot else ""
        proxy = _MessageSuffixProxy(
            message,
            suffix,
            extra_button_rows=self._profile_quick_buttons(telegram_id),
        )
        return await super()._send_profile_to(proxy, c)

    async def _send_today(self, message):
        chat = getattr(message, "chat", None)
        if not chat or getattr(chat, "type", None) != "private":
            return await super()._send_today(message)

        brief = self.business_signals.operator_brief(inactive_days=30, limit=3)
        suffix = format_operator_brief_section(brief, self.settings.timezone)
        return await super()._send_today(_MessageSuffixProxy(message, suffix))

    @staticmethod
    def _clear_quick_state(context) -> None:
        context.user_data.pop("business_quick_capture", None)

    def _set_quick_state(self, context, telegram_id: int, role: str) -> None:
        context.user_data["business_quick_capture"] = {
            "telegram_id": int(telegram_id),
            "role": role,
            "expires_at": time.time() + QUICK_CAPTURE_TTL_SECONDS,
        }

    async def _show_quick_picker(self, message, context, telegram_id: int, role: str) -> None:
        contact = self.business_quick.contact(telegram_id)
        suggestions = self.business_quick.suggestions(telegram_id, role, limit=6)
        self._set_quick_state(context, telegram_id, role)

        rows = []
        pair = []
        for item in suggestions:
            pair.append(
                InlineKeyboardButton(
                    item.name[:28],
                    callback_data=f"bq:prod:{telegram_id}:{role}:{item.product_id}",
                )
            )
            if len(pair) == 2:
                rows.append(pair)
                pair = []
        if pair:
            rows.append(pair)
        rows.append([InlineKeyboardButton("✖ Cancel", callback_data="bq:cancel")])

        if suggestions:
            body = (
                f"<b>Quick {escape(role)} deal — {escape(_contact_label(contact))}</b>\n\n"
                "Tap a product to record <b>1 unit</b> now with no monetary value inferred.\n"
                "Or send a new product name as your next message and it will be created and recorded.\n\n"
                "Use the full <code>/deal</code> command only when quantity, value or a note matters."
            )
        else:
            body = (
                f"<b>Quick {escape(role)} deal — {escape(_contact_label(contact))}</b>\n\n"
                "No products exist yet. Send the product name as your next message.\n"
                "It will be created and recorded as <b>1 unit</b> with no monetary value inferred."
            )
        await message.reply_text(
            body,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(rows),
        )

    async def _confirm_quick_record(self, message, transaction_id: int) -> None:
        tx = self.business_memory.transaction(transaction_id)
        contact = self.db.one("SELECT * FROM contacts WHERE telegram_id=?", (int(tx["telegram_id"]),))
        value = "not recorded" if tx["total_minor_units"] is None else f"{tx['currency']} {int(tx['total_minor_units']) / 100:,.2f}"
        await message.reply_text(
            (
                "<b>✅ Business deal recorded</b>\n"
                f"{escape(_contact_label(contact))}\n"
                f"Role: <b>{escape(str(tx['role']).title())}</b>\n"
                f"Product: <b>{escape(str(tx['product_name']))}</b>\n"
                f"Quantity: {float(tx['quantity']):g} {escape(str(tx['unit']))}\n"
                f"Value: {escape(value)}\n\n"
                "Business Memory, profile history and passive intelligence now read this record automatically."
            ),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("👤 Open profile", callback_data=f"open:{int(tx['telegram_id'])}")
            ]]),
        )

    async def search_message(self, update: Update, context):
        state = context.user_data.get("business_quick_capture")
        if state:
            if float(state.get("expires_at") or 0) < time.time():
                self._clear_quick_state(context)
            else:
                if not await self.allowed(update):
                    return
                text = (update.effective_message.text or "").strip()
                if text.lower() == "cancel":
                    self._clear_quick_state(context)
                    await update.effective_message.reply_text("Quick business capture cancelled.")
                    return
                try:
                    tx_id = self.business_quick.record_product_name(
                        int(state["telegram_id"]),
                        str(state["role"]),
                        text,
                        recorded_by=update.effective_user.id,
                    )
                except ValueError as exc:
                    await update.effective_message.reply_text(str(exc))
                    return
                self._clear_quick_state(context)
                await self._confirm_quick_record(update.effective_message, tx_id)
                return
        return await super().search_message(update, context)

    async def callback(self, update: Update, context):
        q = update.callback_query
        data = str(q.data or "") if q else ""
        if not data.startswith("bq:"):
            return await super().callback(update, context)

        if not await self.allowed(update):
            return
        await q.answer()

        try:
            if data == "bq:cancel":
                self._clear_quick_state(context)
                await q.message.reply_text("Quick business capture cancelled.")
                return

            if data.startswith("bq:role:"):
                _, _, telegram_id, role = data.split(":", 3)
                await self._show_quick_picker(q.message, context, int(telegram_id), role)
                return

            if data.startswith("bq:prod:"):
                _, _, telegram_id, role, product_id = data.split(":", 4)
                tx_id = self.business_quick.record_product_id(
                    int(telegram_id),
                    role,
                    int(product_id),
                    recorded_by=update.effective_user.id,
                )
                self._clear_quick_state(context)
                await self._confirm_quick_record(q.message, tx_id)
                return

            if data.startswith("bq:repeat:"):
                telegram_id = int(data.split(":", 2)[2])
                tx_id = self.business_quick.repeat_last(
                    telegram_id,
                    recorded_by=update.effective_user.id,
                )
                self._clear_quick_state(context)
                await self._confirm_quick_record(q.message, tx_id)
                return
        except (TypeError, ValueError, KeyError) as exc:
            await q.message.reply_text(f"Quick business capture could not complete: {exc}")
            return

        await q.message.reply_text("Unknown quick business action.")
