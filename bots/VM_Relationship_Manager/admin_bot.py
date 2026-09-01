from __future__ import annotations

import re
import json
from datetime import datetime, timedelta, timezone
from html import escape

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
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
from backup_manager import BackupManager
from maintenance_engine import MaintenanceEngine


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
        self.backups = BackupManager(db, settings.backup_dir)
        self.maintenance = MaintenanceEngine(db, settings.backup_dir, engine.integration)
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
        self.app.add_handler(CommandHandler("behavior", self.behavior))
        self.app.add_handler(CommandHandler("network", self.network))
        self.app.add_handler(CommandHandler("bridges", self.bridges))
        self.app.add_handler(CommandHandler("deal", self.deal))
        self.app.add_handler(CommandHandler("deals", self.deals))
        self.app.add_handler(CommandHandler("pipeline", self.pipeline))
        self.app.add_handler(CommandHandler("dealstage", self.dealstage))
        self.app.add_handler(CommandHandler("dealvalue", self.dealvalue))
        self.app.add_handler(CommandHandler("dealnext", self.dealnext))
        self.app.add_handler(CommandHandler("changes", self.changes))
        self.app.add_handler(CommandHandler("privacy", self.privacy))
        self.app.add_handler(CommandHandler("archive", self.archive))
        self.app.add_handler(CommandHandler("restore", self.restore))
        self.app.add_handler(CommandHandler("exclude", self.exclude))
        self.app.add_handler(CommandHandler("include", self.include))
        self.app.add_handler(CommandHandler("forgetbehavior", self.forgetbehavior))
        self.app.add_handler(CommandHandler("purgecontact", self.purgecontact))
        self.app.add_handler(CommandHandler("integrations", self.integrations))
        self.app.add_handler(CommandHandler("export", self.export_data))
        self.app.add_handler(CommandHandler("find", self.find))
        self.app.add_handler(CommandHandler("saveview", self.saveview))
        self.app.add_handler(CommandHandler("views", self.views))
        self.app.add_handler(CommandHandler("view", self.view))
        self.app.add_handler(CommandHandler("lists", self.lists))
        self.app.add_handler(CommandHandler("diagnostics", self.diagnostics))
        self.app.add_handler(CommandHandler("version", self.version))
        self.app.add_handler(CommandHandler("help", self.help))
        self.app.add_handler(CommandHandler("health", self.health))
        self.app.add_handler(CommandHandler("rescan", self.rescan))
        self.app.add_handler(CommandHandler("priority", self.priority))
        self.app.add_handler(CommandHandler("snooze", self.snooze_priority))
        self.app.add_handler(CommandHandler("remember", self.remember))
        self.app.add_handler(CommandHandler("memories", self.memories))
        self.app.add_handler(CommandHandler("forgetmemory", self.forgetmemory))
        self.app.add_handler(CommandHandler("groups", self.groups_overview))
        self.app.add_handler(CommandHandler("group", self.group_detail))
        self.app.add_handler(CommandHandler("risks", self.risks))
        self.app.add_handler(CommandHandler("riskconfirm", self.riskconfirm))
        self.app.add_handler(CommandHandler("riskdismiss", self.riskdismiss))
        self.app.add_handler(CommandHandler("backup", self.backup_now))
        self.app.add_handler(CommandHandler("backups", self.backups_list))
        self.app.add_handler(CommandHandler("report", self.report))
        self.app.add_handler(CommandHandler("forecast", self.forecast))
        self.app.add_handler(CommandHandler("brief", self.brief))
        self.app.add_handler(CommandHandler("goals", self.goals))
        self.app.add_handler(CommandHandler("goal", self.goal_create))
        self.app.add_handler(CommandHandler("goalupdate", self.goal_update))
        self.app.add_handler(CommandHandler("goalcomplete", self.goal_complete))
        self.app.add_handler(CommandHandler("segments", self.segments))
        self.app.add_handler(CommandHandler("segment", self.segment))
        self.app.add_handler(CommandHandler("outlook", self.outlook))
        self.app.add_handler(CommandHandler("sessions", self.sessions))
        self.app.add_handler(CommandHandler("quality", self.quality))
        self.app.add_handler(CommandHandler("playbook", self.playbook))
        self.app.add_handler(CommandHandler("doctor", self.doctor))
        self.app.add_handler(CommandHandler("autonomy", self.autonomy))
        self.app.add_handler(CommandHandler("classify", self.classify))
        self.app.add_handler(CommandHandler("exceptions", self.exceptions))
        self.app.add_handler(CommandHandler("actions", self.actions))
        self.app.add_handler(CommandHandler("actiondone", self.actiondone))
        self.app.add_handler(CommandHandler("actionsnooze", self.actionsnooze))
        self.app.add_handler(CommandHandler("maintain", self.maintain))
        self.app.add_handler(CommandHandler("calibration", self.calibration))
        self.app.add_handler(CommandHandler("policy", self.policy))
        self.app.add_handler(CommandHandler("ops", self.ops))
        self.app.add_handler(CommandHandler("actiondismiss", self.actiondismiss))
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

        total = self.db.one("SELECT COUNT(*) n FROM contacts c LEFT JOIN contact_controls cc ON cc.telegram_id=c.telegram_id WHERE COALESCE(cc.archived,0)=0 AND COALESCE(cc.excluded,0)=0")["n"]
        active = self.db.one("SELECT COUNT(*) n FROM contacts c LEFT JOIN contact_controls cc ON cc.telegram_id=c.telegram_id WHERE c.activity_status IN ('active','returned') AND COALESCE(cc.archived,0)=0 AND COALESCE(cc.excluded,0)=0")["n"]
        cooling = self.db.one("SELECT COUNT(*) n FROM contacts c LEFT JOIN contact_controls cc ON cc.telegram_id=c.telegram_id WHERE c.activity_status='cooling' AND COALESCE(cc.archived,0)=0 AND COALESCE(cc.excluded,0)=0")["n"]
        vip = self.db.one("SELECT COUNT(*) n FROM contacts c LEFT JOIN contact_controls cc ON cc.telegram_id=c.telegram_id WHERE c.relationship_type='vip' AND COALESCE(cc.archived,0)=0 AND COALESCE(cc.excluded,0)=0")["n"]
        followups = self.db.one("SELECT COUNT(*) n FROM followups WHERE status='open' AND due_at<=?", (utcnow(),))["n"]
        attention = self.db.one("SELECT COUNT(*) n FROM attention_queue WHERE status='open'")["n"]
        growing = self.db.one(
            "SELECT COUNT(*) n FROM contact_intelligence i LEFT JOIN contact_controls cc ON cc.telegram_id=i.telegram_id WHERE i.momentum_label IN ('growing','surging') AND COALESCE(cc.archived,0)=0 AND COALESCE(cc.excluded,0)=0"
        )["n"]
        slipping = self.db.one(
            """SELECT COUNT(*) n FROM contact_intelligence i
               JOIN contacts c ON c.telegram_id=i.telegram_id
               WHERE c.relationship_score>=40 AND i.health_score<55"""
        )["n"]
        overdue = self.db.one(
            "SELECT COUNT(*) n FROM attention_queue WHERE status='open' AND category='smart_followup'"
        )["n"]
        opportunity_summary = self.engine.opportunities.summary()
        priority_summary = self.db.one("SELECT COUNT(*) n, COALESCE(MAX(priority_score),0) max_score FROM contact_priorities WHERE priority_score>=50")
        pending_risks = self.db.one("SELECT COUNT(*) n FROM risk_flags WHERE review_status='pending'")["n"]
        group_count = self.db.one("SELECT COUNT(*) n FROM group_metrics")["n"]
        goal_stats = self.engine.goals.stats()
        high_outlook_risk = self.db.one("SELECT COUNT(*) n FROM contact_forecasts WHERE disengagement_risk>=60")["n"] if self.db.table_exists('contact_forecasts') else 0
        segment_count = self.db.one("SELECT COUNT(DISTINCT segment_key) n FROM contact_segments")["n"] if self.db.table_exists('contact_segments') else 0
        classification_stats = self.engine.classification.stats()
        action_stats = self.engine.actions.stats()
        autonomy = self.engine.autonomy.settings()

        text = (
            "<b>ðŸ¤ VM RELATIONSHIP INTELLIGENCE</b>\n\n"
            f"ðŸ‘¥ Contacts: <b>{total}</b>\n"
            f"ðŸŸ¢ Active/Returned: <b>{active}</b>\n"
            f"ðŸ”¥ Growing: <b>{growing}</b>\n"
            f"ðŸ“‰ Needs watching: <b>{slipping}</b>\n"
            f"ðŸŸ¡ Cooling: <b>{cooling}</b>\n"
            f"â­ VIP: <b>{vip}</b>\n"
            f"â± Cycle-overdue: <b>{overdue}</b>\n"
            f"ðŸ”” Due follow-ups: <b>{followups}</b>\n"
            f"âš ï¸ Attention: <b>{attention}</b>\n"
            f"ðŸ’¼ Open opportunities: <b>{opportunity_summary['open']}</b>\n"
            f"ðŸ¤– Autonomy: <b>{escape(autonomy['mode'].upper())}</b> Â· Unknown contacts: <b>{classification_stats['unknown']}</b>\n"
            f"ðŸš¨ Exception actions: <b>{action_stats['exceptions']}</b>\n\n"
            "Open <b>Exceptions</b> first â€” routine relationship maintenance now runs passively."
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("ðŸ§­ Brief", callback_data="brief"),
             InlineKeyboardButton("ðŸš¨ Exceptions", callback_data="exceptions")],
            [InlineKeyboardButton("ðŸ¤– Autonomy", callback_data="autonomy"),
             InlineKeyboardButton("ðŸ§  Classifier", callback_data="classification")],
            [InlineKeyboardButton("ðŸŽ¯ Today", callback_data="today"),
             InlineKeyboardButton("âš™ï¸ Maintain", callback_data="maintain")],
            [InlineKeyboardButton("ðŸ“Š Insights", callback_data="insights"),
             InlineKeyboardButton("ðŸ§© Segments", callback_data="segments")],
            [InlineKeyboardButton("ðŸ”¥ Growing", callback_data="growing"),
             InlineKeyboardButton("ðŸ“‰ Slipping", callback_data="slipping")],
            [InlineKeyboardButton("âš ï¸ Attention", callback_data="attention"),
             InlineKeyboardButton("ðŸ”” Follow-ups", callback_data="followups")],
            [InlineKeyboardButton("ðŸŸ¡ Cooling", callback_data="cooling"),
             InlineKeyboardButton("ðŸ’¤ Dormant", callback_data="dormant")],
            [InlineKeyboardButton("ðŸ’ª Top", callback_data="top"),
             InlineKeyboardButton("ðŸ†• New", callback_data="new")],
            [InlineKeyboardButton("ðŸŒ Network", callback_data="network_overview"),
             InlineKeyboardButton("ðŸŒ‰ Bridges", callback_data="bridges")],
            [InlineKeyboardButton("ðŸ’¼ Pipeline", callback_data="pipeline"),
             InlineKeyboardButton("ðŸŽ¯ Goals", callback_data="goals_overview")],
            [InlineKeyboardButton("ðŸ”­ At Risk", callback_data="segment:disengagement_risk"),
             InlineKeyboardButton("ðŸ§­ Changes", callback_data="changes")],
            [InlineKeyboardButton("â­ VIPs", callback_data="vip"),
             InlineKeyboardButton("â” Unverified", callback_data="unverified")],
            [InlineKeyboardButton("ðŸ“š Lists & Views", callback_data="lists"),
             InlineKeyboardButton("ðŸ”Ž Search Help", callback_data="searchhelp")],
            [InlineKeyboardButton("ðŸ˜ Groups", callback_data="groups_overview"),
             InlineKeyboardButton("ðŸ›¡ Risk Reviews", callback_data="risks")],
            [InlineKeyboardButton("ðŸ“ˆ Report", callback_data="report_weekly"),
             InlineKeyboardButton("ðŸ’° Forecast", callback_data="forecast")],
            [InlineKeyboardButton("ðŸ”„ Refresh Contacts", callback_data="rescan"),
             InlineKeyboardButton("ðŸ©º Diagnostics", callback_data="diagnostics")],
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
                f"â€¢ <code>{r['telegram_id']}</code> â€” {escape(contact_label(r))} "
                f"Â· {r['relationship_type']} Â· {r['relationship_score']}/100"
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
            "SELECT COUNT(*) n FROM contact_groups WHERE telegram_id=? AND chat_id<0",
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
        open_deals = len(self.engine.opportunities.open_for_contact(tid))
        control = self.engine.privacy.control(tid)
        control_state = "Excluded" if control and control["excluded"] else "Archived" if control and control["archived"] else "Active"
        sessions = self.engine.sessions.get(tid, refresh=True)
        quality = self.engine.quality.get(tid, refresh=True)
        outlook = self.engine.forecast.get(tid, refresh=True)
        priority = self.engine.priority.get(tid, refresh=True)
        segments = self.engine.segments.compute(tid)
        classification = self.engine.classification.compute(tid, auto_apply=True)
        self.engine.priority.compute(tid)
        contact_actions = self.engine.actions.for_contact(tid, 5)
        c = self.db.one("SELECT * FROM contacts WHERE telegram_id=?", (tid,))
        playbook = self.engine.playbooks.recommend(tid)
        memories_count = self.db.one("SELECT COUNT(*) n FROM relationship_memories WHERE telegram_id=? AND status='active'", (tid,))["n"]
        pending_risks = self.db.one("SELECT COUNT(*) n FROM risk_flags WHERE telegram_id=? AND review_status='pending'", (tid,))["n"]
        active_goals = self.db.one("SELECT COUNT(*) n FROM relationship_goals WHERE telegram_id=? AND status='active'", (tid,))["n"]

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
            "surging": "ðŸš€", "growing": "â†‘", "stable": "â†’",
            "cooling": "â†“", "fading": "â†“â†“", "learning": "â€¦",
        }.get((intel["momentum_label"] if intel else "learning"), "â€¦")
        health_score = intel["health_score"] if intel else 50
        behavior = self.engine.get_behavior(tid, refresh=False)
        behavior_label = pretty(behavior["behavior_label"]) if behavior else "Learning"
        reciprocity = behavior["reciprocity_score"] if behavior else 50
        network = self.engine.get_network(tid, refresh=False)
        reach = network["reach_score"] if network else 0
        bridge = network["bridge_score"] if network else 0
        overdue_text = (
            f"{intel['days_overdue']} day(s) overdue"
            if intel and intel["days_overdue"] > 0 else "On cycle / learning"
        )
        outlook_text = pretty(outlook["outlook_label"]) if outlook else "Learning"
        outlook_risk = int(outlook["disengagement_risk"] or 0) if outlook else 0
        outlook_conf = int(outlook["confidence"] or 0) if outlook else 0
        quality_conf = int(quality["confidence_score"] or 0) if quality else 0
        quality_complete = int(quality["completeness_score"] or 0) if quality else 0
        session_label = pretty(sessions["session_label"]) if sessions else "Learning"
        session_count = int(sessions["sessions_30"] or 0) if sessions else 0
        segment_text = ", ".join(pretty(x["segment_key"]) for x in segments[:4]) if segments else "Learning"
        playbook_name = pretty(playbook["name"]) if playbook else "Learning"
        classification_text = (f"{pretty(classification['predicted_type'])} {classification['confidence']}%"
                               if classification and classification['predicted_type'] != 'unknown' else 'Learning / abstained')
        action_count = len(contact_actions)

        text = (
            f"<b>ðŸ‘¤ {escape(contact_label(c))}</b>\n"
            f"<code>{c['telegram_id']}</code>\n\n"
            f"ðŸ· Type: <b>{escape(pretty(c['relationship_type']))}</b>\n"
            f"ðŸ¤– Classifier: <b>{escape(classification_text)}</b>\n"
            f"ðŸ“ˆ CRM stage: <b>{escape(stage)}</b>\n"
            f"ðŸŸ¢ Status: {escape(pretty(c['activity_status']))}\n"
            f"âœ… Verification: {escape(pretty(c['verification_status']))}\n"
            f"ðŸ¤ Relationship: <b>{c['relationship_score']}/100</b>\n"
            f"â¤ï¸ Health: <b>{health_score}/100</b>\n"
            f"ðŸ“Š Momentum: <b>{momentum_icon} {escape(momentum)}</b>\n"
            f"ðŸ” Reciprocity: <b>{reciprocity}/100</b> Â· {escape(behavior_label)}\n"
            f"ðŸŒ Network reach: <b>{reach}/100</b> Â· Bridge {bridge}/100\n"
            f"ðŸ›¡ Trust: <b>{c['trust_score']}/100</b>\n"
            f"ðŸ”­ Outlook: <b>{escape(outlook_text)}</b> Â· risk {outlook_risk}/100 Â· confidence {outlook_conf}/100\n"
            f"ðŸ’¬ Private sessions (30d): <b>{session_count}</b> Â· {escape(session_label)}\n"
            f"ðŸ§ª Data confidence: <b>{quality_conf}/100</b> Â· completeness {quality_complete}/100\n"
            f"ðŸ§© Segments: {escape(segment_text)}\n\n"
            f"First seen: {escape(self._local_time(c['first_seen'], date_only=True))}\n"
            f"Last seen: {escape(self._local_time(c['last_seen']))}\n"
            f"Interactions: {c['interaction_count']}\n"
            f"Active days: {c['active_days']}\n"
            f"Known groups: {groups}\n"
            f"Typical cycle: {escape(cycle)}\n"
            f"Cycle status: {escape(overdue_text)}\n"
            f"Tags: {escape(', '.join(tags) if tags else 'None')}\n"
            f"Open follow-ups: {open_followups}\n"
            f"Attention items: {attention}\n"
            f"Open opportunities: {open_deals}\n"
            f"Active goals: {active_goals} Â· Recommended actions: {action_count}\n"
            f"Suggested playbook: {escape(playbook_name)}\n"
            f"CRM control: {escape(control_state)}\n\n"
            f"<b>Suggested next action</b>\n{escape(next_action)}"
        )

        if notes:
            text += "\n\n<b>Recent private notes</b>"
            for n in notes:
                text += f"\nâ€¢ {escape(n['note'][:180])}"

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("ðŸ§  Intelligence", callback_data=f"intel:{tid}"),
             InlineKeyboardButton("ðŸ” Behaviour", callback_data=f"behavior:{tid}")],
            [InlineKeyboardButton("ðŸŽ¯ Priority", callback_data=f"priority:{tid}"),
             InlineKeyboardButton("ðŸ§  Classifier", callback_data=f"classification:{tid}")],
            [InlineKeyboardButton("ðŸ§­ Actions", callback_data=f"contact_actions:{tid}"),
             InlineKeyboardButton("ðŸ§  Memory", callback_data=f"memories:{tid}")],
            [InlineKeyboardButton("ðŸ”­ Outlook", callback_data=f"outlook:{tid}"),
             InlineKeyboardButton("ðŸŽ¯ Goals", callback_data=f"goals:{tid}")],
            [InlineKeyboardButton("ðŸ’¬ Sessions", callback_data=f"sessions:{tid}"),
             InlineKeyboardButton("ðŸ§­ Playbook", callback_data=f"playbook:{tid}")],
            [InlineKeyboardButton("âš ï¸ Attention", callback_data=f"contact_attention:{tid}"),
             InlineKeyboardButton("ðŸ“ Timeline", callback_data=f"timeline:{tid}")],
            [InlineKeyboardButton("ðŸ˜ Groups", callback_data=f"groups:{tid}"),
             InlineKeyboardButton("ðŸŒ Network", callback_data=f"network:{tid}")],
            [InlineKeyboardButton("ðŸ’¼ Opportunities", callback_data=f"deals:{tid}")],
            [InlineKeyboardButton("ðŸ“¦ Archive", callback_data=f"archive:{tid}"),
             InlineKeyboardButton("ðŸš« Exclude", callback_data=f"exclude:{tid}")],
            [InlineKeyboardButton("âœ… Verified", callback_data=f"verify:{tid}:verified"),
             InlineKeyboardButton("â­ Trusted", callback_data=f"verify:{tid}:trusted")],
            [InlineKeyboardButton("Customer", callback_data=f"type:{tid}:customer"),
             InlineKeyboardButton("Regular", callback_data=f"type:{tid}:regular"),
             InlineKeyboardButton("VIP", callback_data=f"type:{tid}:vip")],
            [InlineKeyboardButton("Supplier", callback_data=f"type:{tid}:supplier"),
             InlineKeyboardButton("Partner", callback_data=f"type:{tid}:partner")],
            [InlineKeyboardButton("ðŸ”” +1 day", callback_data=f"quick_followup:{tid}:1d"),
             InlineKeyboardButton("ðŸ”” +7 days", callback_data=f"quick_followup:{tid}:7d"),
             InlineKeyboardButton("ðŸ”” +30 days", callback_data=f"quick_followup:{tid}:30d")],
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
        tid = int(context.args[0])
        self.engine.add_tag(tid, " ".join(context.args[1:]))
        self.engine.classification.compute(tid, auto_apply=True)
        self.engine.actions.compute(tid)
        await update.effective_message.reply_text("Tag added; classifier refreshed.")

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
        # Refresh rankings so Today reflects all current signals, not just raw attention rows.
        self.engine.priority.refresh_all()
        rows = self.engine.priority.top(12)
        if not rows or all(int(r["priority_score"] or 0) == 0 for r in rows):
            await message.reply_text("ðŸŽ¯ Today is clear â€” no relationship actions currently need attention.")
            return
        rows = [r for r in rows if int(r["priority_score"] or 0) > 0]
        lines = ["<b>ðŸŽ¯ TODAY'S RELATIONSHIP PRIORITIES</b>\n"]
        buttons = []
        for n, r in enumerate(rows, start=1):
            who = r["display_name"] or r["username"] or str(r["telegram_id"])
            health = r["health_score"] if r["health_score"] is not None else "?"
            momentum = pretty(r["momentum_label"]) if r["momentum_label"] else "Learning"
            lines.append(
                f"<b>{n}. {escape(str(who))}</b> Â· {escape(r['priority_band'].upper())} Â· <b>{r['priority_score']}/100</b>\n"
                f"   {escape(r['next_action'] or 'Review relationship')}\n"
                f"   Health {health}/100 Â· {escape(momentum)} Â· Relationship {r['relationship_score'] or 0}/100"
            )
            buttons.append([
                InlineKeyboardButton(f"ðŸ‘¤ {str(who)[:24]}", callback_data=f"open:{r['telegram_id']}"),
                InlineKeyboardButton("ðŸ§  Why", callback_data=f"priority:{r['telegram_id']}"),
            ])
        await message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML,
                                 reply_markup=InlineKeyboardMarkup(buttons) if buttons else None)

    async def priority(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update): return
        if not context.args:
            await self._send_today(update.effective_message); return
        try: tid=int(context.args[0])
        except ValueError:
            rows=self._find_contacts(context.args[0],1)
            if not rows: await update.effective_message.reply_text("Contact not found."); return
            tid=rows[0]["telegram_id"]
        await self._send_priority(update.effective_message,tid)

    async def _send_priority(self, message, tid: int):
        p=self.engine.priority.get(tid,refresh=True)
        c=self.db.one("SELECT * FROM contacts WHERE telegram_id=?",(tid,))
        if not p or not c: await message.reply_text("Priority data unavailable."); return
        reasons=self.engine.priority.reasons(tid)
        lines=[f"<b>ðŸŽ¯ Priority Â· {escape(contact_label(c))}</b>",
               f"Score: <b>{p['priority_score']}/100</b> Â· {escape(pretty(p['priority_band']))}",
               f"Next action: {escape(p['next_action'] or 'No immediate action needed.')}"]
        if reasons:
            lines.append("\n<b>Why</b>")
            for r in reasons[:8]:
                lines.append(f"â€¢ +{r['points']} Â· {escape(r['text'])}")
        kb=InlineKeyboardMarkup([[InlineKeyboardButton("ðŸ˜´ Snooze 1d",callback_data=f"priority_snooze:{tid}:1d"),InlineKeyboardButton("ðŸ˜´ Snooze 7d",callback_data=f"priority_snooze:{tid}:7d")]]) if int(p['priority_score'] or 0)>0 else None
        await message.reply_text("\n".join(lines),parse_mode=ParseMode.HTML,reply_markup=kb)

    async def snooze_priority(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update): return
        if len(context.args)!=2: await update.effective_message.reply_text("Usage: /snooze TELEGRAM_ID 1d|7d|30d|0d"); return
        try: tid=int(context.args[0])
        except ValueError: await update.effective_message.reply_text("Telegram ID must be numeric."); return
        delta=self._parse_delta(context.args[1])
        if delta is None: await update.effective_message.reply_text("Time must look like 1d, 7d, 30d or 0d."); return
        until=(datetime.now(timezone.utc)+delta).isoformat() if delta.total_seconds()>0 else None
        self.engine.priority.snooze(tid,until)
        await update.effective_message.reply_text("Priority snoozed." if until else "Priority snooze cleared.")

    async def remember(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update): return
        if len(context.args)<4:
            await update.effective_message.reply_text("Usage: /remember TELEGRAM_ID CATEGORY KEY VALUE...\nCategories: preference, context, commitment, boundary, commercial, admin, custom")
            return
        try:
            tid=int(context.args[0]); category=context.args[1]; key=context.args[2]; value=" ".join(context.args[3:])
            row=self.engine.memory.add(tid,category,key,value,update.effective_user.id)
            self.engine.event(tid,"memory_added",f"{row['category']}:{row['memory_key']}")
            self.engine.integration.emit("memory_changed",tid,{"action":"added","category":row['category'],"key":row['memory_key']})
            self.engine.classification.compute(tid, auto_apply=True)
            self.engine.actions.compute(tid)
            await update.effective_message.reply_text(f"ðŸ§  Saved memory #{row['id']}: {row['memory_key']} = {row['memory_value']}")
        except (ValueError,TypeError) as exc:
            await update.effective_message.reply_text(str(exc))

    async def memories(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update): return
        if not context.args: await update.effective_message.reply_text("Usage: /memories TELEGRAM_ID"); return
        try: tid=int(context.args[0])
        except ValueError: await update.effective_message.reply_text("Telegram ID must be numeric."); return
        await self._send_memories(update.effective_message,tid)

    async def _send_memories(self, message, tid:int):
        c=self.db.one("SELECT * FROM contacts WHERE telegram_id=?",(tid,))
        rows=self.engine.memory.list(tid)
        if not c: await message.reply_text("Contact not found."); return
        lines=[f"<b>ðŸ§  Relationship Memory Â· {escape(contact_label(c))}</b>"]
        for r in rows:
            lines.append(f"â€¢ <code>#{r['id']}</code> {escape(pretty(r['category']))} Â· <b>{escape(r['memory_key'])}</b>: {escape(r['memory_value'])}")
        if not rows: lines.append("No structured memories saved yet.")
        await message.reply_text("\n".join(lines),parse_mode=ParseMode.HTML)

    async def forgetmemory(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update): return
        if not context.args: await update.effective_message.reply_text("Usage: /forgetmemory MEMORY_ID"); return
        try: mid=int(context.args[0])
        except ValueError: await update.effective_message.reply_text("Memory ID must be numeric."); return
        self.engine.memory.delete(mid); await update.effective_message.reply_text(f"Memory #{mid} removed from active memory.")

    async def groups_overview(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update): return
        self.engine.groups.compute_all(); await self._send_groups_overview(update.effective_message)

    async def _send_groups_overview(self, message):
        rows=self.engine.groups.overview(20)
        lines=["<b>ðŸ˜ GROUP INTELLIGENCE</b>"]
        kb=[]
        for r in rows:
            lines.append(f"â€¢ {escape(str(r['chat_title'] or r['chat_id']))} Â· value <b>{r['group_value_score']}/100</b> Â· contacts {r['known_contacts']} Â· active30 {r['active_contacts_30']}")
            if len(kb)<12: kb.append([InlineKeyboardButton(str(r['chat_title'] or r['chat_id'])[:38],callback_data=f"group:{r['chat_id']}")])
        if not rows: lines.append("No group intelligence is available yet.")
        await message.reply_text("\n".join(lines),parse_mode=ParseMode.HTML,reply_markup=InlineKeyboardMarkup(kb) if kb else None)

    async def group_detail(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update): return
        if not context.args: await update.effective_message.reply_text("Usage: /group CHAT_ID"); return
        try: gid=int(context.args[0])
        except ValueError: await update.effective_message.reply_text("Chat ID must be numeric."); return
        await self._send_group_detail(update.effective_message,gid)

    async def _send_group_detail(self, message, gid:int):
        g=self.engine.groups.get(gid,refresh=True)
        if not g: await message.reply_text("Group not found in known relationship data."); return
        rows=self.engine.groups.top_contacts(gid,10)
        lines=[f"<b>ðŸ˜ {escape(str(g['chat_title'] or gid))}</b>",
               f"Value: <b>{g['group_value_score']}/100</b> Â· Known contacts: {g['known_contacts']} Â· Active30: {g['active_contacts_30']}",
               f"Interactions30: {g['interactions_30']} Â· VIP: {g['vip_contacts']} Â· Commercial: {g['commercial_contacts']} Â· Bridges: {g['bridge_contacts']}",
               f"Average relationship score: {g['avg_relationship_score']}","","<b>Top contacts</b>"]
        kb=[]
        for r in rows:
            lines.append(f"â€¢ {escape(contact_label(r))} Â· R {r['relationship_score']} Â· H {r['health_score']} Â· group interactions {r['group_interactions']}")
            kb.append([InlineKeyboardButton(contact_label(r)[:38],callback_data=f"open:{r['telegram_id']}")])
        await message.reply_text("\n".join(lines),parse_mode=ParseMode.HTML,reply_markup=InlineKeyboardMarkup(kb[:10]) if kb else None)

    async def risks(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update): return
        await self._send_risks(update.effective_message)

    async def _send_risks(self, message):
        rows=self.engine.risk.pending(20)
        lines=["<b>ðŸ›¡ PENDING RISK REVIEWS</b>"]
        kb=[]
        for r in rows:
            who=r['display_name'] or r['username'] or str(r['telegram_id'])
            lines.append(f"â€¢ <code>#{r['id']}</code> {escape(str(who))} Â· severity {r['severity']}/5 Â· {escape(r['source'])}: {escape((r['reason'] or '')[:160])}")
            if len(kb)<10:
                kb.append([InlineKeyboardButton(f"âœ… Confirm #{r['id']}",callback_data=f"riskconfirm:{r['id']}"),InlineKeyboardButton("âŒ Dismiss",callback_data=f"riskdismiss:{r['id']}")])
        if not rows: lines.append("No pending risk signals.")
        await message.reply_text("\n".join(lines),parse_mode=ParseMode.HTML,reply_markup=InlineKeyboardMarkup(kb) if kb else None)

    async def riskconfirm(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self._risk_review_command(update,context,"confirmed")

    async def riskdismiss(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self._risk_review_command(update,context,"dismissed")

    async def _risk_review_command(self, update, context, status):
        if not await self.allowed(update): return
        if not context.args: await update.effective_message.reply_text(f"Usage: /risk{'confirm' if status=='confirmed' else 'dismiss'} FLAG_ID"); return
        try: fid=int(context.args[0]); tid=self.engine.risk.review(fid,status,update.effective_user.id); self.engine.recalculate_contact(tid); self.engine.integration.emit("risk_reviewed",tid,{"flag_id":fid,"status":status}); await update.effective_message.reply_text(f"Risk #{fid} â†’ {status}. Trust/priority recalculated.")
        except (ValueError,TypeError) as exc: await update.effective_message.reply_text(str(exc))

    async def backup_now(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update): return
        try:
            r=self.backups.create("manual")
            await update.effective_message.reply_text(f"âœ… Backup {r['status']}.\n{r['path']}\nSHA-256: {r['sha256'][:16]}â€¦")
        except Exception as exc: await update.effective_message.reply_text(f"Backup failed: {exc}")

    async def backups_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update): return
        rows=self.backups.recent(10); lines=["<b>ðŸ’¾ VERIFIED BACKUPS</b>"]
        for r in rows: lines.append(f"â€¢ {escape(self._local_time(r['created_at']))} Â· {escape(r['integrity_status'])} Â· {r['size_bytes']} bytes Â· {escape(r['kind'])}")
        if not rows: lines.append("No v3 backup audit entries yet.")
        await update.effective_message.reply_text("\n".join(lines),parse_mode=ParseMode.HTML)

    async def report(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update): return
        period=(context.args[0].lower() if context.args else "weekly")
        if period not in {"weekly","monthly"}: await update.effective_message.reply_text("Usage: /report weekly|monthly"); return
        r=self.engine.reporting.build(period); await self._send_report(update.effective_message,r)

    async def _send_report(self, message, r):
        m=r.get('momentum',{})
        text=(f"<b>ðŸ“ˆ {escape(r['period'].upper())} RELATIONSHIP REPORT</b>\n\n"
              f"Contacts: <b>{r['total_contacts']}</b> Â· Active: <b>{r['active_contacts']}</b> Â· New: <b>{r['new_contacts']}</b>\n"
              f"Average health: <b>{r['average_health']}/100</b>\n"
              f"Growing/surging: {m.get('growing',0)+m.get('surging',0)} Â· Cooling/fading: {m.get('cooling',0)+m.get('fading',0)}\n"
              f"Due follow-ups: {r['due_followups']} Â· Open opportunities: {r['open_opportunities']} Â· Won: {r['won_opportunities']}\n"
              f"Pending risk reviews: {r['pending_risk_reviews']}")
        await message.reply_text(text,parse_mode=ParseMode.HTML)

    async def forecast(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update): return
        await self.forecast_from_message(update.effective_message)

    async def forecast_from_message(self, message):
        self.engine.opportunities.evaluate_all()
        s=self.engine.opportunities.summary(); lines=["<b>ðŸ’° OPPORTUNITY FORECAST</b>",f"Open/paused: <b>{s['open']}</b> Â· unhealthy: <b>{s['unhealthy']}</b>"]
        for cur in sorted(set(s['gross_by_currency'])|set(s['by_currency'])):
            gross=s['gross_by_currency'].get(cur,0)/100; weighted=s['by_currency'].get(cur,0)/100
            lines.append(f"â€¢ {escape(cur)} Â· gross {gross:,.2f} Â· weighted {weighted:,.2f}")
        await message.reply_text("\n".join(lines),parse_mode=ParseMode.HTML)

    async def growing(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update):
            return
        await self._send_intelligence_list(
            update.effective_message,
            "ðŸ”¥ Growing relationships",
            "i.momentum_label IN ('growing','surging')",
            "i.momentum_score DESC, c.relationship_score DESC",
        )

    async def slipping(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update):
            return
        await self._send_intelligence_list(
            update.effective_message,
            "ðŸ“‰ Relationships to watch",
            "c.relationship_score>=40 AND i.health_score<55",
            "i.health_score ASC, c.relationship_score DESC",
        )

    async def _send_intelligence_list(self, message, title: str, where: str, order_by: str):
        rows = self.db.all(
            f"""SELECT c.*, i.health_score, i.momentum_label, i.momentum_score,
                       i.lifecycle_stage, i.days_overdue
                FROM contacts c JOIN contact_intelligence i ON i.telegram_id=c.telegram_id
                LEFT JOIN contact_controls cc ON cc.telegram_id=c.telegram_id
                WHERE ({where}) AND COALESCE(cc.archived,0)=0 AND COALESCE(cc.excluded,0)=0
                ORDER BY {order_by} LIMIT 25"""
        )
        if not rows:
            await message.reply_text(f"No {title.lower()} right now.")
            return
        lines = [f"<b>{escape(title)}</b>\n"]
        buttons = []
        for r in rows:
            lines.append(
                f"â€¢ {escape(contact_label(r))} Â· Health <b>{r['health_score']}/100</b> Â· "
                f"{escape(pretty(r['momentum_label']))} Â· R {r['relationship_score']}/100"
            )
            if len(buttons) < 10:
                buttons.append([
                    InlineKeyboardButton(
                        f"ðŸ‘¤ {contact_label(r)[:38]}", callback_data=f"open:{r['telegram_id']}"
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
            "SELECT COUNT(*) n FROM contacts c LEFT JOIN contact_controls cc ON cc.telegram_id=c.telegram_id WHERE c.typical_cycle_days IS NOT NULL AND COALESCE(cc.archived,0)=0 AND COALESCE(cc.excluded,0)=0"
        )["n"]
        healthy = self.db.one(
            "SELECT COUNT(*) n FROM contact_intelligence i LEFT JOIN contact_controls cc ON cc.telegram_id=i.telegram_id WHERE i.health_score>=75 AND COALESCE(cc.archived,0)=0 AND COALESCE(cc.excluded,0)=0"
        )["n"]
        watch = self.db.one(
            "SELECT COUNT(*) n FROM contact_intelligence i LEFT JOIN contact_controls cc ON cc.telegram_id=i.telegram_id WHERE i.health_score BETWEEN 50 AND 74 AND COALESCE(cc.archived,0)=0 AND COALESCE(cc.excluded,0)=0"
        )["n"]
        risk = self.db.one(
            "SELECT COUNT(*) n FROM contact_intelligence i LEFT JOIN contact_controls cc ON cc.telegram_id=i.telegram_id WHERE i.health_score<50 AND COALESCE(cc.archived,0)=0 AND COALESCE(cc.excluded,0)=0"
        )["n"]
        growing = self.db.one(
            "SELECT COUNT(*) n FROM contact_intelligence i LEFT JOIN contact_controls cc ON cc.telegram_id=i.telegram_id WHERE i.momentum_label IN ('growing','surging') AND COALESCE(cc.archived,0)=0 AND COALESCE(cc.excluded,0)=0"
        )["n"]
        declining = self.db.one(
            "SELECT COUNT(*) n FROM contact_intelligence i LEFT JOIN contact_controls cc ON cc.telegram_id=i.telegram_id WHERE i.momentum_label IN ('cooling','fading') AND COALESCE(cc.archived,0)=0 AND COALESCE(cc.excluded,0)=0"
        )["n"]
        overdue = self.db.one(
            "SELECT COUNT(*) n FROM contact_intelligence i LEFT JOIN contact_controls cc ON cc.telegram_id=i.telegram_id WHERE i.days_overdue>0 AND COALESCE(cc.archived,0)=0 AND COALESCE(cc.excluded,0)=0"
        )["n"]
        unclassified = self.db.one(
            """SELECT COUNT(*) n FROM contacts c LEFT JOIN contact_controls cc ON cc.telegram_id=c.telegram_id
               WHERE c.relationship_type='unknown' AND c.interaction_count>=3
                 AND COALESCE(cc.archived,0)=0 AND COALESCE(cc.excluded,0)=0"""
        )["n"]

        top_growing = self.db.all(
            """SELECT c.telegram_id, c.display_name, c.username, i.health_score, i.momentum_score
               FROM contacts c JOIN contact_intelligence i ON i.telegram_id=c.telegram_id
               LEFT JOIN contact_controls cc ON cc.telegram_id=c.telegram_id
               WHERE i.momentum_label IN ('growing','surging')
                 AND COALESCE(cc.archived,0)=0 AND COALESCE(cc.excluded,0)=0
               ORDER BY i.momentum_score DESC, c.relationship_score DESC LIMIT 3"""
        )
        at_risk = self.db.all(
            """SELECT c.telegram_id, c.display_name, c.username, c.relationship_score, i.health_score
               FROM contacts c JOIN contact_intelligence i ON i.telegram_id=c.telegram_id
               LEFT JOIN contact_controls cc ON cc.telegram_id=c.telegram_id
               WHERE c.relationship_score>=40 AND i.health_score<55
                 AND COALESCE(cc.archived,0)=0 AND COALESCE(cc.excluded,0)=0
               ORDER BY i.health_score ASC, c.relationship_score DESC LIMIT 3"""
        )

        lines = [
            "<b>ðŸ“Š RELATIONSHIP INTELLIGENCE</b>\n",
            f"â¤ï¸ Healthy (75+): <b>{healthy}</b>",
            f"ðŸ‘€ Watch (50â€“74): <b>{watch}</b>",
            f"âš ï¸ Low health (&lt;50): <b>{risk}</b>",
            f"ðŸ”¥ Growing: <b>{growing}</b>",
            f"ðŸ“‰ Cooling/Fading: <b>{declining}</b>",
            f"â± Learned cycles: <b>{learned}</b>",
            f"âŒ› Outside learned cycle: <b>{overdue}</b>",
            f"ðŸ· Active but unclassified: <b>{unclassified}</b>",
        ]
        if top_growing:
            lines.append("\n<b>Fastest growing</b>")
            for r in top_growing:
                lines.append(
                    f"â€¢ {escape(contact_label(r))} Â· momentum +{r['momentum_score']} Â· health {r['health_score']}"
                )
        if at_risk:
            lines.append("\n<b>Highest-value relationships to watch</b>")
            for r in at_risk:
                lines.append(
                    f"â€¢ {escape(contact_label(r))} Â· health {r['health_score']} Â· relationship {r['relationship_score']}"
                )

        await message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

    async def version(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update):
            return
        version_path = __import__('pathlib').Path(__file__).resolve().parent / 'VERSION.txt'
        version_text = version_path.read_text(encoding='utf-8').strip() if version_path.exists() else 'VM Relationship Manager v6.0.0'
        await update.effective_message.reply_text(f"<b>ðŸ¤ VM Relationship Manager</b>\n<pre>{escape(version_text)}</pre>", parse_mode=ParseMode.HTML)

    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update):
            return
        text = (
            "<b>ðŸ¤ VM Relationship Manager 6.0</b>\n\n"
            "<b>Daily control</b>\n"
            "/rm dashboard Â· /brief executive brief Â· /exceptions exception-only inbox Â· /today ranked priorities Â· /priority ID\n\n"
            "<b>Autonomy & classification</b>\n"
            "/autonomy [observe|assist|safe] Â· /classify [ID] Â· /calibration Â· /policy Â· /actions [ID] Â· /actiondismiss ID Â· /maintain\n\n"
            "<b>Execution & goals</b>\n"
            "/goals [ID] Â· /goal ID PRIORITY 7d title Â· /goalupdate GOAL_ID PERCENT Â· /goalcomplete GOAL_ID Â· /playbook ID\n\n"
            "<b>Intelligence</b>\n"
            "/outlook ID Â· /sessions ID Â· /quality ID Â· /segments Â· /segment KEY Â· /behavior ID Â· /network ID\n\n"
            "<b>Contacts & memory</b>\n"
            "/person @username Â· /find filters Â· /remember Â· /memories Â· /lists Â· /views\n\n"
            "<b>CRM & opportunities</b>\n"
            "/followup Â· /followups Â· /deal Â· /deals Â· /pipeline Â· /forecast\n\n"
            "<b>Trust, reports & operations</b>\n"
            "/risks Â· /report weekly|monthly Â· /backup Â· /backups Â· /ops Â· /doctor Â· /diagnostics\n\n"
            "<b>Privacy & integration</b>\n"
            "/privacy Â· /archive Â· /exclude Â· /rescan Â· /export Â· /integrations\n\n"
            "Search examples: <code>/find segment:commercial risk&gt;60</code>, <code>/find lowconfidence score&gt;50</code>, or <code>/find goaldue</code>, <code>/find quarantined</code>, <code>/find actionsuppressed</code>."
        )
        await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)

    async def brief(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update):
            return
        # Refresh the lightweight decision layers that make the brief useful.
        self.engine.calibration.refresh()
        self.engine.classification.compute_all(auto_apply=True)
        self.engine.priority.refresh_all()
        self.engine.actions.compute_all()
        brief = self.engine.briefing.build()
        lines = [
            "<b>ðŸ§­ VM EXECUTIVE RELATIONSHIP BRIEF</b>",
            f"ðŸ”¥ Growing relationships: <b>{brief['growing_relationships']}</b>",
            f"ðŸ”­ High disengagement risk: <b>{brief['high_disengagement_risk']}</b>",
            f"ðŸŽ¯ Overdue goals: <b>{len(brief['overdue_goals'])}</b>",
            f"ðŸ’¼ Unhealthy opportunities: <b>{brief['unhealthy_opportunities']}</b>",
            f"ðŸ›¡ Pending risk reviews: <b>{brief['pending_risks']}</b>",
            f"ðŸ¤– Auto-classified: <b>{brief.get('auto_classified',0)}</b> Â· Unknown remaining: <b>{brief.get('unknown_contacts',0)}</b>",
            f"ðŸš¨ Eligible exception actions: <b>{brief.get('exception_actions',0)}</b> Â· policy-selected: <b>{brief.get('policy_selected_exceptions',0)}</b>",
            f"ðŸ§¹ Routine exceptions budget-suppressed: <b>{brief.get('policy_suppressed_exceptions',0)}</b>",
            "",
            "<b>Top exception actions</b>",
        ]
        buttons = []
        for r in brief.get('top_exception_actions', []):
            who = r['display_name'] or r['username'] or str(r['telegram_id'])
            lines.append(f"â€¢ <b>{escape(str(who))}</b> Â· {r['action_score']}/100 â€” {escape(r['title'] or 'Review relationship')}")
            buttons.append([InlineKeyboardButton(str(who)[:38], callback_data=f"open:{r['telegram_id']}")])
        if not brief.get('top_exception_actions'):
            lines.append("â€¢ No policy-selected exception action is currently urgent.")
        if brief['overdue_goals']:
            lines.append("\n<b>Overdue goals</b>")
            for g in brief['overdue_goals'][:5]:
                who = g['display_name'] or g['username'] or str(g['telegram_id'])
                lines.append(f"â€¢ #{g['id']} {escape(str(who))}: {escape(g['title'])} Â· {g['progress_pct']}%")
        await update.effective_message.reply_text(
            "\n".join(lines), parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(buttons[:10]) if buttons else None,
        )

    async def goals(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update):
            return
        tid = None
        if context.args:
            try:
                tid = int(context.args[0])
            except ValueError:
                await update.effective_message.reply_text("Usage: /goals [TELEGRAM_ID]")
                return
        rows = self.engine.goals.list(tid, 'active', 30)
        title = "ðŸŽ¯ Active relationship goals" if tid is None else f"ðŸŽ¯ Goals for {tid}"
        lines = [f"<b>{title}</b>"]
        buttons = []
        for g in rows:
            who = (g['display_name'] or g['username'] or str(g['telegram_id'])) if tid is None else ''
            due = self._local_time(g['target_at']) if g['target_at'] else 'No due date'
            prefix = f"{escape(str(who))} Â· " if who else ''
            lines.append(f"â€¢ #{g['id']} {prefix}{escape(g['title'])} Â· {g['progress_pct']}% Â· P{g['priority']} Â· {escape(due)}")
            buttons.append([
                InlineKeyboardButton(f"âœ… Complete #{g['id']}", callback_data=f"goalcomplete:{g['id']}"),
                InlineKeyboardButton("ðŸ‘¤ Contact", callback_data=f"open:{g['telegram_id']}"),
            ])
        if not rows:
            lines.append("No active goals.")
        lines.append("\nCreate: <code>/goal TELEGRAM_ID PRIORITY DUE title</code> â€” e.g. <code>/goal 123 80 7d Confirm wholesale terms</code>")
        await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(buttons[:12]) if buttons else None)

    async def goal_create(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update):
            return
        if len(context.args) < 4:
            await update.effective_message.reply_text("Usage: /goal TELEGRAM_ID PRIORITY 7d|24h|none goal title")
            return
        try:
            tid = int(context.args[0]); priority = int(context.args[1])
        except ValueError:
            await update.effective_message.reply_text("Telegram ID and priority must be numeric.")
            return
        due_token = context.args[2].lower()
        target_at = None
        if due_token not in {'none','-','nodue'}:
            delta = self._parse_delta(due_token)
            if not delta:
                await update.effective_message.reply_text("Due time must look like 7d, 24h, 30m, or none.")
                return
            target_at = (datetime.now(timezone.utc) + delta).isoformat()
        title = " ".join(context.args[3:])
        try:
            row = self.engine.goals.create(tid, title, update.effective_user.id, priority=priority, target_at=target_at)
            self.engine.event(tid, 'goal_created', f"#{row['id']} {row['title']}")
            self.engine.automation.process_goal_due()
            self.engine.priority.compute(tid)
            await update.effective_message.reply_text(f"ðŸŽ¯ Goal #{row['id']} created.")
        except ValueError as exc:
            await update.effective_message.reply_text(str(exc))

    async def goal_update(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update):
            return
        if len(context.args) < 2:
            await update.effective_message.reply_text("Usage: /goalupdate GOAL_ID PERCENT [next step]")
            return
        try:
            gid = int(context.args[0]); pct = int(context.args[1])
            next_step = " ".join(context.args[2:]) if len(context.args) > 2 else None
            row = self.engine.goals.update(gid, progress_pct=pct, next_step=next_step)
            self.engine.event(row['telegram_id'], 'goal_updated', f"#{gid} progress {row['progress_pct']}%")
            self.engine.priority.compute(row['telegram_id'])
            await update.effective_message.reply_text(f"ðŸŽ¯ Goal #{gid} updated to {row['progress_pct']}%.")
        except (ValueError, TypeError) as exc:
            await update.effective_message.reply_text(str(exc))

    async def goal_complete(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update):
            return
        if not context.args:
            await update.effective_message.reply_text("Usage: /goalcomplete GOAL_ID")
            return
        try:
            row = self.engine.goals.complete(int(context.args[0]))
            if not row:
                raise ValueError("Goal not found.")
            self.engine.event(row['telegram_id'], 'goal_completed', f"#{row['id']} {row['title']}")
            self.engine.automation.process_goal_due(); self.engine.priority.compute(row['telegram_id'])
            await update.effective_message.reply_text(f"âœ… Goal #{row['id']} completed.")
        except ValueError as exc:
            await update.effective_message.reply_text(str(exc))

    async def segments(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update):
            return
        self.engine.segments.compute_all()
        rows = self.engine.segments.overview()
        lines = ["<b>ðŸ§© Dynamic CRM Segments</b>"]
        buttons = []
        for r in rows:
            lines.append(f"â€¢ <code>{escape(r['segment_key'])}</code>: <b>{r['contacts']}</b> Â· confidence {r['avg_confidence']}")
            buttons.append([InlineKeyboardButton(f"{pretty(r['segment_key'])} ({r['contacts']})", callback_data=f"segment:{r['segment_key']}")])
        if not rows:
            lines.append("Segments are still learning.")
        await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(buttons[:15]) if buttons else None)

    async def segment(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update): return
        if not context.args:
            await update.effective_message.reply_text("Usage: /segment SEGMENT_KEY")
            return
        await self._send_segment(update.effective_message, context.args[0])

    async def _send_segment(self, message, key: str):
        rows = self.engine.segments.members(key, 25)
        lines = [f"<b>ðŸ§© Segment: {escape(pretty(key))}</b>"]
        buttons = []
        for r in rows:
            who = r['display_name'] or r['username'] or str(r['telegram_id'])
            lines.append(f"â€¢ {escape(str(who))} Â· confidence {r['confidence']} Â· score {r['relationship_score']} Â· health {r['health_score'] if r['health_score'] is not None else '?'}")
            buttons.append([InlineKeyboardButton(str(who)[:38], callback_data=f"open:{r['telegram_id']}")])
        if not rows: lines.append("No contacts currently match this segment.")
        await message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(buttons[:15]) if buttons else None)

    async def outlook(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update): return
        if not context.args:
            await update.effective_message.reply_text("Usage: /outlook TELEGRAM_ID")
            return
        await self._send_outlook(update.effective_message, int(context.args[0]))

    async def _send_outlook(self, message, tid: int):
        self.engine.sessions.compute(tid); self.engine.quality.compute(tid)
        row = self.engine.forecast.compute(tid)
        c = self.db.one("SELECT * FROM contacts WHERE telegram_id=?", (tid,))
        if not row or not c:
            await message.reply_text("No outlook data available."); return
        lines = [
            f"<b>ðŸ”­ Outlook â€” {escape(contact_label(c))}</b>",
            f"Risk of disengagement: <b>{row['disengagement_risk']}/100</b>",
            f"Re-engagement priority: <b>{row['reengagement_priority']}/100</b>",
            f"Outlook: <b>{escape(pretty(row['outlook_label']))}</b>",
            f"Evidence confidence: <b>{row['confidence']}/100</b>",
            "",
            "<b>Why</b>",
        ]
        reasons = self.engine.forecast.reasons(tid)
        for r in reasons[:8]:
            sign = '+' if int(r['points']) >= 0 else ''
            lines.append(f"â€¢ {sign}{r['points']} â€” {escape(r['text'])}")
        if not reasons: lines.append("â€¢ Not enough history for a strong outlook yet.")
        lines.append("\n<i>This is a conservative metadata-based outlook, not a claim about the person's intentions.</i>")
        await message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

    async def sessions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update): return
        if not context.args:
            await update.effective_message.reply_text("Usage: /sessions TELEGRAM_ID")
            return
        await self._send_sessions(update.effective_message, int(context.args[0]))

    async def _send_sessions(self, message, tid: int):
        c = self.db.one("SELECT * FROM contacts WHERE telegram_id=?", (tid,))
        row = self.engine.sessions.compute(tid)
        if not c or not row:
            await message.reply_text("No session data available."); return
        recent = self.engine.sessions.recent_sessions(tid, 30, 5)
        lines = [
            f"<b>ðŸ’¬ Conversation Sessions â€” {escape(contact_label(c))}</b>",
            f"Sessions (30d): <b>{row['sessions_30']}</b>",
            f"Avg messages/session: <b>{row['avg_messages_per_session']}</b>",
            f"Median duration: <b>{round(int(row['median_duration_seconds'] or 0)/60,1)} min</b>",
            f"They started: {row['incoming_started_30']} Â· You started: {row['outgoing_started_30']}",
            f"Initiation balance: <b>{row['initiation_balance_score']}/100</b>",
            f"Pattern: <b>{escape(pretty(row['session_label']))}</b>",
        ]
        if recent:
            lines.append("\n<b>Recent sessions</b>")
            for s in recent:
                lines.append(f"â€¢ {s['start'].astimezone(self.settings.timezone).strftime('%d %b %I:%M %p')} Â· {s['messages']} msgs Â· {round(s['duration_seconds']/60,1)} min Â· started by {escape(s['initiator'])}")
        await message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

    async def quality(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update): return
        if not context.args:
            await update.effective_message.reply_text("Usage: /quality TELEGRAM_ID")
            return
        tid = int(context.args[0]); c = self.db.one("SELECT * FROM contacts WHERE telegram_id=?", (tid,))
        row = self.engine.quality.compute(tid)
        if not c or not row:
            await update.effective_message.reply_text("No data-quality information available."); return
        missing = json.loads(row['missing_fields_json'] or '[]')
        await update.effective_message.reply_text(
            f"<b>ðŸ§ª Data Quality â€” {escape(contact_label(c))}</b>\n"
            f"Completeness: <b>{row['completeness_score']}/100</b>\n"
            f"Intelligence confidence: <b>{row['confidence_score']}/100</b>\n"
            f"Still learning: {escape(', '.join(pretty(x) for x in missing) if missing else 'Nothing obvious')}\n\n"
            "<i>Confidence measures evidence depth, not whether the person is trustworthy.</i>",
            parse_mode=ParseMode.HTML,
        )

    async def playbook(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update): return
        if not context.args:
            await update.effective_message.reply_text("Usage: /playbook TELEGRAM_ID")
            return
        await self._send_playbook(update.effective_message, int(context.args[0]))

    async def _send_playbook(self, message, tid: int):
        c = self.db.one("SELECT * FROM contacts WHERE telegram_id=?", (tid,))
        pb = self.engine.playbooks.recommend(tid)
        if not c or not pb:
            await message.reply_text("No playbook recommendation available."); return
        lines = [f"<b>ðŸ§­ Suggested Playbook â€” {escape(contact_label(c))}</b>", f"<b>{escape(pretty(pb['name']))}</b>"]
        for n, step in enumerate(pb['steps'], 1):
            lines.append(f"{n}. {escape(step)}")
        lines.append("\n<i>Playbooks recommend admin actions only; they never message contacts automatically.</i>")
        await message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


    async def autonomy(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update):
            return
        if context.args:
            try:
                self.engine.autonomy.set_mode(context.args[0], update.effective_user.id)
            except ValueError as exc:
                await update.effective_message.reply_text(str(exc))
                return
        cfg = self.engine.autonomy.settings()
        stats = self.engine.classification.stats()
        action_stats = self.engine.actions.stats()
        text = (
            "<b>ðŸ¤– VM AUTONOMY</b>\n"
            f"Mode: <b>{escape(cfg['mode'].upper())}</b>\n"
            f"Auto-classification threshold: <b>{cfg['classification_auto_threshold']}%</b>\n"
            f"Exception threshold: <b>{cfg['exception_threshold']}/100</b>\n"
            f"Daily exception limit: <b>{cfg['daily_exception_limit']}</b>\n"
            f"Suppress clear digests: <b>{'Yes' if cfg['suppress_clear_digests'] else 'No'}</b>\n\n"
            f"Unknown contacts: <b>{stats['unknown']}</b> Â· classifier suggestions: <b>{stats['suggested']}</b>\n"
            f"Auto-applied classifications: <b>{stats['auto_applied']}</b> Â· locked: <b>{stats['locked']}</b>\n"
            f"Current exception actions: <b>{action_stats['exceptions']}</b>\n\n"
            "<i>SAFE mode only performs reversible metadata maintenance and high-confidence safe classification. "
            "It never messages contacts automatically.</i>\n\n"
            "Change mode: <code>/autonomy observe</code>, <code>/autonomy assist</code>, or <code>/autonomy safe</code>."
        )
        await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)

    async def classify(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update):
            return
        if context.args:
            try:
                tid = int(context.args[0])
            except ValueError:
                rows = self._find_contacts(context.args[0], 1)
                if not rows:
                    await update.effective_message.reply_text("Contact not found.")
                    return
                tid = rows[0]["telegram_id"]
            await self._send_classification(update.effective_message, tid)
            return
        result = self.engine.classification.compute_all(auto_apply=True)
        self.engine.priority.refresh_all()
        self.engine.actions.compute_all()
        stats = self.engine.classification.stats()
        rows = self.engine.classification.backlog(10)
        lines = [
            "<b>ðŸ§  AUTOMATIC CONTACT CLASSIFICATION</b>",
            f"Computed: <b>{result['computed']}</b> Â· newly auto-applied this pass: <b>{result['newly_applied']}</b>",
            f"Unknown remaining: <b>{stats['unknown']}</b> Â· review suggestions: <b>{stats['suggested']}</b>",
            f"Manual locks: <b>{stats['locked']}</b> Â· average non-abstain confidence: <b>{stats['avg_confidence']:.1f}%</b>",
        ]
        buttons = []
        if rows:
            lines.append("\n<b>Highest-confidence review suggestions</b>")
            for row in rows:
                who = row['display_name'] or row['username'] or str(row['telegram_id'])
                lines.append(f"â€¢ {escape(str(who))} â†’ <b>{escape(pretty(row['predicted_type']))}</b> Â· {row['confidence']}%")
                buttons.append([InlineKeyboardButton(str(who)[:34], callback_data=f"open:{row['telegram_id']}"),
                                InlineKeyboardButton("Review", callback_data=f"classification:{row['telegram_id']}")])
        else:
            lines.append("\nNo classifier review backlog currently needs admin attention.")
        await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(buttons[:10]) if buttons else None)

    async def _send_classification(self, message, tid: int):
        row = self.engine.classification.compute(tid, auto_apply=True)
        c = self.db.one("SELECT * FROM contacts WHERE telegram_id=?", (tid,))
        if not row or not c:
            await message.reply_text("Classification data unavailable.")
            return
        try:
            evidence = json.loads(row['evidence_json'] or '[]')
        except Exception:
            evidence = []
        lines = [
            f"<b>ðŸ§  Classification Â· {escape(contact_label(c))}</b>",
            f"Current type: <b>{escape(pretty(c['relationship_type']))}</b>",
            f"Prediction: <b>{escape(pretty(row['predicted_type']))}</b> Â· confidence <b>{row['confidence']}%</b>",
            f"Decision: <b>{escape(pretty(row['decision_state']))}</b> Â· manual lock: <b>{'Yes' if row['admin_locked'] else 'No'}</b>",
        ]
        if evidence:
            lines.append("\n<b>Evidence</b>")
            for e in evidence[:7]:
                lines.append(f"â€¢ {escape(e.get('text',''))} â†’ {escape(pretty(e.get('type')))} ({e.get('points',0)}%)")
        else:
            lines.append("\nThe classifier abstained because there is not enough reliable structured evidence yet.")
        kb = []
        if row['predicted_type'] != 'unknown' and not row['admin_locked']:
            kb.append([InlineKeyboardButton(f"âœ… Apply {pretty(row['predicted_type'])}", callback_data=f"classapply:{tid}")])
        if row['admin_locked']:
            kb.append([InlineKeyboardButton("ðŸ”“ Allow classifier suggestions", callback_data=f"classunlock:{tid}")])
        else:
            kb.append([InlineKeyboardButton("ðŸ”’ Lock current type", callback_data=f"classlock:{tid}")])
        await message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML,
                                 reply_markup=InlineKeyboardMarkup(kb) if kb else None)

    async def exceptions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update):
            return
        await self._send_exceptions(update.effective_message)

    async def _send_exceptions(self, message):
        self.engine.classification.compute_all(auto_apply=True)
        self.engine.priority.refresh_all()
        self.engine.actions.compute_all()
        cfg = self.engine.autonomy.settings()
        rows = self.engine.exception_policy.select(cfg['daily_exception_limit'], cfg['exception_threshold'])
        policy_summary = self.engine.exception_policy.summary()
        if not rows:
            await message.reply_text("âœ… Exception inbox is clear â€” routine relationship maintenance can stay passive.")
            return
        lines = ["<b>ðŸš¨ VM EXCEPTION INBOX</b>",
                 f"Policy-selected {len(rows)} of {policy_summary['eligible']} eligible exception(s); critical work bypasses the normal budget.\n"]
        buttons = []
        for n, r in enumerate(rows, 1):
            who = r['display_name'] or r['username'] or str(r['telegram_id'])
            lines.append(
                f"<b>{n}. {escape(str(who))}</b> Â· {r['action_score']}/100 Â· confidence {r['confidence']}%\n"
                f"   {escape(r['title'])} â€” {escape((r['reason'] or '')[:170])}"
            )
            buttons.append([
                InlineKeyboardButton(f"ðŸ‘¤ {str(who)[:20]}", callback_data=f"open:{r['telegram_id']}"),
                InlineKeyboardButton("âœ… Done", callback_data=f"actiondone:{r['id']}"),
                InlineKeyboardButton("ðŸš« Dismiss", callback_data=f"actiondismiss:{r['id']}"),
                InlineKeyboardButton("ðŸ˜´ 7d", callback_data=f"actionsnooze:{r['id']}:7"),
            ])
        await message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML,
                                 reply_markup=InlineKeyboardMarkup(buttons[:12]))

    async def actions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update):
            return
        if not context.args:
            await self._send_exceptions(update.effective_message)
            return
        try:
            tid = int(context.args[0])
        except ValueError:
            rows = self._find_contacts(context.args[0], 1)
            if not rows:
                await update.effective_message.reply_text("Contact not found.")
                return
            tid = rows[0]['telegram_id']
        c = self.db.one("SELECT * FROM contacts WHERE telegram_id=?", (tid,))
        rows = self.engine.actions.for_contact(tid)
        if not c:
            await update.effective_message.reply_text("Contact not found.")
            return
        lines = [f"<b>ðŸ§­ Recommended Actions Â· {escape(contact_label(c))}</b>"]
        buttons = []
        for r in rows:
            lines.append(f"â€¢ #{r['id']} <b>{escape(r['title'])}</b> Â· {r['action_score']}/100 Â· {r['confidence']}%\n  {escape((r['reason'] or '')[:180])}")
            buttons.append([InlineKeyboardButton(f"âœ… Done #{r['id']}", callback_data=f"actiondone:{r['id']}"),
                            InlineKeyboardButton("ðŸš« Dismiss", callback_data=f"actiondismiss:{r['id']}"),
                            InlineKeyboardButton("ðŸ˜´ 7d", callback_data=f"actionsnooze:{r['id']}:7")])
        if not rows:
            lines.append("No open recommended admin actions for this contact.")
        await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(buttons[:10]) if buttons else None)

    async def actiondone(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update):
            return
        if not context.args:
            await update.effective_message.reply_text("Usage: /actiondone ACTION_ID")
            return
        try:
            action_id = int(context.args[0])
        except ValueError:
            await update.effective_message.reply_text("Action ID must be numeric.")
            return
        ok = self.engine.actions.resolve(action_id, 'done')
        await update.effective_message.reply_text("âœ… Action completed." if ok else "Action not found.")

    async def actionsnooze(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update):
            return
        if not context.args:
            await update.effective_message.reply_text("Usage: /actionsnooze ACTION_ID [DAYS]")
            return
        try:
            action_id = int(context.args[0]); days = int(context.args[1]) if len(context.args) > 1 else 7
        except ValueError:
            await update.effective_message.reply_text("Action ID and days must be numeric.")
            return
        ok = self.engine.actions.snooze(action_id, days)
        await update.effective_message.reply_text(f"ðŸ˜´ Action snoozed for {days} day(s)." if ok else "Action not found.")

    async def actiondismiss(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update):
            return
        if not context.args:
            await update.effective_message.reply_text("Usage: /actiondismiss ACTION_ID")
            return
        try:
            action_id = int(context.args[0])
        except ValueError:
            await update.effective_message.reply_text("Action ID must be numeric.")
            return
        ok = self.engine.actions.resolve(action_id, 'dismissed')
        days = self.engine.exception_policy.settings()['dismissal_cooldown_days']
        await update.effective_message.reply_text(
            f"ðŸš« Action dismissed and suppressed for {days} day(s)." if ok else "Action not found."
        )

    async def calibration(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update):
            return
        rows = self.engine.calibration.refresh()
        summary = self.engine.calibration.summary()
        lines = [
            "<b>ðŸ§ª CLASSIFIER CALIBRATION</b>",
            f"Admin feedback samples: <b>{summary['feedback_samples']}</b> Â· quarantined types: <b>{summary['quarantined']}</b>",
            "<i>Calibration never lowers the global safety threshold; disagreement can only raise it or quarantine auto-apply.</i>",
            "",
        ]
        for row in rows:
            precision = "learning" if row['precision'] is None else f"{round(row['precision']*100)}%"
            state = "AUTO" if row['auto_enabled'] else "QUARANTINED"
            lines.append(f"â€¢ <b>{escape(pretty(row['relationship_type']))}</b> Â· {state} Â· threshold {row['effective_threshold']}% Â· precision {precision} Â· n={row['sample_count']}")
        await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

    async def policy(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update):
            return
        p = self.engine.exception_policy.summary()
        lines = [
            "<b>ðŸŽ› EXCEPTION POLICY</b>",
            f"Normal threshold: <b>{p['threshold']}/100</b> Â· critical bypass: <b>{p['critical_threshold']}/100</b>",
            f"Daily normal-work budget: <b>{p['limit']}</b> Â· per-contact cap: <b>{p['per_contact_limit']}</b>",
            f"Dismissal cooldown: <b>{p['dismissal_cooldown_days']}d</b> Â· done cooldown: <b>{p['done_cooldown_days']}d</b>",
            f"Eligible now: <b>{p['eligible']}</b> Â· critical: <b>{p['critical']}</b> Â· selected: <b>{p['selected']}</b>",
            f"Budget-suppressed routine items: <b>{p['budget_suppressed']}</b>",
            "",
            "<i>Critical work is never hidden by the normal daily budget.</i>",
        ]
        await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

    async def ops(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update):
            return
        snapshot = self.engine.operations.capture(run_integrity=False)
        lines = [
            f"<b>ðŸ“¡ VM OPERATIONS â€” {escape(snapshot['status'].upper())}</b>",
            f"Operational health: <b>{snapshot['health_score']}/100</b>",
        ]
        for name, detail in snapshot['components'].items():
            extra = ', '.join(f"{k}={v}" for k,v in detail.items() if k != 'status' and v is not None)
            lines.append(f"â€¢ {escape(name)}: <b>{escape(str(detail.get('status','unknown')).upper())}</b>" + (f" Â· {escape(extra)}" if extra else ""))
        await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

    async def maintain(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update):
            return
        result = self.maintenance.run_safe(allow_backup=True)
        calibration = self.engine.calibration.refresh()
        classifications = self.engine.classification.compute_all(auto_apply=True)
        self.engine.priority.refresh_all()
        actions = self.engine.actions.compute_all()
        policy = self.engine.exception_policy.summary()
        self.engine.integration.export_all()
        ops = self.engine.operations.capture(run_integrity=False)
        lines = [
            f"<b>âš™ï¸ SAFE MAINTENANCE â€” {escape(result['status'].upper())}</b>",
            f"Findings before: <b>{len(result['before'])}</b> Â· remaining: <b>{len(result['after'])}</b>",
            f"Maintenance actions: <b>{len(result['actions'])}</b>",
            f"Classifier: {classifications['computed']} checked Â· {classifications['newly_applied']} newly auto-applied Â· {len(calibration)} calibration policies",
            f"Relationship action signals: {actions['active_signals']} Â· policy-selected: {policy['selected']}",
            f"Operational health: {ops['health_score']}/100 Â· {ops['status'].upper()}",
        ]
        for a in result['actions'][:6]:
            lines.append(f"â€¢ {escape(a['action'])}: {escape(str(a['status']))}")
        if result['after']:
            lines.append("\n<b>Remaining exceptions</b>")
            for f in result['after'][:6]:
                lines.append(f"â€¢ {escape(f['severity'].upper())} Â· {escape(f['code'])}: {escape(f['detail'])}")
        else:
            lines.append("\nNo operational exception remains after safe maintenance.")
        await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

    async def doctor(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update): return
        integrity = self.db.integrity_check()
        schema = self.db.meta('schema_version','unknown')
        heartbeat = self.db.meta('last_heartbeat')
        backup = self.db.one("SELECT * FROM backup_audit ORDER BY id DESC LIMIT 1")
        backlog = self.engine.integration.backlog()
        warnings = []
        if integrity != ['ok']: warnings.append('SQLite integrity is not OK')
        if schema != '6.0.0': warnings.append(f'Schema is {schema}, expected 6.0.0')
        if heartbeat:
            try:
                age = (datetime.now(timezone.utc)-datetime.fromisoformat(heartbeat)).total_seconds()
                if age > 900: warnings.append(f'Heartbeat is stale ({round(age/60)} min)')
            except Exception: warnings.append('Heartbeat timestamp could not be parsed')
        else: warnings.append('No process heartbeat recorded yet')
        backup_check = self.backups.verify_record(backup) if backup else {"status": "missing", "reason": "no backup audit entry"}
        if not backup:
            warnings.append('No backup audit exists yet')
        elif backup_check['status'] != 'verified':
            warnings.append(f"Latest backup verification failed: {backup_check.get('reason','unknown reason')}")
        if int(backlog['retrying'] or 0) > 0: warnings.append(f"{backlog['retrying']} integration event(s) retrying")
        ops = self.engine.operations.capture(run_integrity=False)
        if ops['status'] == 'critical': warnings.append(f"Operational SLO is critical ({ops['health_score']}/100)")
        status = 'PASS' if not warnings else 'WARN'
        lines = [
            f"<b>ðŸ©º VM Doctor â€” {status}</b>",
            f"Schema: <b>{escape(schema)}</b>",
            f"SQLite: <b>{'OK' if integrity == ['ok'] else 'ERROR'}</b>",
            f"Integration backlog: {backlog['total'] or 0} Â· retrying {backlog['retrying'] or 0}",
            f"Latest backup: {escape(backup['created_at']) if backup else 'None yet'}",
            f"Backup verification: <b>{escape(backup_check['status'].upper())}</b>",
            f"Monitor account ID recorded: {'Yes' if self.db.meta('monitor_self_user_id') else 'No'}",
            f"Autonomy mode: <b>{escape(self.engine.autonomy.mode().upper())}</b>",
            f"Unknown contacts: {self.engine.classification.stats()['unknown']} Â· exception actions: {self.engine.actions.stats()['exceptions']}",
            f"Operational health: <b>{ops['health_score']}/100</b> Â· policy-selected exceptions: {self.engine.exception_policy.summary()['selected']}",
        ]
        if warnings:
            lines.append("\n<b>Warnings</b>")
            lines.extend(f"â€¢ {escape(w)}" for w in warnings)
        else:
            lines.append("\nNo operational warning detected from the local Relationship Manager state.")
        await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

    async def diagnostics(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update):
            return
        integrity = self.db.integrity_check()
        summary = self.engine.privacy.summary()
        backlog = self.engine.integration.backlog()
        pending = backlog['total'] or 0
        behavior = self.db.one("SELECT COUNT(*) n FROM behavior_metrics")["n"]
        network = self.db.one("SELECT COUNT(*) n FROM network_metrics")["n"]
        intel = self.db.one("SELECT COUNT(*) n FROM contact_intelligence")["n"]
        opp_summary = self.engine.opportunities.summary()
        opp = opp_summary["open"]
        priorities = self.db.one("SELECT COUNT(*) n FROM contact_priorities")["n"]
        groups = self.db.one("SELECT COUNT(*) n FROM group_metrics")["n"]
        risks = self.db.one("SELECT COUNT(*) n FROM risk_flags WHERE review_status='pending'")["n"]
        goals = self.db.one("SELECT COUNT(*) n FROM relationship_goals WHERE status='active'")["n"] if self.db.table_exists('relationship_goals') else 0
        forecasts = self.db.one("SELECT COUNT(*) n FROM contact_forecasts")["n"] if self.db.table_exists('contact_forecasts') else 0
        segments = self.db.one("SELECT COUNT(DISTINCT segment_key) n FROM contact_segments")["n"] if self.db.table_exists('contact_segments') else 0
        sessions = self.db.one("SELECT COUNT(*) n FROM conversation_session_metrics")["n"] if self.db.table_exists('conversation_session_metrics') else 0
        quality = self.db.one("SELECT ROUND(AVG(confidence_score),1) n FROM data_quality_metrics")["n"] if self.db.table_exists('data_quality_metrics') else 0
        heartbeat = self.db.meta('last_heartbeat','never')
        class_stats = self.engine.classification.stats()
        action_stats = self.engine.actions.stats()
        autonomy = self.engine.autonomy.settings()
        latest = self.db.all("SELECT component,status,created_at FROM bot_health ORDER BY id DESC LIMIT 8")
        lines = [
            "<b>ðŸ©º VM Relationship Manager Diagnostics</b>",
            f"Schema: <b>{escape(self.db.meta('schema_version','unknown'))}</b>",
            f"SQLite integrity: <b>{'OK' if integrity == ['ok'] else escape(', '.join(integrity[:3]))}</b>",
            f"Contacts: {summary['contacts']} Â· behavior: {behavior} Â· network: {network} Â· intelligence: {intel} Â· priority: {priorities}",
            f"Group profiles: {groups} Â· pending risk reviews: {risks}",
            f"Core intelligence: goals {goals} Â· forecasts {forecasts} Â· segments {segments} Â· sessions {sessions} Â· avg confidence {quality or 0}",
            f"v6 autonomy: {autonomy['mode']} Â· unknown {class_stats['unknown']} Â· classifier suggestions {class_stats['suggested']} Â· exception actions {action_stats['exceptions']} Â· policy-selected {self.engine.exception_policy.summary()['selected']}",
            f"Archived: {summary['archived']} Â· excluded: {summary['excluded']} Â· open opportunities: {opp}",
            f"Integration backlog: {pending} Â· retrying: {backlog['retrying'] or 0} Â· max attempts: {backlog['max_attempts'] or 0}",
            f"Last process heartbeat: {escape(str(heartbeat))}",
            "",
            "<b>Recent components</b>",
        ]
        for r in latest:
            lines.append(f"â€¢ {escape(r['component'])}: {escape(r['status'])}")
        await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

    async def find(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update):
            return
        if not context.args:
            await update.effective_message.reply_text(
                "Usage: /find type:supplier inactive>14  |  health<50 score>60  |  momentum:growing"
            )
            return
        await self._send_query_results(update.effective_message, " ".join(context.args))

    async def saveview(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update):
            return
        if len(context.args) < 2:
            await update.effective_message.reply_text("Usage: /saveview NAME query filters")
            return
        try:
            name = self.engine.query.save_view(
                update.effective_user.id,
                context.args[0],
                " ".join(context.args[1:]),
            )
            await update.effective_message.reply_text(f"Saved view: {name}. Open with /view {name}")
        except ValueError as e:
            await update.effective_message.reply_text(str(e))

    async def views(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update):
            return
        rows = self.engine.query.views(update.effective_user.id)
        lines = ["<b>ðŸ“š Saved Views</b>"]
        for r in rows:
            lines.append(f"â€¢ <code>{escape(r['view_name'])}</code> â€” {escape(r['query_text'])}")
        if not rows:
            lines.append("No saved views yet. Use /saveview NAME filters")
        await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

    async def view(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update):
            return
        if not context.args:
            await update.effective_message.reply_text("Usage: /view NAME")
            return
        r = self.engine.query.get_view(update.effective_user.id, context.args[0])
        if not r:
            await update.effective_message.reply_text("Saved view not found.")
            return
        await self._send_query_results(
            update.effective_message,
            r['query_text'],
            title=f"ðŸ“š {r['view_name']}",
        )

    async def lists(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update):
            return
        await self._send_lists(update.effective_message)

    async def _send_lists(self, message):
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("â­ VIP", callback_data="q:type:vip"), InlineKeyboardButton("ðŸ“¦ Suppliers", callback_data="q:type:supplier")],
            [InlineKeyboardButton("ðŸ‘¤ Customers", callback_data="q:type:customer"), InlineKeyboardButton("ðŸ¤ Partners", callback_data="q:type:partner")],
            [InlineKeyboardButton("ðŸ“‰ Health <50", callback_data="q:health<50"), InlineKeyboardButton("âŒ› Overdue", callback_data="q:overdue")],
            [InlineKeyboardButton("ðŸŒ‰ Bridges", callback_data="q:bridge"), InlineKeyboardButton("â” Unverified", callback_data="q:unverified")],
        ])
        await message.reply_text(
            "<b>ðŸ“š Working Lists</b>\nChoose a standard view, or use /find and /saveview for custom lists.",
            parse_mode=ParseMode.HTML,
            reply_markup=kb,
        )

    async def _send_query_results(self, message, query: str, title: str | None = None):
        rows = self.engine.query.search(query, limit=25)
        lines = [f"<b>{escape(title or 'ðŸ”Ž CRM Search')}</b>", f"<code>{escape(query)}</code>"]
        kb = []
        for r in rows:
            name = r['display_name'] or r['username'] or str(r['telegram_id'])
            health = r['health_score'] if r['health_score'] is not None else 50
            lines.append(
                f"â€¢ {escape(str(name))} Â· {escape(pretty(r['relationship_type']))} Â· "
                f"score {r['relationship_score']} Â· health {health}"
            )
            kb.append([InlineKeyboardButton(str(name)[:38], callback_data=f"open:{r['telegram_id']}")])
        if not rows:
            lines.append("No contacts match this view.")
        await message.reply_text(
            "\n".join(lines),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(kb[:15]) if kb else None,
        )

    async def integrations(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update): return
        backlog=self.engine.integration.backlog(); pending=backlog['total'] or 0
        exported=self.db.one("SELECT COUNT(*) n FROM integration_events WHERE status='exported'")['n']
        await update.effective_message.reply_text(
            f"<b>ðŸ”Œ Ecosystem Integration</b>\n\nBacklog: <b>{pending}</b> Â· retrying: <b>{backlog['retrying'] or 0}</b>\nExported signals: <b>{exported}</b>\n"
            f"Export folder: <code>{escape(str(self.engine.integration.export_dir))}</code>\n\n"
            "Prepared for future Universal Search, VM Guard and Admin Command Centre adapters. External risk signals enter as review items and do not automatically damage trust.",parse_mode=ParseMode.HTML)

    async def export_data(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update): return
        r=self.engine.integration.export_all()
        await update.effective_message.reply_text(
            f"âœ… Export refreshed.\nContacts indexed: {r['contacts']}\nNew integration events exported: {r['events']}\nFolder: {r['contacts_path']}")

    async def privacy(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update): return
        s=self.engine.privacy.summary()
        await update.effective_message.reply_text(
            f"<b>ðŸ” Relationship Manager Privacy</b>\n\nContacts: <b>{s['contacts']}</b>\n"
            f"Private direction/timing metadata events: <b>{s['private_metadata_events']}</b>\n"
            f"Archived: <b>{s['archived']}</b>\nExcluded: <b>{s['excluded']}</b>\n\n"
            "Message bodies are not stored by the Relationship Manager. Private interaction metadata is retained for behaviour analytics and automatically pruned.",
            parse_mode=ParseMode.HTML)

    async def archive(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update): return
        if not context.args: await update.effective_message.reply_text("Usage: /archive TELEGRAM_ID [reason]"); return
        tid=int(context.args[0]); self.engine.privacy.set_archived(tid,True," ".join(context.args[1:])); self.engine.event(tid,'contact_archived'," ".join(context.args[1:]) or None); await update.effective_message.reply_text("Contact archived from working views.")

    async def restore(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update): return
        if not context.args: await update.effective_message.reply_text("Usage: /restore TELEGRAM_ID"); return
        tid=int(context.args[0]); self.engine.privacy.set_archived(tid,False,'restored'); self.engine.event(tid,'contact_restored','Restored to active CRM views'); await update.effective_message.reply_text("Contact restored.")

    async def exclude(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update): return
        if not context.args: await update.effective_message.reply_text("Usage: /exclude TELEGRAM_ID [reason]"); return
        tid=int(context.args[0]); self.engine.privacy.set_excluded(tid,True," ".join(context.args[1:])); self.engine.event(tid,'contact_excluded'," ".join(context.args[1:]) or 'Excluded from future monitoring'); await update.effective_message.reply_text("Contact excluded from future Relationship Manager monitoring.")

    async def include(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update): return
        if not context.args: await update.effective_message.reply_text("Usage: /include TELEGRAM_ID"); return
        tid=int(context.args[0]); self.engine.privacy.set_excluded(tid,False,'included'); self.engine.event(tid,'contact_included','Future monitoring re-enabled'); await update.effective_message.reply_text("Contact monitoring re-enabled.")

    async def forgetbehavior(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update): return
        if not context.args: await update.effective_message.reply_text("Usage: /forgetbehavior TELEGRAM_ID"); return
        tid=int(context.args[0]); self.engine.privacy.forget_behavior(tid); self.engine.event(tid,'behavior_metadata_forgotten','Private interaction timing/direction metadata deleted'); await update.effective_message.reply_text("Private behaviour metadata deleted for this contact.")

    async def purgecontact(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update): return
        if len(context.args)!=2 or context.args[1] != 'CONFIRM':
            await update.effective_message.reply_text("Destructive action. Usage: /purgecontact TELEGRAM_ID CONFIRM"); return
        tid=int(context.args[0]); self.engine.privacy.purge_contact(tid); await update.effective_message.reply_text("Contact and Relationship Manager history purged.")

    async def changes(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update): return
        await self._send_changes(update.effective_message)

    async def _send_changes(self,message):
        self.engine.automation.evaluate_all()
        rows=self.engine.automation.recent_changes(days=7,limit=25)
        lines=["<b>ðŸ§­ Relationship Changes Â· last 7 days</b>"]
        kb=[]
        for r in rows:
            who=r['display_name'] or r['username'] or str(r['telegram_id'])
            lines.append(f"â€¢ {escape(str(who))} â€” {escape(pretty(r['event_type']))}: {escape((r['details'] or '')[:150])}")
            kb.append([InlineKeyboardButton(str(who)[:38],callback_data=f"open:{r['telegram_id']}")])
        if not rows: lines.append("No major relationship transitions recorded yet.")
        await message.reply_text("\n".join(lines),parse_mode=ParseMode.HTML,reply_markup=InlineKeyboardMarkup(kb[:15]) if kb else None)

    async def deal(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update): return
        if len(context.args)<2:
            await update.effective_message.reply_text("Usage: /deal TELEGRAM_ID opportunity title")
            return
        tid=int(context.args[0]); title=" ".join(context.args[1:])
        if not self.db.one("SELECT 1 FROM contacts WHERE telegram_id=?",(tid,)):
            await update.effective_message.reply_text("Contact not found."); return
        o=self.engine.opportunities.create(tid,title,update.effective_user.id)
        self.engine.event(tid,'opportunity_created',f"#{o['id']} {title}")
        await update.effective_message.reply_text(f"ðŸ’¼ Opportunity #{o['id']} created as Lead.")

    async def deals(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update): return
        if not context.args:
            await update.effective_message.reply_text("Usage: /deals TELEGRAM_ID"); return
        await self._send_deals(update.effective_message,int(context.args[0]))

    async def pipeline(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update): return
        await self._send_pipeline(update.effective_message)

    async def dealstage(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update): return
        if len(context.args)!=2:
            await update.effective_message.reply_text("Usage: /dealstage DEAL_ID lead|contacted|interested|negotiating|active|won|lost|paused"); return
        try:
            o=self.engine.opportunities.set_stage(int(context.args[0]),context.args[1])
            if not o: raise ValueError('Opportunity not found.')
            self.engine.event(o['telegram_id'],'opportunity_stage',f"#{o['id']} -> {o['stage']}")
            await update.effective_message.reply_text(f"Opportunity #{o['id']} â†’ {pretty(o['stage'])}.")
        except ValueError as e: await update.effective_message.reply_text(str(e))

    async def dealvalue(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update): return
        if len(context.args)<2:
            await update.effective_message.reply_text("Usage: /dealvalue DEAL_ID 1500 [AUD]"); return
        try:
            o=self.engine.opportunities.set_value(int(context.args[0]),float(context.args[1]),context.args[2] if len(context.args)>2 else 'AUD')
            await update.effective_message.reply_text(f"Opportunity #{o['id']} value set to {o['currency']} {o['value_cents']/100:,.2f}.")
        except (ValueError,TypeError) as e: await update.effective_message.reply_text(str(e))

    async def dealnext(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update): return
        if len(context.args)<3:
            await update.effective_message.reply_text("Usage: /dealnext DEAL_ID 7d next action"); return
        delta=self._parse_delta(context.args[1])
        if not delta:
            await update.effective_message.reply_text("Time must look like 7d, 12h or 30m."); return
        o=self.engine.opportunities.set_next(int(context.args[0])," ".join(context.args[2:]),datetime.now(timezone.utc)+delta)
        await update.effective_message.reply_text(f"Next action saved for opportunity #{o['id']}.")

    async def _send_deals(self,message,tid:int):
        c=self.db.one("SELECT * FROM contacts WHERE telegram_id=?",(tid,)); rows=self.engine.opportunities.open_for_contact(tid)
        if not c:
            await message.reply_text("Contact not found."); return
        lines=[f"<b>ðŸ’¼ Opportunities Â· {escape(contact_label(c))}</b>"]
        kb=[]
        for o in rows:
            value=f" Â· {o['currency']} {o['value_cents']/100:,.0f}" if o['value_cents'] is not None else ''
            due=f" Â· due {escape(self._local_time(o['due_at'],date_only=True))}" if o['due_at'] else ''
            lines.append(f"â€¢ #{o['id']} <b>{escape(o['title'])}</b> Â· {escape(pretty(o['stage']))}{value}{due} Â· health {o['health_score']}/100")
            kb.append([InlineKeyboardButton(f"#{o['id']} â†’ Negotiating",callback_data=f"dealstage:{o['id']}:negotiating"),InlineKeyboardButton("Won",callback_data=f"dealstage:{o['id']}:won")])
        if not rows: lines.append("No open opportunities. Use /deal TELEGRAM_ID title to create one.")
        await message.reply_text("\n".join(lines),parse_mode=ParseMode.HTML,reply_markup=InlineKeyboardMarkup(kb) if kb else None)

    async def _send_pipeline(self,message):
        rows=self.engine.opportunities.pipeline()
        summary=self.engine.opportunities.summary()
        values = " Â· ".join(f"{cur} {cents/100:,.0f}" for cur,cents in sorted(summary.get('by_currency',{}).items())) or "No known values"
        lines=["<b>ðŸ’¼ Opportunity Pipeline</b>",f"Open: <b>{summary['open']}</b> Â· unhealthy: <b>{summary['unhealthy']}</b> Â· weighted known value: <b>{escape(values)}</b>"]
        kb=[]
        for o in rows[:20]:
            who=o['display_name'] or o['username'] or str(o['telegram_id'])
            val=f" Â· {o['currency']} {o['value_cents']/100:,.0f}" if o['value_cents'] is not None else ''
            lines.append(f"â€¢ #{o['id']} {escape(str(who))} â€” <b>{escape(o['title'])}</b> Â· {escape(pretty(o['stage']))}{val} Â· health {o['health_score']}/100 Â· stale {o['stale_days']}d")
            kb.append([InlineKeyboardButton(f"Open {str(who)[:30]}",callback_data=f"open:{o['telegram_id']}")])
        if not rows: lines.append("Pipeline is empty.")
        await message.reply_text("\n".join(lines),parse_mode=ParseMode.HTML,reply_markup=InlineKeyboardMarkup(kb) if kb else None)

    async def network(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update):
            return
        if context.args:
            await self._send_network_contact(update.effective_message, int(context.args[0]))
        else:
            await self._send_network_overview(update.effective_message)

    async def bridges(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update):
            return
        await self._send_network_list(update.effective_message, bridges_only=True)

    async def _send_network_contact(self, message, tid: int):
        n=self.engine.get_network(tid, refresh=True)
        c=self.db.one("SELECT * FROM contacts WHERE telegram_id=?",(tid,))
        if not n or not c:
            await message.reply_text("No network data available.")
            return
        text=(
            f"<b>ðŸŒ Network Â· {escape(contact_label(c))}</b>\n\n"
            f"Reach: <b>{n['reach_score']}/100</b>\n"
            f"Bridge estimate: <b>{n['bridge_score']}/100</b>\n"
            f"Audience diversity: <b>{n['diversity_score']}/100</b>\n"
            f"Shared groups: <b>{n['shared_groups']}</b>\n"
            f"Active groups (30d): <b>{n['active_groups_30']}</b>\n"
            f"Known network neighbours: <b>{n['known_neighbors']}</b>\n"
            f"Network role: <b>{escape(pretty(n['network_label']))}</b>\n\n"
            "Computed only from groups/contacts already visible to the authorised Telegram account."
        )
        await message.reply_text(text, parse_mode=ParseMode.HTML)

    async def _send_network_overview(self, message):
        self.engine.recalculate_network_all()
        rows=self.db.all(
            """SELECT n.*, c.display_name, c.username, c.telegram_id
               FROM network_metrics n JOIN contacts c ON c.telegram_id=n.telegram_id
               LEFT JOIN contact_controls cc ON cc.telegram_id=c.telegram_id
               WHERE n.shared_groups>0 AND COALESCE(cc.archived,0)=0 AND COALESCE(cc.excluded,0)=0
               ORDER BY n.reach_score DESC, n.bridge_score DESC LIMIT 12"""
        )
        lines=["<b>ðŸŒ Network Intelligence</b>","Top known network-reach contacts:"]
        kb=[]
        for r in rows:
            name=r['display_name'] or r['username'] or str(r['telegram_id'])
            lines.append(f"â€¢ {escape(str(name))} Â· reach {r['reach_score']} Â· bridge {r['bridge_score']} Â· groups {r['shared_groups']}")
            kb.append([InlineKeyboardButton(str(name)[:38],callback_data=f"open:{r['telegram_id']}")])
        await message.reply_text("\n".join(lines),parse_mode=ParseMode.HTML,reply_markup=InlineKeyboardMarkup(kb) if kb else None)

    async def _send_network_list(self, message, bridges_only: bool=False):
        self.engine.recalculate_network_all()
        where="n.bridge_score>=55 AND n.shared_groups>=2" if bridges_only else "n.shared_groups>0"
        rows=self.db.all(
            f"""SELECT n.*, c.display_name, c.username, c.telegram_id
                FROM network_metrics n JOIN contacts c ON c.telegram_id=n.telegram_id
                LEFT JOIN contact_controls cc ON cc.telegram_id=c.telegram_id
                WHERE ({where}) AND COALESCE(cc.archived,0)=0 AND COALESCE(cc.excluded,0)=0
                ORDER BY n.bridge_score DESC, n.reach_score DESC LIMIT 15"""
        )
        title="ðŸŒ‰ Bridge contacts" if bridges_only else "ðŸŒ Network contacts"
        lines=[f"<b>{title}</b>"]
        kb=[]
        for r in rows:
            name=r['display_name'] or r['username'] or str(r['telegram_id'])
            lines.append(f"â€¢ {escape(str(name))} Â· bridge {r['bridge_score']} Â· reach {r['reach_score']}")
            kb.append([InlineKeyboardButton(str(name)[:38],callback_data=f"open:{r['telegram_id']}")])
        if not rows: lines.append("No qualifying contacts yet.")
        await message.reply_text("\n".join(lines),parse_mode=ParseMode.HTML,reply_markup=InlineKeyboardMarkup(kb) if kb else None)

    async def behavior(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update):
            return
        if not context.args:
            await update.effective_message.reply_text("Usage: /behavior TELEGRAM_ID")
            return
        await self._send_behavior(update.effective_message, int(context.args[0]))

    async def _send_behavior(self, message, tid: int):
        row = self.engine.get_behavior(tid, refresh=True)
        c = self.db.one("SELECT * FROM contacts WHERE telegram_id=?", (tid,))
        if not c or not row:
            await message.reply_text("No behaviour data available.")
            return
        def duration(v):
            if v is None:
                return "Learning"
            v=float(v)
            if v < 60:
                return f"{v:.0f}s"
            if v < 3600:
                return f"{v/60:.0f}m"
            if v < 86400:
                return f"{v/3600:.1f}h"
            return f"{v/86400:.1f}d"
        text=(
            f"<b>ðŸ” Behaviour Â· {escape(contact_label(c))}</b>\n\n"
            f"Pattern: <b>{escape(pretty(row['behavior_label']))}</b>\n"
            f"Reciprocity: <b>{row['reciprocity_score']}/100</b>\n"
            f"Consistency: <b>{row['consistency_score']}/100</b>\n"
            f"Acceleration: <b>{row['acceleration_pct']:+.1f}%</b>\n\n"
            f"<b>Private messages Â· last 30d</b>\n"
            f"Incoming: {row['incoming_30']} Â· Outgoing: {row['outgoing_30']}\n"
            f"Conversation starts Â· them {row['incoming_initiations_60']} / you {row['outgoing_initiations_60']}\n\n"
            f"Typical response Â· you: {escape(duration(row['median_our_response_seconds']))} "
            f"({row['our_response_samples']} samples)\n"
            f"Typical response Â· them: {escape(duration(row['median_their_response_seconds']))} "
            f"({row['their_response_samples']} samples)\n\n"
            "Metadata only: message text is not stored."
        )
        await message.reply_text(text, parse_mode=ParseMode.HTML)

    async def attention(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update):
            return
        await self._send_attention(update.effective_message)

    async def _send_attention(self, message):
        rows = self.db.all(
            """SELECT a.*, c.username, c.display_name
               FROM attention_queue a
               LEFT JOIN contacts c ON c.telegram_id=a.telegram_id
               LEFT JOIN contact_controls cc ON cc.telegram_id=a.telegram_id
               WHERE a.status='open' AND COALESCE(cc.archived,0)=0 AND COALESCE(cc.excluded,0)=0
               ORDER BY CASE priority WHEN 'red' THEN 1 WHEN 'orange' THEN 2 ELSE 3 END,
                        a.created_at ASC LIMIT 20"""
        )
        if not rows:
            await message.reply_text("No open attention items.")
            return

        lines = ["<b>âš ï¸ VM ATTENTION</b>\n"]
        buttons = []
        for r in rows:
            who = r["display_name"] or r["username"] or r["telegram_id"]
            lines.append(
                f"â€¢ <b>{escape(r['priority'].upper())}</b> â€” "
                f"{escape(str(who))}: {escape(r['title'])}\n"
                f"  {escape((r['details'] or '')[:120])}"
            )
            if r["telegram_id"] and len(buttons) < 10:
                buttons.append([
                    InlineKeyboardButton(
                        f"ðŸ‘¤ {str(who)[:22]}",
                        callback_data=f"open:{r['telegram_id']}",
                    ),
                    InlineKeyboardButton(
                        f"âœ… Clear #{r['id']}",
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
        lines = ["<b>ðŸ”” OPEN FOLLOW-UPS</b>\n"]
        buttons = []
        for r in rows:
            who = r["display_name"] or r["username"] or str(r["telegram_id"])
            due_dt = datetime.fromisoformat(r["due_at"])
            overdue = due_dt <= now
            marker = "ðŸ”´ DUE" if overdue else "ðŸ—“"
            local_due = due_dt.astimezone(self.settings.timezone).strftime(
                "%d %b %Y, %I:%M %p"
            )
            lines.append(
                f"â€¢ {marker} <code>#{r['id']}</code> â€” {escape(str(who))}\n"
                f"  {escape(local_due)} Â· {escape((r['reason'] or 'Follow-up')[:100])}"
            )
            if len(buttons) < 10:
                buttons.append([
                    InlineKeyboardButton(
                        f"âœ… Done #{r['id']}",
                        callback_data=f"followup_done:{r['id']}",
                    ),
                    InlineKeyboardButton(
                        f"ðŸ‘¤ {str(who)[:24]}",
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
            f"""SELECT c.* FROM contacts c
                LEFT JOIN contact_controls cc ON cc.telegram_id=c.telegram_id
                WHERE ({where}) AND COALESCE(cc.archived,0)=0 AND COALESCE(cc.excluded,0)=0
                ORDER BY c.relationship_score DESC, c.last_seen DESC LIMIT 30"""
        )
        if not rows:
            await message.reply_text(f"No {title.lower()} contacts.")
            return

        lines = [f"<b>{escape(title)}</b>\n"]
        buttons = []
        for r in rows:
            lines.append(
                f"â€¢ <code>{r['telegram_id']}</code> â€” {escape(contact_label(r))} "
                f"Â· {r['relationship_score']}/100 Â· {escape(crm_stage(r))}"
            )
            if len(buttons) < 10:
                buttons.append([
                    InlineKeyboardButton(
                        f"ðŸ‘¤ {contact_label(r)[:38]}",
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
            "ðŸ”„ Refreshing recent accessible Telegram contacts in the background. "
            "Live monitoring continues while this runs."
        )
        result = await self.monitor.bootstrap_recent_history(force=True)
        if result.get("status") == "already_running":
            await update.effective_message.reply_text(
                "A contact refresh is already running."
            )
            return
        await update.effective_message.reply_text(
            f"âœ… Contact refresh complete.\n"
            f"Dialogs checked: {result.get('dialogs', 0)}\n"
            f"Contacts seeded/refreshed: {result.get('contacts', 0)}"
        )

    async def health(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update):
            return
        rows = self.db.all("SELECT * FROM bot_health ORDER BY id DESC LIMIT 10")
        lines = ["<b>Health log</b>"]
        for r in rows:
            lines.append(f"â€¢ {escape(r['component'])}: {escape(r['status'])} â€” {escape((r['details'] or '')[:120])}")
        await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

    async def callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.allowed(update):
            return
        q = update.callback_query
        await q.answer()
        data = q.data

        if data == "brief":
            self.engine.classification.compute_all(auto_apply=True)
            self.engine.priority.refresh_all()
            self.engine.actions.compute_all()
            brief=self.engine.briefing.build()
            lines=["<b>ðŸ§­ VM EXECUTIVE RELATIONSHIP BRIEF</b>",
                   f"ðŸ”¥ Growing: <b>{brief['growing_relationships']}</b>",
                   f"ðŸ”­ High disengagement risk: <b>{brief['high_disengagement_risk']}</b>",
                   f"ðŸŽ¯ Overdue goals: <b>{len(brief['overdue_goals'])}</b>",
                   f"ðŸ’¼ Unhealthy opportunities: <b>{brief['unhealthy_opportunities']}</b>",
                   f"ðŸ›¡ Pending risk reviews: <b>{brief['pending_risks']}</b>",
                   f"ðŸ¤– Unknown: <b>{brief.get('unknown_contacts',0)}</b> Â· auto-classified: <b>{brief.get('auto_classified',0)}</b>",
                   f"ðŸš¨ Eligible exceptions: <b>{brief.get('exception_actions',0)}</b> Â· policy-selected: <b>{brief.get('policy_selected_exceptions',0)}</b>","","<b>Top exception actions</b>"]
            buttons=[]
            for r in brief.get('top_exception_actions', []):
                who=r['display_name'] or r['username'] or str(r['telegram_id'])
                lines.append(f"â€¢ {escape(str(who))} Â· {r['action_score']}/100 â€” {escape(r['title'] or 'Review relationship')}")
                buttons.append([InlineKeyboardButton(str(who)[:38],callback_data=f"open:{r['telegram_id']}")])
            if not brief.get('top_exception_actions'): lines.append("â€¢ No policy-selected exception action is currently urgent.")
            await q.message.reply_text("\n".join(lines),parse_mode=ParseMode.HTML,reply_markup=InlineKeyboardMarkup(buttons[:10]) if buttons else None)
        elif data == "exceptions":
            await self._send_exceptions(q.message)
        elif data == "autonomy":
            cfg=self.engine.autonomy.settings(); stats=self.engine.classification.stats(); action_stats=self.engine.actions.stats()
            await q.message.reply_text(
                f"<b>ðŸ¤– VM AUTONOMY</b>\nMode: <b>{escape(cfg['mode'].upper())}</b>\n"
                f"Unknown contacts: {stats['unknown']} Â· suggestions: {stats['suggested']} Â· auto-applied: {stats['auto_applied']}\n"
                f"Exception actions: {action_stats['exceptions']}\n\n"
                "SAFE mode never messages contacts automatically.", parse_mode=ParseMode.HTML)
        elif data == "classification":
            result=self.engine.classification.compute_all(auto_apply=True); stats=self.engine.classification.stats()
            await q.message.reply_text(
                f"<b>ðŸ§  CLASSIFIER</b>\nChecked: {result['computed']} Â· auto-applied this pass: {result['newly_applied']}\n"
                f"Unknown remaining: {stats['unknown']} Â· review suggestions: {stats['suggested']}", parse_mode=ParseMode.HTML)
        elif data == "maintain":
            result=self.maintenance.run_safe(allow_backup=True)
            await q.message.reply_text(
                f"<b>âš™ï¸ SAFE MAINTENANCE â€” {escape(result['status'].upper())}</b>\n"
                f"Actions: {len(result['actions'])} Â· remaining findings: {len(result['after'])}", parse_mode=ParseMode.HTML)
        elif data.startswith("classification:"):
            await self._send_classification(q.message, int(data.split(":",1)[1]))
        elif data.startswith("classapply:"):
            tid=int(data.split(":",1)[1]); row=self.engine.classification.apply_prediction(tid, update.effective_user.id)
            if row:
                self.engine.recalculate_contact(tid); self.engine.priority.compute(tid); self.engine.actions.compute(tid)
                await q.message.reply_text(f"âœ… Classification applied and locked: {pretty(row['predicted_type'])}.")
            else:
                await q.message.reply_text("No classifier prediction is available to apply.")
        elif data.startswith("classlock:"):
            tid=int(data.split(":",1)[1]); self.engine.classification.set_lock(tid, True, update.effective_user.id, 'Profile classifier lock')
            await q.message.reply_text("ðŸ”’ Current relationship type locked against automatic classification changes.")
        elif data.startswith("classunlock:"):
            tid=int(data.split(":",1)[1]); self.engine.classification.set_lock(tid, False, update.effective_user.id, 'Classifier unlocked')
            await q.message.reply_text("ðŸ”“ Classifier suggestions re-enabled. Existing non-unknown type will still not be overwritten automatically.")
        elif data.startswith("actiondone:"):
            aid=int(data.split(":",1)[1]); ok=self.engine.actions.resolve(aid,'done')
            await q.message.reply_text("âœ… Recommended action completed." if ok else "Action not found.")
        elif data.startswith("actiondismiss:"):
            action_id=int(data.split(":",1)[1]); ok=self.engine.actions.resolve(action_id,'dismissed')
            days=self.engine.exception_policy.settings()['dismissal_cooldown_days']
            await q.message.reply_text(f"ðŸš« Action dismissed for {days}d." if ok else "Action not found.")
        elif data.startswith("actionsnooze:"):
            _,aid,days=data.split(":",2); ok=self.engine.actions.snooze(int(aid),int(days))
            await q.message.reply_text(f"ðŸ˜´ Recommended action snoozed for {days} day(s)." if ok else "Action not found.")
        elif data == "segments":
            self.engine.segments.compute_all()
            rows=self.engine.segments.overview(); lines=["<b>ðŸ§© Dynamic CRM Segments</b>"]; buttons=[]
            for r in rows:
                lines.append(f"â€¢ {escape(pretty(r['segment_key']))}: <b>{r['contacts']}</b>")
                buttons.append([InlineKeyboardButton(f"{pretty(r['segment_key'])} ({r['contacts']})",callback_data=f"segment:{r['segment_key']}")])
            if not rows: lines.append("Segments are still learning.")
            await q.message.reply_text("\n".join(lines),parse_mode=ParseMode.HTML,reply_markup=InlineKeyboardMarkup(buttons[:15]) if buttons else None)
        elif data == "goals_overview":
            rows=self.engine.goals.list(None,'active',25); lines=["<b>ðŸŽ¯ Active Relationship Goals</b>"]; buttons=[]
            for g in rows:
                who=g['display_name'] or g['username'] or str(g['telegram_id'])
                lines.append(f"â€¢ #{g['id']} {escape(str(who))}: {escape(g['title'])} Â· {g['progress_pct']}%")
                buttons.append([InlineKeyboardButton(f"âœ… Complete #{g['id']}",callback_data=f"goalcomplete:{g['id']}"),InlineKeyboardButton("ðŸ‘¤",callback_data=f"open:{g['telegram_id']}")])
            if not rows: lines.append("No active goals.")
            await q.message.reply_text("\n".join(lines),parse_mode=ParseMode.HTML,reply_markup=InlineKeyboardMarkup(buttons[:12]) if buttons else None)
        elif data == "today":
            await self._send_today(q.message)
        elif data == "insights":
            await self._send_insights(q.message)
        elif data == "growing":
            await self._send_intelligence_list(
                q.message, "ðŸ”¥ Growing relationships",
                "i.momentum_label IN ('growing','surging')",
                "i.momentum_score DESC, c.relationship_score DESC",
            )
        elif data == "slipping":
            await self._send_intelligence_list(
                q.message, "ðŸ“‰ Relationships to watch",
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
        elif data == "changes":
            await self._send_changes(q.message)
        elif data == "pipeline":
            await self._send_pipeline(q.message)
        elif data == "network_overview":
            await self._send_network_overview(q.message)
        elif data == "bridges":
            await self._send_network_list(q.message, bridges_only=True)
        elif data == "lists":
            await self._send_lists(q.message)
        elif data == "diagnostics":
            integrity = self.db.integrity_check()
            await q.message.reply_text(
                f"ðŸ©º Schema {self.db.meta('schema_version','unknown')} Â· SQLite {'OK' if integrity == ['ok'] else 'CHECK'} Â· use /diagnostics for details."
            )
        elif data == "groups_overview":
            self.engine.groups.compute_all()
            await self._send_groups_overview(q.message)
        elif data == "risks":
            await self._send_risks(q.message)
        elif data == "report_weekly":
            await self._send_report(q.message, self.engine.reporting.build("weekly"))
        elif data == "forecast":
            await self.forecast_from_message(q.message)
        elif data.startswith("goalcomplete:"):
            gid=int(data.split(":",1)[1])
            try:
                row=self.engine.goals.complete(gid)
                if not row: raise ValueError("Goal not found.")
                self.engine.event(row['telegram_id'],'goal_completed',f"#{row['id']} {row['title']}")
                self.engine.automation.process_goal_due(); self.engine.priority.compute(row['telegram_id'])
                await q.message.reply_text(f"âœ… Goal #{gid} completed.")
            except ValueError as exc: await q.message.reply_text(str(exc))
        elif data.startswith("segment:"):
            await self._send_segment(q.message, data.split(":",1)[1])
        elif data.startswith("outlook:"):
            await self._send_outlook(q.message, int(data.split(":",1)[1]))
        elif data.startswith("sessions:"):
            await self._send_sessions(q.message, int(data.split(":",1)[1]))
        elif data.startswith("goals:"):
            tid=int(data.split(":",1)[1])
            rows=self.engine.goals.list(tid,'active',20)
            lines=[f"<b>ðŸŽ¯ Active goals â€” {tid}</b>"]
            buttons=[]
            for g in rows:
                due=self._local_time(g['target_at']) if g['target_at'] else 'No due date'
                lines.append(f"â€¢ #{g['id']} {escape(g['title'])} Â· {g['progress_pct']}% Â· {escape(due)}")
                buttons.append([InlineKeyboardButton(f"âœ… Complete #{g['id']}",callback_data=f"goalcomplete:{g['id']}")])
            if not rows: lines.append("No active goals.")
            await q.message.reply_text("\n".join(lines),parse_mode=ParseMode.HTML,reply_markup=InlineKeyboardMarkup(buttons) if buttons else None)
        elif data.startswith("playbook:"):
            await self._send_playbook(q.message, int(data.split(":",1)[1]))
        elif data.startswith("priority_snooze:"):
            _,tid,delta_text=data.split(":",2)
            delta=self._parse_delta(delta_text)
            until=(datetime.now(timezone.utc)+delta).isoformat() if delta and delta.total_seconds()>0 else None
            self.engine.priority.snooze(int(tid),until)
            await q.message.reply_text(f"ðŸ˜´ Priority snoozed for {delta_text}.")
        elif data.startswith("priority:"):
            await self._send_priority(q.message, int(data.split(":",1)[1]))
        elif data.startswith("memories:"):
            await self._send_memories(q.message, int(data.split(":",1)[1]))
        elif data.startswith("group:"):
            await self._send_group_detail(q.message, int(data.split(":",1)[1]))
        elif data.startswith("riskconfirm:"):
            fid=int(data.split(":",1)[1])
            try:
                tid=self.engine.risk.review(fid,"confirmed",update.effective_user.id)
                self.engine.recalculate_contact(tid)
                self.engine.integration.emit("risk_reviewed",tid,{"flag_id":fid,"status":"confirmed"})
                await q.message.reply_text(f"âœ… Risk #{fid} confirmed; trust and priority recalculated.")
            except ValueError as exc: await q.message.reply_text(str(exc))
        elif data.startswith("riskdismiss:"):
            fid=int(data.split(":",1)[1])
            try:
                tid=self.engine.risk.review(fid,"dismissed",update.effective_user.id)
                self.engine.recalculate_contact(tid)
                self.engine.integration.emit("risk_reviewed",tid,{"flag_id":fid,"status":"dismissed"})
                await q.message.reply_text(f"âŒ Risk #{fid} dismissed; priority recalculated.")
            except ValueError as exc: await q.message.reply_text(str(exc))
        elif data.startswith("q:"):
            await self._send_query_results(q.message, data[2:])
        elif data == "searchhelp":
            await q.message.reply_text("Search: send a name/@username, or use /find type:supplier inactive>14, health<50 score>60, momentum:growing, tag:wholesale, group:name.")
        elif data == "rescan":
            if self.monitor is None or not self.monitor.ready.is_set():
                await q.message.reply_text("Telegram monitoring account is still connecting.")
            else:
                await q.message.reply_text("ðŸ”„ Refreshing recent accessible contacts...")
                result = await self.monitor.bootstrap_recent_history(force=True)
                if result.get("status") == "already_running":
                    await q.message.reply_text("A contact refresh is already running.")
                else:
                    await q.message.reply_text(
                        f"âœ… Contact refresh complete. "
                        f"Dialogs: {result.get('dialogs', 0)} Â· "
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
                await q.message.reply_text(f"ðŸ”” Follow-up set for +{delta_text}.")
        elif data.startswith("followup_done:"):
            followup_id = int(data.split(":", 1)[1])
            if self.engine.complete_followup(followup_id, update.effective_user.id):
                await q.message.reply_text(f"âœ… Follow-up #{followup_id} completed.")
            else:
                await q.message.reply_text("Follow-up not found.")
        elif data.startswith("attention_done:"):
            attention_id = int(data.split(":", 1)[1])
            if self.engine.resolve_attention(attention_id, update.effective_user.id):
                await q.message.reply_text(f"âœ… Attention item #{attention_id} cleared.")
            else:
                await q.message.reply_text("Attention item was already cleared or not found.")
        elif data.startswith("groups:"):
            tid = int(data.split(":", 1)[1])
            rows = self.db.all(
                """SELECT chat_title, chat_id, first_seen, last_seen, interaction_count
                   FROM contact_groups WHERE telegram_id=? AND chat_id<0
                   ORDER BY last_seen DESC LIMIT 30""",
                (tid,),
            )
            if not rows:
                await q.message.reply_text("No known groups for this contact.")
            else:
                lines = ["<b>ðŸ˜ Known groups</b>"]
                for r in rows:
                    title = r["chat_title"] or str(r["chat_id"])
                    lines.append(
                        f"â€¢ {escape(str(title))} Â· {r['interaction_count']} live interactions\n"
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
                    f"â€¢ {escape(self._local_time(r['created_at']))} â€” "
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
                    f"<b>ðŸ§  {escape(contact_label(c))}</b>\n\n"
                    f"â¤ï¸ Health: <b>{intel['health_score']}/100</b>\n"
                    f"ðŸ“Š Momentum: <b>{escape(pretty(intel['momentum_label']))}</b> "
                    f"({intel['momentum_score']:+d})\n"
                    f"ðŸ§­ Lifecycle: <b>{escape(pretty(intel['lifecycle_stage']))}</b>\n"
                    f"â± Typical cycle: {escape(cycle)}\n"
                    f"âŒ› Days beyond cycle: {intel['days_overdue']}\n\n"
                    f"<b>Recent 7 days</b>\n"
                    f"Interactions: {intel['recent_7_interactions']} Â· Active days: {intel['recent_7_active_days']}\n"
                    f"<b>Previous 7 days</b>\n"
                    f"Interactions: {intel['previous_7_interactions']} Â· Active days: {intel['previous_7_active_days']}\n\n"
                    f"<b>Recommended action</b>\n{escape(intel['suggested_action'] or 'No immediate action needed.')}"
                )
                await q.message.reply_text(text, parse_mode=ParseMode.HTML)
        elif data.startswith("archive:"):
            tid=int(data.split(":",1)[1]); self.engine.privacy.set_archived(tid,True,'profile button'); self.engine.event(tid,'contact_archived','Profile button'); await q.message.reply_text("ðŸ“¦ Contact archived.")
        elif data.startswith("exclude:"):
            tid=int(data.split(":",1)[1]); self.engine.privacy.set_excluded(tid,True,'profile button'); self.engine.event(tid,'contact_excluded','Profile button'); await q.message.reply_text("ðŸš« Contact excluded from future monitoring. Use /include TELEGRAM_ID to reverse.")
        elif data.startswith("deals:"):
            tid=int(data.split(":",1)[1])
            await self._send_deals(q.message,tid)
        elif data.startswith("dealstage:"):
            _,oid,stage=data.split(":",2)
            try:
                o=self.engine.opportunities.set_stage(int(oid),stage)
                if o:
                    self.engine.event(o['telegram_id'],'opportunity_stage',f"#{o['id']} -> {o['stage']}")
                    await q.message.reply_text(f"ðŸ’¼ Opportunity #{o['id']} â†’ {pretty(o['stage'])}.")
            except ValueError as e:
                await q.message.reply_text(str(e))
        elif data.startswith("network:"):
            tid = int(data.split(":", 1)[1])
            await self._send_network_contact(q.message, tid)
        elif data.startswith("behavior:"):
            tid = int(data.split(":", 1)[1])
            await self._send_behavior(q.message, tid)
        elif data.startswith("contact_actions:"):
            tid = int(data.split(":",1)[1])
            c=self.db.one("SELECT * FROM contacts WHERE telegram_id=?",(tid,))
            rows=self.engine.actions.for_contact(tid,10)
            lines=[f"<b>ðŸ§­ Recommended Actions Â· {escape(contact_label(c)) if c else tid}</b>"]
            buttons=[]
            for r in rows:
                lines.append(f"â€¢ #{r['id']} {escape(r['title'])} Â· {r['action_score']}/100 Â· {r['confidence']}%")
                buttons.append([InlineKeyboardButton(f"âœ… Done #{r['id']}",callback_data=f"actiondone:{r['id']}"),InlineKeyboardButton("ðŸ˜´ 7d",callback_data=f"actionsnooze:{r['id']}:7")])
            if not rows: lines.append("No open recommended admin actions.")
            await q.message.reply_text("\n".join(lines),parse_mode=ParseMode.HTML,reply_markup=InlineKeyboardMarkup(buttons[:10]) if buttons else None)
        elif data.startswith("contact_attention:"):
            tid = int(data.split(":")[1])
            rows = self.db.all(
                "SELECT * FROM attention_queue WHERE telegram_id=? AND status='open' ORDER BY id DESC LIMIT 10", (tid,)
            )
            if not rows:
                await q.message.reply_text("No open attention items for this contact.")
            else:
                await q.message.reply_text("\n".join(f"â€¢ {r['priority'].upper()} â€” {r['title']}: {r['details'] or ''}" for r in rows))

    def digest_text(self, weekly: bool = False) -> str:
        self.engine.calibration.refresh()
        self.engine.classification.compute_all(auto_apply=True)
        self.engine.priority.refresh_all()
        self.engine.actions.compute_all()
        total = self.db.one("SELECT COUNT(*) n FROM contacts c LEFT JOIN contact_controls cc ON cc.telegram_id=c.telegram_id WHERE COALESCE(cc.archived,0)=0 AND COALESCE(cc.excluded,0)=0")["n"]
        new_days = 7 if weekly else 1
        cutoff = (datetime.now(timezone.utc) - timedelta(days=new_days)).isoformat()
        new_contacts = self.db.one("SELECT COUNT(*) n FROM contacts c LEFT JOIN contact_controls cc ON cc.telegram_id=c.telegram_id WHERE c.first_seen>=? AND COALESCE(cc.archived,0)=0 AND COALESCE(cc.excluded,0)=0", (cutoff,))["n"]
        growing = self.db.one("SELECT COUNT(*) n FROM contact_intelligence i LEFT JOIN contact_controls cc ON cc.telegram_id=i.telegram_id WHERE i.momentum_label IN ('growing','surging') AND COALESCE(cc.archived,0)=0 AND COALESCE(cc.excluded,0)=0")["n"]
        slipping = self.db.one("SELECT COUNT(*) n FROM contact_intelligence i JOIN contacts c ON c.telegram_id=i.telegram_id WHERE c.relationship_score>=40 AND i.health_score<55")["n"]
        overdue_cycle = self.db.one("SELECT COUNT(*) n FROM contact_intelligence i LEFT JOIN contact_controls cc ON cc.telegram_id=i.telegram_id WHERE i.days_overdue>0 AND COALESCE(cc.archived,0)=0 AND COALESCE(cc.excluded,0)=0")["n"]
        followups = self.db.one("SELECT COUNT(*) n FROM followups WHERE status='open' AND due_at<=?", (utcnow(),))["n"]
        risks = self.db.one("SELECT COUNT(*) n FROM risk_flags WHERE review_status='pending'")["n"]
        opp = self.engine.opportunities.summary()
        high_priority = self.db.one("SELECT COUNT(*) n FROM contact_priorities WHERE priority_score>=50")["n"]
        goal_stats = self.engine.goals.stats()
        high_outlook = self.db.one("SELECT COUNT(*) n FROM contact_forecasts WHERE disengagement_risk>=60")["n"] if self.db.table_exists('contact_forecasts') else 0
        class_stats = self.engine.classification.stats()
        action_stats = self.engine.actions.stats()
        policy_summary = self.engine.exception_policy.summary()
        exception_top = self.engine.exception_policy.select(5)
        top = self.engine.priority.top(5)
        label = "WEEKLY" if weekly else "DAILY"
        text = (
            f"<b>ðŸ¤ VM {label} RELATIONSHIP BRIEF</b>\n\n"
            f"ðŸ‘¥ Total contacts: <b>{total}</b>\n"
            f"ðŸ†• New: <b>{new_contacts}</b>\n"
            f"ðŸ”¥ Growing: <b>{growing}</b>\n"
            f"ðŸ“‰ Needs watching: <b>{slipping}</b>\n"
            f"âŒ› Outside learned cycle: <b>{overdue_cycle}</b>\n"
            f"ðŸ”” Due follow-ups: <b>{followups}</b>\n"
            f"ðŸŽ¯ High-priority: <b>{high_priority}</b>\n"
            f"ðŸ›¡ Pending risk reviews: <b>{risks}</b>\n"
            f"ðŸ’¼ Open opportunities: <b>{opp['open']}</b> Â· unhealthy: <b>{opp['unhealthy']}</b>\n"
            f"ðŸ¤– Unknown contacts: <b>{class_stats['unknown']}</b> Â· classifier suggestions: <b>{class_stats['suggested']}</b>\n"
            f"ðŸš¨ Exception actions: <b>{action_stats['exceptions']}</b> Â· policy-selected: <b>{policy_summary['selected']}</b>"
        )
        meaningful=[r for r in top if int(r['priority_score'] or 0)>0]
        if meaningful:
            text += "\n\n<b>Top priorities</b>"
            for r in meaningful:
                who=r['display_name'] or r['username'] or str(r['telegram_id'])
                text += f"\nâ€¢ {escape(str(who))} Â· {r['priority_score']}/100: {escape(r['next_action'] or '')}"
        if exception_top:
            text += "\n\n<b>Exception inbox</b>"
            for r in exception_top:
                who=r['display_name'] or r['username'] or str(r['telegram_id'])
                text += f"\nâ€¢ {escape(str(who))} Â· {r['action_score']}/100: {escape(r['title'])}"
        text += "\n\nUse /exceptions for exception-only work or /today for full ranked priorities."
        return text

    async def notify_admins(self, text: str):
        for admin_id in self.settings.admin_ids:
            try:
                await self.app.bot.send_message(admin_id, text, parse_mode=ParseMode.HTML)
            except Exception:
                # Admin may not have started the control bot yet.
                pass

    async def send_daily_digest(self, context: ContextTypes.DEFAULT_TYPE):
        self.engine.calibration.refresh()
        self.engine.classification.compute_all(auto_apply=True)
        self.engine.priority.refresh_all(); self.engine.actions.compute_all()
        cfg = self.engine.autonomy.settings()
        if cfg['suppress_clear_digests'] and not self.engine.exception_policy.select(1, cfg['exception_threshold']):
            return
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
        await self.app.bot.set_my_commands([
            BotCommand("rm", "Relationship control centre"),
            BotCommand("brief", "Executive relationship brief"),
            BotCommand("exceptions", "Exception-only admin inbox"),
            BotCommand("today", "Ranked priorities"),
            BotCommand("autonomy", "Autonomy mode and policy"),
            BotCommand("classify", "Automatic classification"),
            BotCommand("person", "Open a contact profile"),
            BotCommand("goals", "Relationship goals"),
            BotCommand("segments", "Dynamic CRM segments"),
            BotCommand("outlook", "Contact engagement outlook"),
            BotCommand("priority", "Explain contact priority"),
            BotCommand("find", "Filter/search CRM contacts"),
            BotCommand("groups", "Group intelligence"),
            BotCommand("pipeline", "Opportunity pipeline"),
            BotCommand("actions", "Recommended admin actions"),
            BotCommand("maintain", "Run safe self-healing maintenance"),
            BotCommand("policy", "Exception workload policy"),
            BotCommand("calibration", "Classifier feedback calibration"),
            BotCommand("ops", "Operational SLO health"),
            BotCommand("doctor", "Operational doctor"),
            BotCommand("diagnostics", "System diagnostics"),
            BotCommand("help", "Commands and examples"),
        ])
        await self.app.updater.start_polling(drop_pending_updates=True)
        await self.notify_admins("<b>ðŸŸ¢ VM Relationship Manager Online</b>\nPassive monitoring and admin controls are active.")

    async def stop(self):
        await self.app.updater.stop()
        await self.app.stop()
        await self.app.shutdown()
