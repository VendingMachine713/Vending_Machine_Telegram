from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from html import escape

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config import Settings
from database import Database, utcnow
from relationship_engine import RelationshipEngine


def authorised(settings: Settings):
    async def guard(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if not user or user.id not in settings.admin_ids:
            if update.effective_message:
                await update.effective_message.reply_text("Unauthorised.")
            return False
        return True
    return guard


def contact_label(row) -> str:
    name = row["display_name"] or row["username"] or str(row["telegram_id"])
    if row["username"]:
        return f"{name} (@{row['username']})"
    return name


def pretty(value: str | None) -> str:
    return (value or "unknown").replace("_", " ").title()


def crm_stage(row) -> str:
    status = row["activity_status"]
    score = int(row["relationship_score"])
    interactions = int(row["interaction_count"])
    active_days = int(row["active_days"])

    if status == "dormant":
        return "Dormant"
    if status == "cooling":
        return "Cooling"
    if status == "returned":
        return "Returned"
    if interactions == 0:
        return "Discovered"
    if active_days <= 1 and score < 40:
        return "New"
    if score < 50:
        return "Developing"
    if score < 70:
        return "Established"
    if score < 85:
        return "Strong"
    return "VIP Candidate"


class AdminBot:
    def __init__(self, settings: Settings, db: Database, engine: RelationshipEngine, monitor=None):
        self.settings = settings
        self.db = db
        self.engine = engine
        self.monitor = monitor
        self.app = Application.builder().token(settings.bot_token).build()
        self._register()

    def _register(self):
        self.app.add_handler(CommandHandler(["start", "rm", "relationships"], self.dashboard))
        self.app.add_handler(CommandHandler("person", self.person))
        self.app.add_handler(CommandHandler("note", self.note))
        self.app.add_handler(CommandHandler("tag", self.tag))
        self.app.add_handler(CommandHandler("verify", self.verify))
        self.app.add_handler(CommandHandler("type", self.rel_type))
        self.app.add_handler(CommandHandler("followup", self.followup))
        self.app.add_handler(CommandHandler("attention", self.attention))
        self.app.add_handler(CommandHandler("dormant", self.dormant))
        self.app.add_handler(CommandHandler("vip", self.vip))
        self.app.add_handler(CommandHandler("regulars", self.regulars))
        self.app.add_handler(CommandHandler("new", self.new_contacts))
        self.app.add_handler(CommandHandler("cooling", self.cooling))
        self.app.add_handler(CommandHandler("top", self.top_contacts))
        self.app.add_handler(CommandHandler("unverified", self.unverified))
        self.app.add_handler(CommandHandler("followups", self.followups))
        self.app.add_handler(CommandHandler("today", self.today))
        self.app.add_handler(CommandHandler("insights", self.insights))
        self.app.add_handler(CommandHandler("growing", self.growing))
        self.app.add_handler(CommandHandler("slipping", self.slipping))
        self.app.add_handler(CommandHandler("health", self.health))
        self.app.add_handler(CommandHandler("rescan", self.rescan))
        self.app.add_handler(CallbackQueryHandler(self.callback))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.search_message))

    async def allowed(self, update: Update) -> bool:
        user = update.effective_user
        if not user or user.id not in self.settings.admin_ids:
            if update.effective_message:
                await update.effective_message.reply_text("Unauthorised.")
            return False
        return True

    async def dashboard(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update):
            return

        total = self.db.one("SELECT COUNT(*) n FROM contacts")["n"]
        active = self.db.one("SELECT COUNT(*) n FROM contacts WHERE activity_status IN ('active','returned')")["n"]
        cooling = self.db.one("SELECT COUNT(*) n FROM contacts WHERE activity_status='cooling'")["n"]
        vip = self.db.one("SELECT COUNT(*) n FROM contacts WHERE relationship_type='vip'")["n"]
        followups = self.db.one("SELECT COUNT(*) n FROM followups WHERE status='open' AND due_at<=?", (utcnow(),))["n"]
        attention = self.db.one("SELECT COUNT(*) n FROM attention_queue WHERE status='open'")["n"]
        growing = self.db.one(
            "SELECT COUNT(*) n FROM contact_intelligence WHERE momentum_label IN ('growing','surging')"
        )["n"]
        slipping = self.db.one(
            """SELECT COUNT(*) n FROM contact_intelligence i
               JOIN contacts c ON c.telegram_id=i.telegram_id
               WHERE c.relationship_score>=40 AND i.health_score<55"""
        )["n"]
        overdue = self.db.one(
            "SELECT COUNT(*) n FROM attention_queue WHERE status='open' AND category='smart_followup'"
        )["n"]

        text = (
            "<b>🤝 VM RELATIONSHIP INTELLIGENCE</b>\n\n"
            f"👥 Contacts: <b>{total}</b>\n"
            f"🟢 Active/Returned: <b>{active}</b>\n"
            f"🔥 Growing: <b>{growing}</b>\n"
            f"📉 Needs watching: <b>{slipping}</b>\n"
            f"🟡 Cooling: <b>{cooling}</b>\n"
            f"⭐ VIP: <b>{vip}</b>\n"
            f"⏱ Cycle-overdue: <b>{overdue}</b>\n"
            f"🔔 Due follow-ups: <b>{followups}</b>\n"
            f"⚠️ Attention: <b>{attention}</b>\n\n"
            "Open <b>Today</b> first — it is the ranked admin-by-exception inbox."
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎯 Today", callback_data="today"),
             InlineKeyboardButton("📊 Insights", callback_data="insights")],
            [InlineKeyboardButton("🔥 Growing", callback_data="growing"),
             InlineKeyboardButton("📉 Slipping", callback_data="slipping")],
            [InlineKeyboardButton("⚠️ Attention", callback_data="attention"),
             InlineKeyboardButton("🔔 Follow-ups", callback_data="followups")],
            [InlineKeyboardButton("🟡 Cooling", callback_data="cooling"),
             InlineKeyboardButton("💤 Dormant", callback_data="dormant")],
            [InlineKeyboardButton("💪 Top", callback_data="top"),
             InlineKeyboardButton("🆕 New", callback_data="new")],
            [InlineKeyboardButton("⭐ VIPs", callback_data="vip"),
             InlineKeyboardButton("❔ Unverified", callback_data="unverified")],
            [InlineKeyboardButton("🔄 Refresh Contacts", callback_data="rescan"),
             InlineKeyboardButton("🔎 Search Help", callback_data="searchhelp")],
        ])
        await update.effective_message.reply_text(
            text, parse_mode=ParseMode.HTML, reply_markup=kb
        )

    def _find_contacts(self, query: str, limit: int = 10):
        q = query.strip().lstrip("@")
        if q.isdigit():
            rows = self.db.all("SELECT * FROM contacts WHERE telegram_id=? LIMIT ?", (int(q), limit))
        else:
            like = f"%{q}%"
            rows = self.db.all(
                """SELECT * FROM contacts
                   WHERE username LIKE ? COLLATE NOCASE
                      OR display_name LIKE ? COLLATE NOCASE
                   ORDER BY relationship_score DESC, last_seen DESC
                   LIMIT ?""",
                (like, like, limit),
            )
        return rows

    async def person(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update):
            return
        if not context.args:
            await update.effective_message.reply_text("Usage: /person @username | TelegramID | name")
            return
        await self._show_search(update, " ".join(context.args))

    async def search_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update):
            return
        await self._show_search(update, update.effective_message.text)

    async def _show_search(self, update: Update, query: str):
        rows = self._find_contacts(query)

        # If SQLite has never seen this username, ask the authorised Telethon
        # account to resolve it directly, seed the identity, then search again.
        if not rows and self.monitor is not None:
            q = query.strip()
            looks_like_username_or_id = (
                q.startswith("@")
                or q.isdigit()
                or (" " not in q and len(q.lstrip("@")) >= 5)
            )
            if looks_like_username_or_id:
                resolved = await self.monitor.resolve_contact(q)
                if resolved:
                    rows = self._find_contacts(str(resolved["telegram_id"]))

        if not rows:
            await update.effective_message.reply_text(
                "No matching contact found. If this is someone from an existing "
                "group/history, use /rescan to refresh recent accessible contacts."
            )
            return
        if len(rows) == 1:
            await self._send_profile(update, rows[0])
            return

        lines = ["<b>Search results</b>\n"]
        for r in rows:
            lines.append(
                f"• <code>{r['telegram_id']}</code> — {escape(contact_label(r))} "
                f"· {r['relationship_type']} · {r['relationship_score']}/100"
            )
        lines.append("\nUse /person TELEGRAM_ID to open a profile.")
        await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

    def _local_time(self, iso_value: str, date_only: bool = False) -> str:
        try:
            dt = datetime.fromisoformat(iso_value)
            local = dt.astimezone(self.settings.timezone)
            if date_only:
                return local.strftime("%d %b %Y")
            return local.strftime("%d %b %Y, %I:%M %p %Z")
        except Exception:
            return iso_value

    def _next_action(self, c) -> str:
        tid = c["telegram_id"]
        due = self.db.one(
            "SELECT COUNT(*) n FROM followups WHERE telegram_id=? AND status='open' AND due_at<=?",
            (tid, utcnow()),
        )["n"]
        if due:
            return "Follow-up is due now."
        if c["verification_status"] == "restricted":
            return "Review restrictions/risk before engaging."
        if c["activity_status"] == "dormant":
            return "Consider a check-in if this relationship still matters."
        if c["activity_status"] == "cooling":
            return "Relationship is cooling; consider a light check-in."
        if c["relationship_score"] >= 80 and c["relationship_type"] not in {"vip", "admin", "partner"}:
            return "Review as a possible VIP."
        if c["relationship_score"] >= 60 and c["relationship_type"] in {"unknown", "prospect"}:
            return "Classify the relationship type."
        if c["relationship_score"] >= 60 and c["verification_status"] in {"unknown", "pending"}:
            return "Consider verification review."
        if c["interaction_count"] == 0:
            return "No live interaction data yet; keep learning."
        return "No immediate action needed."

    async def _send_profile(self, update: Update, c):
        await self._send_profile_to(update.effective_message, c)

    async def _send_profile_to(self, message, c):
        tid = c["telegram_id"]

        # Always present a freshly calculated score/status when a profile is opened.
        self.engine.recalculate_contact(tid)
        c = self.db.one("SELECT * FROM contacts WHERE telegram_id=?", (tid,))

        groups = self.db.one(
            "SELECT COUNT(*) n FROM contact_groups WHERE telegram_id=?",
            (tid,),
        )["n"]
        tags = [
            r["tag"] for r in self.db.all(
                "SELECT tag FROM tags WHERE telegram_id=? ORDER BY tag", (tid,)
            )
        ]
        notes = self.db.all(
            "SELECT note, created_at FROM notes WHERE telegram_id=? ORDER BY id DESC LIMIT 3",
            (tid,),
        )
        open_followups = self.db.one(
            "SELECT COUNT(*) n FROM followups WHERE telegram_id=? AND status='open'",
            (tid,),
        )["n"]
        attention = self.db.one(
            "SELECT COUNT(*) n FROM attention_queue WHERE telegram_id=? AND status='open'",
            (tid,),
        )["n"]

        cycle = (
            f"{c['typical_cycle_days']:g} days"
            if c["typical_cycle_days"] is not None
            else "Learning..."
        )
        intel = self.engine.get_intelligence(tid, refresh=False)
        stage = pretty(intel["lifecycle_stage"]) if intel else crm_stage(c)
        next_action = intel["suggested_action"] if intel and intel["suggested_action"] else self._next_action(c)
        momentum = pretty(intel["momentum_label"]) if intel else "Learning"
        momentum_icon = {
            "surging": "🚀", "growing": "↑", "stable": "→",
            "cooling": "↓", "fading": "↓↓", "learning": "…",
        }.get((intel["momentum_label"] if intel else "learning"), "…")
        health_score = intel["health_score"] if intel else 50
        overdue_text = (
            f"{intel['days_overdue']} day(s) overdue"
            if intel and intel["days_overdue"] > 0 else "On cycle / learning"
        )

        text = (
            f"<b>👤 {escape(contact_label(c))}</b>\n"
            f"<code>{c['telegram_id']}</code>\n\n"
            f"🏷 Type: <b>{escape(pretty(c['relationship_type']))}</b>\n"
            f"📈 CRM stage: <b>{escape(stage)}</b>\n"
            f"🟢 Status: {escape(pretty(c['activity_status']))}\n"
            f"✅ Verification: {escape(pretty(c['verification_status']))}\n"
            f"🤝 Relationship: <b>{c['relationship_score']}/100</b>\n"
            f"❤️ Health: <b>{health_score}/100</b>\n"
            f"📊 Momentum: <b>{momentum_icon} {escape(momentum)}</b>\n"
            f"🛡 Trust: <b>{c['trust_score']}/100</b>\n\n"
            f"First seen: {escape(self._local_time(c['first_seen'], date_only=True))}\n"
            f"Last seen: {escape(self._local_time(c['last_seen']))}\n"
            f"Interactions: {c['interaction_count']}\n"
            f"Active days: {c['active_days']}\n"
            f"Known groups: {groups}\n"
            f"Typical cycle: {escape(cycle)}\n"
            f"Cycle status: {escape(overdue_text)}\n"
            f"Tags: {escape(', '.join(tags) if tags else 'None')}\n"
            f"Open follow-ups: {open_followups}\n"
            f"Attention items: {attention}\n\n"
            f"<b>Suggested next action</b>\n{escape(next_action)}"
        )

        if notes:
            text += "\n\n<b>Recent private notes</b>"
            for n in notes:
                text += f"\n• {escape(n['note'][:180])}"

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🧠 Intelligence", callback_data=f"intel:{tid}"),
             InlineKeyboardButton("⚠️ Attention", callback_data=f"contact_attention:{tid}")],
            [InlineKeyboardButton("📝 Timeline", callback_data=f"timeline:{tid}"),
             InlineKeyboardButton("🏘 Groups", callback_data=f"groups:{tid}")],
            [InlineKeyboardButton("✅ Verified", callback_data=f"verify:{tid}:verified"),
             InlineKeyboardButton("⭐ Trusted", callback_data=f"verify:{tid}:trusted")],
            [InlineKeyboardButton("Customer", callback_data=f"type:{tid}:customer"),
             InlineKeyboardButton("Regular", callback_data=f"type:{tid}:regular"),
             InlineKeyboardButton("VIP", callback_data=f"type:{tid}:vip")],
            [InlineKeyboardButton("Supplier", callback_data=f"type:{tid}:supplier"),
             InlineKeyboardButton("Partner", callback_data=f"type:{tid}:partner")],
            [InlineKeyboardButton("🔔 +1 day", callback_data=f"quick_followup:{tid}:1d"),
             InlineKeyboardButton("🔔 +7 days", callback_data=f"quick_followup:{tid}:7d"),
             InlineKeyboardButton("🔔 +30 days", callback_data=f"quick_followup:{tid}:30d")],
        ])
        await message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)

    async def note(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update):
            return
        if len(context.args) < 2:
            await update.effective_message.reply_text("Usage: /note TELEGRAM_ID note text")
            return
        tid = int(context.args[0])
        self.engine.add_note(tid, update.effective_user.id, " ".join(context.args[1:]))
        await update.effective_message.reply_text("Private note saved.")

    async def tag(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update):
            return
        if len(context.args) < 2:
            await update.effective_message.reply_text("Usage: /tag TELEGRAM_ID tag")
            return
        self.engine.add_tag(int(context.args[0]), " ".join(context.args[1:]))
        await update.effective_message.reply_text("Tag added.")

    async def verify(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update):
            return
        if len(context.args) < 2:
            await update.effective_message.reply_text("Usage: /verify TELEGRAM_ID unknown|pending|verified|trusted|restricted [reason]")
            return
        tid = int(context.args[0])
        state = context.args[1]
        reason = " ".join(context.args[2:])
        try:
            self.engine.set_verification(tid, state, update.effective_user.id, reason)
            self.engine.recalculate_contact(tid)
            await update.effective_message.reply_text(f"Verification set to {state}.")
        except ValueError as e:
            await update.effective_message.reply_text(str(e))

    async def rel_type(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update):
            return
        if len(context.args) != 2:
            await update.effective_message.reply_text("Usage: /type TELEGRAM_ID customer|regular|vip|supplier|vendor|partner|admin|group_owner|prospect|unknown")
            return
        try:
            self.engine.set_relationship_type(int(context.args[0]), context.args[1], update.effective_user.id)
            self.engine.recalculate_contact(int(context.args[0]))
            await update.effective_message.reply_text("Relationship type updated.")
        except ValueError as e:
            await update.effective_message.reply_text(str(e))

    async def followup(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update):
            return
        if len(context.args) < 2:
            await update.effective_message.reply_text("Usage: /followup TELEGRAM_ID 7d [reason]  (also 12h, 30m)")
            return
        tid = int(context.args[0])
        delta = self._parse_delta(context.args[1])
        if not delta:
            await update.effective_message.reply_text("Time must look like 7d, 12h or 30m.")
            return
        reason = " ".join(context.args[2:]) or "Manual follow-up"
        self.engine.add_followup(tid, datetime.now(timezone.utc) + delta, reason, update.effective_user.id)
        await update.effective_message.reply_text("Follow-up created.")

    @staticmethod
    def _parse_delta(value: str):
        m = re.fullmatch(r"(\d+)([dhm])", value.lower())
        if not m:
            return None
        n, unit = int(m.group(1)), m.group(2)
        return {"d": timedelta(days=n), "h": timedelta(hours=n), "m": timedelta(minutes=n)}[unit]

    async def today(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update):
            return
        await self._send_today(update.effective_message)

    async def _send_today(self, message):
        rows = self.db.all(
            """SELECT a.*, c.username, c.display_name, c.relationship_score,
                      i.health_score, i.momentum_label, i.suggested_action
               FROM attention_queue a
               LEFT JOIN contacts c ON c.telegram_id=a.telegram_id
               LEFT JOIN contact_intelligence i ON i.telegram_id=a.telegram_id
               WHERE a.status='open'
               ORDER BY CASE a.priority
                          WHEN 'red' THEN 1 WHEN 'orange' THEN 2
                          WHEN 'yellow' THEN 3 WHEN 'blue' THEN 4 ELSE 5 END,
                        c.relationship_score DESC, a.created_at ASC"""
        )
        if not rows:
            await message.reply_text("🎯 Today is clear — no relationship actions currently need attention.")
            return

        # Admin-by-exception: show only the single highest-priority item per contact.
        selected = []
        seen = set()
        for r in rows:
            tid = r["telegram_id"]
            key = tid if tid is not None else f"attention:{r['id']}"
            if key in seen:
                continue
            seen.add(key)
            selected.append(r)
            if len(selected) >= 12:
                break

        lines = ["<b>🎯 TODAY'S RELATIONSHIP PRIORITIES</b>\n"]
        buttons = []
        for n, r in enumerate(selected, start=1):
            who = r["display_name"] or r["username"] or str(r["telegram_id"])
            health = r["health_score"] if r["health_score"] is not None else "?"
            momentum = pretty(r["momentum_label"]) if r["momentum_label"] else "Learning"
            lines.append(
                f"<b>{n}. {escape(str(who))}</b> · {escape(r['priority'].upper())}\n"
                f"   {escape(r['title'])}\n"
                f"   Health {health}/100 · {escape(momentum)} · Relationship {r['relationship_score'] or 0}/100"
            )
            if r["telegram_id"]:
                buttons.append([
                    InlineKeyboardButton(
                        f"👤 {str(who)[:24]}", callback_data=f"open:{r['telegram_id']}"
                    ),
                    InlineKeyboardButton(
                        "✅ Clear", callback_data=f"attention_done:{r['id']}"
                    ),
                ])

        await message.reply_text(
            "\n".join(lines),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(buttons) if buttons else None,
        )

    async def growing(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update):
            return
        await self._send_intelligence_list(
            update.effective_message,
            "🔥 Growing relationships",
            "i.momentum_label IN ('growing','surging')",
            "i.momentum_score DESC, c.relationship_score DESC",
        )

    async def slipping(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update):
            return
        await self._send_intelligence_list(
            update.effective_message,
            "📉 Relationships to watch",
            "c.relationship_score>=40 AND i.health_score<55",
            "i.health_score ASC, c.relationship_score DESC",
        )

    async def _send_intelligence_list(self, message, title: str, where: str, order_by: str):
        rows = self.db.all(
            f"""SELECT c.*, i.health_score, i.momentum_label, i.momentum_score,
                       i.lifecycle_stage, i.days_overdue
                FROM contacts c JOIN contact_intelligence i ON i.telegram_id=c.telegram_id
                WHERE {where}
                ORDER BY {order_by} LIMIT 25"""
        )
        if not rows:
            await message.reply_text(f"No {title.lower()} right now.")
            return
        lines = [f"<b>{escape(title)}</b>\n"]
        buttons = []
        for r in rows:
            lines.append(
                f"• {escape(contact_label(r))} · Health <b>{r['health_score']}/100</b> · "
                f"{escape(pretty(r['momentum_label']))} · R {r['relationship_score']}/100"
            )
            if len(buttons) < 10:
                buttons.append([
                    InlineKeyboardButton(
                        f"👤 {contact_label(r)[:38]}", callback_data=f"open:{r['telegram_id']}"
                    )
                ])
        await message.reply_text(
            "\n".join(lines), parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(buttons) if buttons else None,
        )

    async def insights(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update):
            return
        await self._send_insights(update.effective_message)

    async def _send_insights(self, message):
        learned = self.db.one(
            "SELECT COUNT(*) n FROM contacts WHERE typical_cycle_days IS NOT NULL"
        )["n"]
        healthy = self.db.one(
            "SELECT COUNT(*) n FROM contact_intelligence WHERE health_score>=75"
        )["n"]
        watch = self.db.one(
            "SELECT COUNT(*) n FROM contact_intelligence WHERE health_score BETWEEN 50 AND 74"
        )["n"]
        risk = self.db.one(
            "SELECT COUNT(*) n FROM contact_intelligence WHERE health_score<50"
        )["n"]
        growing = self.db.one(
            "SELECT COUNT(*) n FROM contact_intelligence WHERE momentum_label IN ('growing','surging')"
        )["n"]
        declining = self.db.one(
            "SELECT COUNT(*) n FROM contact_intelligence WHERE momentum_label IN ('cooling','fading')"
        )["n"]
        overdue = self.db.one(
            "SELECT COUNT(*) n FROM contact_intelligence WHERE days_overdue>0"
        )["n"]
        unclassified = self.db.one(
            """SELECT COUNT(*) n FROM contacts
               WHERE relationship_type='unknown' AND interaction_count>=3"""
        )["n"]

        top_growing = self.db.all(
            """SELECT c.telegram_id, c.display_name, c.username, i.health_score, i.momentum_score
               FROM contacts c JOIN contact_intelligence i ON i.telegram_id=c.telegram_id
               WHERE i.momentum_label IN ('growing','surging')
               ORDER BY i.momentum_score DESC, c.relationship_score DESC LIMIT 3"""
        )
        at_risk = self.db.all(
            """SELECT c.telegram_id, c.display_name, c.username, c.relationship_score, i.health_score
               FROM contacts c JOIN contact_intelligence i ON i.telegram_id=c.telegram_id
               WHERE c.relationship_score>=40 AND i.health_score<55
               ORDER BY i.health_score ASC, c.relationship_score DESC LIMIT 3"""
        )

        lines = [
            "<b>📊 RELATIONSHIP INTELLIGENCE</b>\n",
            f"❤️ Healthy (75+): <b>{healthy}</b>",
            f"👀 Watch (50–74): <b>{watch}</b>",
            f"⚠️ Low health (&lt;50): <b>{risk}</b>",
            f"🔥 Growing: <b>{growing}</b>",
            f"📉 Cooling/Fading: <b>{declining}</b>",
            f"⏱ Learned cycles: <b>{learned}</b>",
            f"⌛ Outside learned cycle: <b>{overdue}</b>",
            f"🏷 Active but unclassified: <b>{unclassified}</b>",
        ]
        if top_growing:
            lines.append("\n<b>Fastest growing</b>")
            for r in top_growing:
                lines.append(
                    f"• {escape(contact_label(r))} · momentum +{r['momentum_score']} · health {r['health_score']}"
                )
        if at_risk:
            lines.append("\n<b>Highest-value relationships to watch</b>")
            for r in at_risk:
                lines.append(
                    f"• {escape(contact_label(r))} · health {r['health_score']} · relationship {r['relationship_score']}"
                )

        await message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

    async def attention(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update):
            return
        await self._send_attention(update.effective_message)

    async def _send_attention(self, message):
        rows = self.db.all(
            """SELECT a.*, c.username, c.display_name
               FROM attention_queue a
               LEFT JOIN contacts c ON c.telegram_id=a.telegram_id
               WHERE a.status='open'
               ORDER BY CASE priority WHEN 'red' THEN 1 WHEN 'orange' THEN 2 ELSE 3 END,
                        a.created_at ASC LIMIT 20"""
        )
        if not rows:
            await message.reply_text("No open attention items.")
            return

        lines = ["<b>⚠️ VM ATTENTION</b>\n"]
        buttons = []
        for r in rows:
            who = r["display_name"] or r["username"] or r["telegram_id"]
            lines.append(
                f"• <b>{escape(r['priority'].upper())}</b> — "
                f"{escape(str(who))}: {escape(r['title'])}\n"
                f"  {escape((r['details'] or '')[:120])}"
            )
            if r["telegram_id"] and len(buttons) < 10:
                buttons.append([
                    InlineKeyboardButton(
                        f"👤 {str(who)[:22]}",
                        callback_data=f"open:{r['telegram_id']}",
                    ),
                    InlineKeyboardButton(
                        f"✅ Clear #{r['id']}",
                        callback_data=f"attention_done:{r['id']}",
                    ),
                ])

        await message.reply_text(
            "\n".join(lines),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(buttons) if buttons else None,
        )

    async def dormant(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update):
            return
        await self._send_list(update.effective_message, "Dormant", "activity_status='dormant'")

    async def vip(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update):
            return
        await self._send_list(update.effective_message, "VIP", "relationship_type='vip'")

    async def regulars(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update):
            return
        await self._send_list(update.effective_message, "Regulars", "relationship_type='regular'")

    async def new_contacts(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update):
            return
        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        await self._send_list(
            update.effective_message,
            "New / recently discovered",
            f"first_seen>='{cutoff}'",
        )

    async def cooling(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update):
            return
        await self._send_list(
            update.effective_message, "Cooling", "activity_status='cooling'"
        )

    async def top_contacts(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update):
            return
        await self._send_list(
            update.effective_message, "Top relationships", "relationship_score>=40"
        )

    async def unverified(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update):
            return
        await self._send_list(
            update.effective_message,
            "Unverified",
            "verification_status IN ('unknown','pending')",
        )

    async def followups(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update):
            return
        await self._send_followups(update.effective_message)

    async def _send_followups(self, message):
        rows = self.db.all(
            """SELECT f.*, c.username, c.display_name, c.relationship_score
               FROM followups f
               JOIN contacts c ON c.telegram_id=f.telegram_id
               WHERE f.status='open'
               ORDER BY f.due_at ASC LIMIT 20"""
        )
        if not rows:
            await message.reply_text("No open follow-ups.")
            return

        now = datetime.now(timezone.utc)
        lines = ["<b>🔔 OPEN FOLLOW-UPS</b>\n"]
        buttons = []
        for r in rows:
            who = r["display_name"] or r["username"] or str(r["telegram_id"])
            due_dt = datetime.fromisoformat(r["due_at"])
            overdue = due_dt <= now
            marker = "🔴 DUE" if overdue else "🗓"
            local_due = due_dt.astimezone(self.settings.timezone).strftime(
                "%d %b %Y, %I:%M %p"
            )
            lines.append(
                f"• {marker} <code>#{r['id']}</code> — {escape(str(who))}\n"
                f"  {escape(local_due)} · {escape((r['reason'] or 'Follow-up')[:100])}"
            )
            if len(buttons) < 10:
                buttons.append([
                    InlineKeyboardButton(
                        f"✅ Done #{r['id']}",
                        callback_data=f"followup_done:{r['id']}",
                    ),
                    InlineKeyboardButton(
                        f"👤 {str(who)[:24]}",
                        callback_data=f"open:{r['telegram_id']}",
                    ),
                ])

        await message.reply_text(
            "\n".join(lines),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(buttons) if buttons else None,
        )

    async def _send_list(self, message, title: str, where: str):
        rows = self.db.all(
            f"""SELECT * FROM contacts WHERE {where}
                ORDER BY relationship_score DESC, last_seen DESC LIMIT 30"""
        )
        if not rows:
            await message.reply_text(f"No {title.lower()} contacts.")
            return

        lines = [f"<b>{escape(title)}</b>\n"]
        buttons = []
        for r in rows:
            lines.append(
                f"• <code>{r['telegram_id']}</code> — {escape(contact_label(r))} "
                f"· {r['relationship_score']}/100 · {escape(crm_stage(r))}"
            )
            if len(buttons) < 10:
                buttons.append([
                    InlineKeyboardButton(
                        f"👤 {contact_label(r)[:38]}",
                        callback_data=f"open:{r['telegram_id']}",
                    )
                ])
        await message.reply_text(
            "\n".join(lines),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(buttons) if buttons else None,
        )

    async def rescan(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update):
            return
        if self.monitor is None or not self.monitor.ready.is_set():
            await update.effective_message.reply_text(
                "Telegram monitoring account is still connecting. Try /rescan again shortly."
            )
            return

        await update.effective_message.reply_text(
            "🔄 Refreshing recent accessible Telegram contacts in the background. "
            "Live monitoring continues while this runs."
        )
        result = await self.monitor.bootstrap_recent_history()
        if result.get("status") == "already_running":
            await update.effective_message.reply_text(
                "A contact refresh is already running."
            )
            return
        await update.effective_message.reply_text(
            f"✅ Contact refresh complete.\n"
            f"Dialogs checked: {result.get('dialogs', 0)}\n"
            f"Contacts seeded/refreshed: {result.get('contacts', 0)}"
        )

    async def health(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update):
            return
        rows = self.db.all("SELECT * FROM bot_health ORDER BY id DESC LIMIT 10")
        lines = ["<b>Health log</b>"]
        for r in rows:
            lines.append(f"• {escape(r['component'])}: {escape(r['status'])} — {escape((r['details'] or '')[:120])}")
        await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

    async def callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update):
            return
        q = update.callback_query
        await q.answer()
        data = q.data

        if data == "today":
            await self._send_today(q.message)
        elif data == "insights":
            await self._send_insights(q.message)
        elif data == "growing":
            await self._send_intelligence_list(
                q.message, "🔥 Growing relationships",
                "i.momentum_label IN ('growing','surging')",
                "i.momentum_score DESC, c.relationship_score DESC",
            )
        elif data == "slipping":
            await self._send_intelligence_list(
                q.message, "📉 Relationships to watch",
                "c.relationship_score>=40 AND i.health_score<55",
                "i.health_score ASC, c.relationship_score DESC",
            )
        elif data == "attention":
            await self._send_attention(q.message)
        elif data == "followups":
            await self._send_followups(q.message)
        elif data == "cooling":
            await self._send_list(q.message, "Cooling", "activity_status='cooling'")
        elif data == "dormant":
            await self._send_list(q.message, "Dormant", "activity_status='dormant'")
        elif data == "top":
            await self._send_list(q.message, "Top relationships", "relationship_score>=40")
        elif data == "new":
            cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
            await self._send_list(q.message, "New / recently discovered", f"first_seen>='{cutoff}'")
        elif data == "vip":
            await self._send_list(q.message, "VIP", "relationship_type='vip'")
        elif data == "unverified":
            await self._send_list(q.message, "Unverified", "verification_status IN ('unknown','pending')")
        elif data == "searchhelp":
            await q.message.reply_text("Send a name, @username, or use /person TELEGRAM_ID.")
        elif data == "rescan":
            if self.monitor is None or not self.monitor.ready.is_set():
                await q.message.reply_text("Telegram monitoring account is still connecting.")
            else:
                await q.message.reply_text("🔄 Refreshing recent accessible contacts...")
                result = await self.monitor.bootstrap_recent_history()
                if result.get("status") == "already_running":
                    await q.message.reply_text("A contact refresh is already running.")
                else:
                    await q.message.reply_text(
                        f"✅ Contact refresh complete. "
                        f"Dialogs: {result.get('dialogs', 0)} · "
                        f"Contacts: {result.get('contacts', 0)}"
                    )
        elif data.startswith("verify:"):
            _, tid, state = data.split(":", 2)
            self.engine.set_verification(int(tid), state, update.effective_user.id, "Admin bot button")
            self.engine.recalculate_contact(int(tid))
            await q.message.reply_text(f"Verification set to {state}.")
        elif data.startswith("type:"):
            _, tid, reltype = data.split(":", 2)
            self.engine.set_relationship_type(int(tid), reltype, update.effective_user.id)
            self.engine.recalculate_contact(int(tid))
            await q.message.reply_text(f"Relationship type set to {reltype}.")
        elif data.startswith("open:"):
            tid = int(data.split(":", 1)[1])
            c = self.db.one("SELECT * FROM contacts WHERE telegram_id=?", (tid,))
            if c:
                await self._send_profile_to(q.message, c)
            else:
                await q.message.reply_text("Contact no longer exists.")
        elif data.startswith("quick_followup:"):
            _, tid, delta_text = data.split(":", 2)
            delta = self._parse_delta(delta_text)
            if delta:
                self.engine.add_followup(
                    int(tid),
                    datetime.now(timezone.utc) + delta,
                    f"Quick follow-up ({delta_text})",
                    update.effective_user.id,
                )
                await q.message.reply_text(f"🔔 Follow-up set for +{delta_text}.")
        elif data.startswith("followup_done:"):
            followup_id = int(data.split(":", 1)[1])
            if self.engine.complete_followup(followup_id, update.effective_user.id):
                await q.message.reply_text(f"✅ Follow-up #{followup_id} completed.")
            else:
                await q.message.reply_text("Follow-up not found.")
        elif data.startswith("attention_done:"):
            attention_id = int(data.split(":", 1)[1])
            if self.engine.resolve_attention(attention_id, update.effective_user.id):
                await q.message.reply_text(f"✅ Attention item #{attention_id} cleared.")
            else:
                await q.message.reply_text("Attention item was already cleared or not found.")
        elif data.startswith("groups:"):
            tid = int(data.split(":", 1)[1])
            rows = self.db.all(
                """SELECT chat_title, chat_id, first_seen, last_seen, interaction_count
                   FROM contact_groups WHERE telegram_id=?
                   ORDER BY last_seen DESC LIMIT 30""",
                (tid,),
            )
            if not rows:
                await q.message.reply_text("No known groups for this contact.")
            else:
                lines = ["<b>🏘 Known groups</b>"]
                for r in rows:
                    title = r["chat_title"] or str(r["chat_id"])
                    lines.append(
                        f"• {escape(str(title))} · {r['interaction_count']} live interactions\n"
                        f"  Last seen: {escape(self._local_time(r['last_seen']))}"
                    )
                await q.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
        elif data.startswith("timeline:"):
            tid = int(data.split(":")[1])
            rows = self.db.all(
                "SELECT * FROM relationship_events WHERE telegram_id=? ORDER BY id DESC LIMIT 20", (tid,)
            )
            lines = ["<b>Recent timeline</b>"]
            for r in rows:
                lines.append(
                    f"• {escape(self._local_time(r['created_at']))} — "
                    f"{escape(pretty(r['event_type']))}: {escape((r['details'] or '')[:160])}"
                )
            await q.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
        elif data.startswith("intel:"):
            tid = int(data.split(":", 1)[1])
            intel = self.engine.get_intelligence(tid, refresh=True)
            c = self.db.one("SELECT * FROM contacts WHERE telegram_id=?", (tid,))
            if not intel or not c:
                await q.message.reply_text("No intelligence data available yet.")
            else:
                cycle = (
                    f"{c['typical_cycle_days']:g} days"
                    if c["typical_cycle_days"] is not None else "Learning"
                )
                text = (
                    f"<b>🧠 {escape(contact_label(c))}</b>\n\n"
                    f"❤️ Health: <b>{intel['health_score']}/100</b>\n"
                    f"📊 Momentum: <b>{escape(pretty(intel['momentum_label']))}</b> "
                    f"({intel['momentum_score']:+d})\n"
                    f"🧭 Lifecycle: <b>{escape(pretty(intel['lifecycle_stage']))}</b>\n"
                    f"⏱ Typical cycle: {escape(cycle)}\n"
                    f"⌛ Days beyond cycle: {intel['days_overdue']}\n\n"
                    f"<b>Recent 7 days</b>\n"
                    f"Interactions: {intel['recent_7_interactions']} · Active days: {intel['recent_7_active_days']}\n"
                    f"<b>Previous 7 days</b>\n"
                    f"Interactions: {intel['previous_7_interactions']} · Active days: {intel['previous_7_active_days']}\n\n"
                    f"<b>Recommended action</b>\n{escape(intel['suggested_action'] or 'No immediate action needed.')}"
                )
                await q.message.reply_text(text, parse_mode=ParseMode.HTML)
        elif data.startswith("contact_attention:"):
            tid = int(data.split(":")[1])
            rows = self.db.all(
                "SELECT * FROM attention_queue WHERE telegram_id=? AND status='open' ORDER BY id DESC LIMIT 10", (tid,)
            )
            if not rows:
                await q.message.reply_text("No open attention items for this contact.")
            else:
                await q.message.reply_text("\n".join(f"• {r['priority'].upper()} — {r['title']}: {r['details'] or ''}" for r in rows))

    def digest_text(self, weekly: bool = False) -> str:
        total = self.db.one("SELECT COUNT(*) n FROM contacts")["n"]
        new_days = 7 if weekly else 1
        cutoff = (datetime.now(timezone.utc) - timedelta(days=new_days)).isoformat()
        new_contacts = self.db.one("SELECT COUNT(*) n FROM contacts WHERE first_seen>=?", (cutoff,))["n"]
        growing = self.db.one(
            "SELECT COUNT(*) n FROM contact_intelligence WHERE momentum_label IN ('growing','surging')"
        )["n"]
        slipping = self.db.one(
            """SELECT COUNT(*) n FROM contact_intelligence i JOIN contacts c ON c.telegram_id=i.telegram_id
               WHERE c.relationship_score>=40 AND i.health_score<55"""
        )["n"]
        overdue_cycle = self.db.one(
            "SELECT COUNT(*) n FROM contact_intelligence WHERE days_overdue>0"
        )["n"]
        followups = self.db.one(
            "SELECT COUNT(*) n FROM followups WHERE status='open' AND due_at<=?", (utcnow(),)
        )["n"]
        attention = self.db.one("SELECT COUNT(*) n FROM attention_queue WHERE status='open'")["n"]

        top = self.db.all(
            """SELECT a.title, a.priority, c.display_name, c.username
               FROM attention_queue a
               LEFT JOIN contacts c ON c.telegram_id=a.telegram_id
               WHERE a.status='open'
               ORDER BY CASE a.priority WHEN 'red' THEN 1 WHEN 'orange' THEN 2 WHEN 'yellow' THEN 3 ELSE 4 END,
                        a.created_at ASC LIMIT 5"""
        )
        label = "WEEKLY" if weekly else "DAILY"
        text = (
            f"<b>🤝 VM {label} RELATIONSHIP BRIEF</b>\n\n"
            f"👥 Total contacts: <b>{total}</b>\n"
            f"🆕 New: <b>{new_contacts}</b>\n"
            f"🔥 Growing: <b>{growing}</b>\n"
            f"📉 Needs watching: <b>{slipping}</b>\n"
            f"⌛ Outside learned cycle: <b>{overdue_cycle}</b>\n"
            f"🔔 Due follow-ups: <b>{followups}</b>\n"
            f"⚠️ Open attention: <b>{attention}</b>"
        )
        if top:
            text += "\n\n<b>Top priorities</b>"
            for r in top:
                who = r["display_name"] or r["username"] or "Contact"
                text += f"\n• {escape(str(who))}: {escape(r['title'])}"
        text += "\n\nUse /today for the ranked action inbox."
        return text

    async def notify_admins(self, text: str):
        for admin_id in self.settings.admin_ids:
            try:
                await self.app.bot.send_message(admin_id, text, parse_mode=ParseMode.HTML)
            except Exception:
                # Admin may not have started the control bot yet.
                pass

    async def send_daily_digest(self, context: ContextTypes.DEFAULT_TYPE):
        await self.notify_admins(self.digest_text(weekly=False))

    async def send_weekly_digest(self, context: ContextTypes.DEFAULT_TYPE):
        await self.notify_admins(self.digest_text(weekly=True))

    async def start(self):
        await self.app.initialize()

        jq = self.app.job_queue
        if jq:
            import datetime as _dt
            daily_time = _dt.time(
                hour=self.settings.daily_digest_hour,
                minute=0,
                tzinfo=self.settings.timezone,
            )
            weekly_time = _dt.time(
                hour=self.settings.weekly_digest_hour,
                minute=0,
                tzinfo=self.settings.timezone,
            )
            jq.run_daily(self.send_daily_digest, time=daily_time, name="daily_relationship_digest")
            jq.run_daily(
                self.send_weekly_digest,
                time=weekly_time,
                days=(self.settings.weekly_digest_weekday,),
                name="weekly_relationship_digest",
            )

        await self.app.start()
        await self.app.updater.start_polling(drop_pending_updates=True)
        await self.notify_admins("<b>🟢 VM Relationship Manager Online</b>\nPassive monitoring and admin controls are active.")

    async def stop(self):
        await self.app.updater.stop()
        await self.app.stop()
        await self.app.shutdown()
