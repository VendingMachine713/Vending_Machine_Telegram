from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html import escape

from telegram import Update

from admin_bot import AdminBot
from business_memory import BusinessMemory


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
        )

    def profile_snapshot(self, telegram_id: int) -> BusinessProfileSnapshot | None:
        # Preserve BusinessMemory's fail-closed contact validation.
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


def format_dashboard_section(snapshot: BusinessDashboardSnapshot) -> str:
    return (
        "\n\n<b>💼 Business Memory</b>\n"
        f"Clients: <b>{snapshot.clients}</b> · Suppliers: <b>{snapshot.suppliers}</b>\n"
        f"Products: <b>{snapshot.products}</b> · Deals: <b>{snapshot.transactions}</b>\n"
        f"Repeat clients: <b>{snapshot.repeat_clients}</b> · "
        f"Repeat suppliers: <b>{snapshot.repeat_suppliers}</b>\n"
        f"Reconnect {snapshot.reconnect_days}d+: <b>{snapshot.reconnect_candidates}</b>\n"
        "Use <code>/business</code> for business controls."
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


class _MessageSuffixProxy:
    def __init__(self, message, suffix: str):
        self._message = message
        self._suffix = suffix

    def __getattr__(self, name):
        return getattr(self._message, name)

    async def reply_text(self, text, *args, **kwargs):
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
    """AdminBot with private, read-only Business Memory projections embedded."""

    def __init__(self, settings, db, engine, business_memory: BusinessMemory, monitor=None):
        self.business_memory = business_memory
        self.business_views = BusinessViewData(business_memory)
        super().__init__(settings, db, engine, monitor=monitor)

    async def dashboard(self, update: Update, context):
        chat = update.effective_chat
        if not chat or chat.type != "private":
            return await super().dashboard(update, context)

        snapshot = self.business_views.dashboard_snapshot(reconnect_days=30)
        suffix = format_dashboard_section(snapshot)
        return await super().dashboard(_UpdateProxy(update, suffix), context)

    async def _send_profile_to(self, message, c):
        chat = getattr(message, "chat", None)
        if not chat or getattr(chat, "type", None) != "private":
            return await super()._send_profile_to(message, c)

        snapshot = self.business_views.profile_snapshot(int(c["telegram_id"]))
        if snapshot is None:
            return await super()._send_profile_to(message, c)

        suffix = format_profile_section(snapshot, self.settings.timezone)
        return await super()._send_profile_to(_MessageSuffixProxy(message, suffix), c)
