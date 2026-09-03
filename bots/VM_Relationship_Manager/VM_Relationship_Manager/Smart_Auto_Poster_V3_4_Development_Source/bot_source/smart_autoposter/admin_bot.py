from __future__ import annotations

from . import __version__
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .core import add_campaign_content, campaign_preview, clone_campaign, create_campaign, enqueue_campaign
from .db import Database, utcnow
from .notifications import NotificationManager
from .operations import (
    audit,
    manage_job,
    mark_campaign_previewed,
    operational_summary,
    set_campaign_state,
    set_content_state,
)
from .safety import SafetyController
from .scheduler import configure_daily, configure_interval, configure_once
from .collections import list_collections, collection_preview
from .recommendations import generate_recommendations, list_recommendations, apply_recommendation, dismiss_recommendation
from .reports import daily_report_text, weekly_report_text


def _short(value, n=40):
    value = str(value or "").replace("\n", " ")
    return value if len(value) <= n else value[: n - 1] + "…"


def dashboard_text(db: Database) -> str:
    summary = operational_summary(db, 24)
    q = summary["queue_status"]
    accounts = summary["accounts"]
    lines = [f"🤖 SMART AUTO POSTER V{__version__}", "", "SYSTEM"]
    for a in accounts:
        icon = "🟢" if a.get("authorized") and not a.get("cooldown_until") else ("🟡" if a.get("authorized") else "🔴")
        lines.append(f"{icon} {a['account_key'].title()}: {_short(a.get('identity') or 'unknown', 24)} | health {a.get('health_score',100)}")
    lines += ["", "CAMPAIGNS"]
    states = summary["campaigns"]
    lines.append(f"Active {states.get('active',0)} | Paused {states.get('paused',0)} | Draft {states.get('draft',0)} | Ready {states.get('ready',0)}")
    d = summary["destinations"]
    lines += ["", "DESTINATIONS", f"Enabled {d.get('enabled',0)} | Review {d.get('review',0)} | Quarantined {d.get('quarantined',0)}"]
    lines += ["", "QUEUE", f"Pending {q.get('pending',0)} | Deferred {q.get('deferred',0)} | Failed {q.get('failed',0)} | Uncertain {q.get('uncertain',0)}"]
    lines.append(f"24h success rate: {summary['success_rate']:.2f}%")
    return "\n".join(lines)


def campaigns_text(db: Database, limit: int = 12) -> str:
    with db.connect() as con:
        rows = con.execute(
            '''SELECT c.campaign_id,c.name,c.lifecycle_state,c.priority,c.category,c.max_cycles,c.completed_cycles,
               (SELECT COUNT(*) FROM campaign_content cc WHERE cc.campaign_id=c.campaign_id AND cc.enabled=1) variants,
               s.mode schedule_mode,s.next_run_at
               FROM campaigns c LEFT JOIN campaign_schedules s ON s.campaign_id=c.campaign_id
               ORDER BY c.enabled DESC,c.priority DESC,c.campaign_id LIMIT ?''',
            (limit,),
        ).fetchall()
    if not rows:
        return "No campaigns yet."
    lines = ["📣 CAMPAIGNS"]
    for r in rows:
        icon = "🟢" if r["lifecycle_state"] == "active" else ("⏸" if r["lifecycle_state"] == "paused" else "⚪")
        lines.append(f"{icon} {r['campaign_id']} — {_short(r['name'],24)} | {r['variants']} variant(s) | {r['schedule_mode'] or 'manual'} | cycles {r['completed_cycles']}/{r['max_cycles'] or '∞'}")
    return "\n".join(lines)


def content_text(db: Database, limit: int = 15) -> str:
    with db.connect() as con:
        rows = con.execute(
            '''SELECT c.content_id,c.lifecycle_state,c.enabled,length(c.caption) caption_chars,
               (SELECT COUNT(*) FROM campaign_content cc WHERE cc.content_id=c.content_id AND cc.enabled=1) campaigns
               FROM content c ORDER BY c.enabled DESC,c.updated_at DESC,c.content_id LIMIT ?''',
            (limit,),
        ).fetchall()
    if not rows:
        return "No content registered yet."
    lines = ["🗂 CONTENT LIBRARY"]
    for r in rows:
        icon = "🟢" if r["lifecycle_state"] == "ready" else "⚪"
        lines.append(f"{icon} {r['content_id']} | {r['lifecycle_state']} | campaigns {r['campaigns']} | caption {r['caption_chars']} chars")
    return "\n".join(lines)


def accounts_text(db: Database) -> str:
    with db.connect() as con:
        rows = con.execute("SELECT * FROM accounts ORDER BY account_key").fetchall()
    lines = ["👥 TELEGRAM ACCOUNTS"]
    for r in rows:
        icon = "🟢" if r["authorized"] else "🔴"
        lines.append(
            f"{icon} {r['account_key'].title()} — {_short(r['identity'] or 'unknown',30)}\n"
            f"ID {r['telegram_user_id'] or '?'} | health {r['health_score']} | cooldown {r['cooldown_until'] or 'none'}"
        )
    return "\n".join(lines)


def queue_text(db: Database) -> str:
    with db.connect() as con:
        rows = con.execute("SELECT status,COUNT(*) n FROM queue GROUP BY status ORDER BY status").fetchall()
        next_rows = con.execute(
            '''SELECT q.id,q.status,q.campaign_id,q.due_at,d.group_name FROM queue q JOIN destinations d ON d.group_id=q.group_id
               WHERE q.status IN ('pending','retry','deferred') ORDER BY q.due_at LIMIT 8'''
        ).fetchall()
    lines = ["📬 QUEUE"] + [f"{r['status']}: {r['n']}" for r in rows]
    if next_rows:
        lines.append("\nNEXT")
        for r in next_rows:
            lines.append(f"#{r['id']} {r['campaign_id']} → {_short(r['group_name'],25)} [{r['status']}]")
    return "\n".join(lines)


def errors_text(db: Database, limit: int = 12) -> str:
    with db.connect() as con:
        rows = con.execute(
            '''SELECT q.id,q.status,q.campaign_id,q.error_kind,q.last_error,d.group_name
               FROM queue q JOIN destinations d ON d.group_id=q.group_id
               WHERE q.status IN ('failed','uncertain','quarantined') ORDER BY q.updated_at DESC LIMIT ?''',
            (limit,),
        ).fetchall()
    if not rows:
        return "✅ No failed/uncertain queue jobs."
    lines = ["⚠️ NEEDS ATTENTION"]
    for r in rows:
        lines.append(f"#{r['id']} {r['status']} | {r['campaign_id']} → {_short(r['group_name'],22)}\n{_short(r['error_kind'] or r['last_error'],70)}")
    return "\n".join(lines)


def review_text(db: Database, limit: int = 12) -> str:
    with db.connect() as con:
        rows = con.execute(
            "SELECT group_id,group_name,primary_access,secondary_access,mode FROM destinations WHERE needs_review=1 ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    if not rows:
        return "✅ No destinations waiting for review."
    lines = ["🆕 DESTINATION REVIEW"]
    for r in rows:
        lines.append(f"{r['group_id']} | {_short(r['group_name'],32)} | P/S {r['primary_access']}/{r['secondary_access']} | {r['mode']}")
    return "\n".join(lines)


def search_destinations_text(db: Database, term: str, limit: int = 12) -> str:
    term = term.strip()
    if not term:
        return "Usage: /find part-of-name"
    with db.connect() as con:
        like = f"%{term}%"
        rows = con.execute(
            '''SELECT group_id,group_name,enabled,needs_review,primary_access,secondary_access,mode
               FROM destinations WHERE group_name LIKE ? OR username LIKE ? OR CAST(group_id AS TEXT)=?
               ORDER BY enabled DESC,group_name LIMIT ?''',
            (like, like, term, limit),
        ).fetchall()
    if not rows:
        return f"No destinations matched: {term}"
    lines = [f"🔎 DESTINATIONS: {term}"]
    for r in rows:
        lines.append(f"{r['group_id']} | {_short(r['group_name'],30)} | {'ON' if r['enabled'] else 'OFF'} | P/S {r['primary_access']}/{r['secondary_access']} | {r['mode']}")
    return "\n".join(lines)


def collections_text(db: Database, limit: int = 15) -> str:
    rows=list_collections(db, enabled_only=False)[:limit]
    if not rows:
        return "No destination collections configured."
    lines=["🧭 DESTINATION COLLECTIONS"]
    for r in rows:
        try: n=collection_preview(db,r["collection_id"])["selected"]
        except Exception: n=0
        lines.append(f"{'🟢' if r['enabled'] else '⚪'} {r['collection_id']} — {_short(r['name'],26)} | {n} destination(s)")
    return "\n".join(lines)


def recommendations_text(db: Database, limit: int = 10) -> str:
    generate_recommendations(db,168)
    rows=list_recommendations(db,'open',limit)
    if not rows:
        return "✅ No open recommendations."
    lines=["💡 RECOMMENDATIONS"]
    for r in rows:
        icon={'CRITICAL':'🚨','IMPORTANT':'⚠️','WARNING':'🟡'}.get(r['severity'],'ℹ️')
        lines.append(f"{icon} {r['recommendation_id']} | {_short(r['title'],55)}")
    return "\n".join(lines)


@dataclass
class WizardState:
    step: str = "campaign_id"
    data: dict = field(default_factory=dict)


class TelegramAdminController:
    """Allowlisted private Telegram operator surface using the production core."""

    def __init__(self, db: Database, settings, safety: SafetyController):
        self.db = db
        self.settings = settings
        self.safety = safety
        self.notifier = NotificationManager(db)
        self.client = None
        self._wizard: dict[int, WizardState] = {}
        self.stop_requested = False
        self.ready_event = asyncio.Event()
        self.startup_error = None

    def role(self, user_id: int | None) -> str | None:
        if not user_id:
            return None
        uid = int(user_id)
        if uid in set(self.settings.admin_user_ids):
            return "control"
        if uid in set(getattr(self.settings, "admin_readonly_user_ids", ())):
            return "readonly"
        return None

    def authorized(self, user_id: int | None) -> bool:
        return self.role(user_id) is not None

    def can_control(self, user_id: int | None) -> bool:
        return self.role(user_id) == "control"

    def _queue_limits(self) -> dict:
        return {
            "max_queue_size": self.settings.max_queue_size,
            "max_pending_per_campaign": self.settings.max_pending_per_campaign,
            "max_pending_per_destination": self.settings.max_pending_per_destination,
        }

    async def _build_client(self):
        from telethon import Button, TelegramClient, events

        # Bot-token sessions do not need a persistent Telethon SQLite session.
        # Memory mode is the unattended default because it avoids stale/locked
        # admin_bot.session files blocking managed service startup.
        session_arg = self.settings.admin_bot_session if getattr(self.settings, "admin_bot_persist_session", False) else None
        client = TelegramClient(
            session_arg,
            self.settings.api_id,
            self.settings.api_hash,
            flood_sleep_threshold=0,
        )
        try:
            await client.start(bot_token=self.settings.admin_bot_token)
        except Exception as exc:
            # Telethon raises AccessTokenInvalidError when BotFather token is
            # revoked, mistyped, or belongs to no current bot.  Keep the
            # operator output concise and never echo the token itself.
            try:
                from telethon.errors import AccessTokenInvalidError
            except Exception:
                AccessTokenInvalidError = ()
            if AccessTokenInvalidError and isinstance(exc, AccessTokenInvalidError):
                try:
                    await client.disconnect()
                except Exception:
                    pass
                raise RuntimeError(
                    "ADMIN_BOT_TOKEN was rejected by Telegram. Generate a fresh token in @BotFather, "
                    "save it in this bot's .env, then retry option 53."
                ) from exc
            raise
        self.client = client

        @client.on(events.NewMessage)
        async def on_message(event):
            sender = int(event.sender_id or 0)
            if not self.authorized(sender):
                if event.is_private:
                    await event.respond("Access denied.")
                return
            text = (event.raw_text or "").strip()
            if sender in self._wizard and not text.startswith("/"):
                await self._wizard_input(event, text)
                return
            parts = text.split(maxsplit=2)
            cmd = parts[0].lower() if parts else ""
            control_commands = {"/clone", "/pause", "/resume", "/newcampaign"}
            if cmd in control_commands and not self.can_control(sender):
                await event.respond("Read-only access: this action requires a control admin.")
                return
            if cmd in {"/start", "/status", "/dashboard"}:
                await event.respond(dashboard_text(self.db), buttons=self._home_buttons(Button))
            elif cmd == "/campaigns":
                await event.respond(campaigns_text(self.db), buttons=self._campaign_buttons(Button))
            elif cmd == "/content":
                await event.respond(content_text(self.db), buttons=self._content_buttons(Button))
            elif cmd == "/accounts":
                await event.respond(accounts_text(self.db), buttons=self._home_buttons(Button))
            elif cmd == "/queue":
                await event.respond(queue_text(self.db), buttons=self._queue_buttons(Button))
            elif cmd == "/errors":
                await event.respond(errors_text(self.db), buttons=self._error_buttons(Button))
            elif cmd == "/review":
                await event.respond(review_text(self.db), buttons=self._review_buttons(Button))
            elif cmd == "/collections":
                await event.respond(collections_text(self.db), buttons=self._home_buttons(Button))
            elif cmd in {"/recommendations","/recs"}:
                await event.respond(recommendations_text(self.db), buttons=self._recommendation_buttons(Button))
            elif cmd == "/report":
                await event.respond(daily_report_text(self.db), buttons=self._home_buttons(Button))
            elif cmd == "/weekly":
                await event.respond(weekly_report_text(self.db), buttons=self._home_buttons(Button))
            elif cmd == "/find":
                term = text[len("/find"):].strip()
                await event.respond(search_destinations_text(self.db, term), buttons=self._home_buttons(Button))
            elif cmd == "/clone":
                if len(parts) < 3:
                    await event.respond("Usage: /clone source_campaign new_campaign")
                else:
                    source, new_id = parts[1], parts[2].strip().split()[0]
                    clone_campaign(self.db, source, new_id)
                    audit(self.db, f"telegram:{sender}", "campaign_clone", "campaign", new_id, source=source)
                    await event.respond(f"✅ Cloned {source} → {new_id} as DRAFT.", buttons=self._campaign_buttons(Button))
            elif cmd == "/pause":
                self.safety.pause("Telegram admin emergency pause", manual=True)
                audit(self.db, f"telegram:{sender}", "pause_all")
                await event.respond("⏸ Outbound posting paused.", buttons=self._home_buttons(Button))
            elif cmd == "/resume":
                self.safety.resume("Telegram admin resume")
                audit(self.db, f"telegram:{sender}", "resume_all")
                await event.respond("▶️ Outbound posting resumed.", buttons=self._home_buttons(Button))
            elif cmd == "/newcampaign":
                self._wizard[sender] = WizardState()
                await event.respond("Campaign wizard started. Send a short campaign ID (letters/numbers/_). Send /cancel to stop.")
            elif cmd == "/cancel":
                self._wizard.pop(sender, None)
                await event.respond("Cancelled.")
            elif cmd == "/help":
                await event.respond(
                    "/status /campaigns /content /accounts /queue /errors /review /collections /recommendations /report /weekly /find <name> /clone <source> <new> /newcampaign /pause /resume /cancel"
                )
            else:
                await event.respond("Use /status or /help.", buttons=self._home_buttons(Button))

        @client.on(events.CallbackQuery)
        async def on_callback(event):
            sender = int(event.sender_id or 0)
            if not self.authorized(sender):
                await event.answer("Access denied", alert=True)
                return
            data = bytes(event.data or b"").decode("utf-8", "ignore")
            try:
                await self._callback(event, data, Button, sender)
            except Exception as exc:
                self.db.event("ERROR", "admin_callback_error", str(exc)[:800])
                await event.answer(_short(exc, 120), alert=True)

        return client

    @staticmethod
    def _home_buttons(Button):
        return [
            [Button.inline("📣 Campaigns", b"campaigns"), Button.inline("📬 Queue", b"queue")],
            [Button.inline("🗂 Content", b"content"), Button.inline("👥 Accounts", b"accounts")],
            [Button.inline("🆕 Review", b"review"), Button.inline("⚠️ Errors", b"errors")],
            [Button.inline("🧭 Collections", b"collections"), Button.inline("💡 Recommendations", b"recommendations")],
            [Button.inline("⏸ Pause", b"pause"), Button.inline("▶ Resume", b"resume")],
            [Button.inline("🔄 Refresh", b"home")],
        ]

    def _campaign_buttons(self, Button):
        with self.db.connect() as con:
            rows = con.execute("SELECT campaign_id,lifecycle_state FROM campaigns ORDER BY enabled DESC,priority DESC LIMIT 8").fetchall()
        buttons = [[Button.inline(("🟢 " if r["lifecycle_state"] == "active" else "⚪ ") + _short(r["campaign_id"], 35), f"camp:{r['campaign_id']}".encode())] for r in rows]
        buttons.append([Button.inline("🏠 Home", b"home")])
        return buttons

    def _content_buttons(self, Button):
        with self.db.connect() as con:
            rows = con.execute("SELECT content_id,lifecycle_state FROM content ORDER BY enabled DESC,updated_at DESC LIMIT 8").fetchall()
        buttons = [[Button.inline(("🟢 " if r["lifecycle_state"] == "ready" else "⚪ ") + _short(r["content_id"], 35), f"contentitem:{r['content_id']}".encode())] for r in rows]
        buttons.append([Button.inline("🏠 Home", b"home")])
        return buttons

    @staticmethod
    def _queue_buttons(Button):
        return [
            [Button.inline("🔁 Retry failed", b"retry_failed"), Button.inline("⚠️ Errors", b"errors")],
            [Button.inline("🏠 Home", b"home")],
        ]

    def _error_buttons(self, Button):
        with self.db.connect() as con:
            rows = con.execute("SELECT id,status FROM queue WHERE status IN ('failed','uncertain','quarantined') ORDER BY updated_at DESC LIMIT 6").fetchall()
        out = [[Button.inline(f"Job #{r['id']} [{r['status']}]", f"job:{r['id']}".encode())] for r in rows]
        out.append([Button.inline("🔁 Retry failed", b"retry_failed"), Button.inline("🏠 Home", b"home")])
        return out

    def _recommendation_buttons(self, Button):
        rows=list_recommendations(self.db,'open',6)
        out=[[Button.inline(_short(r['title'],28), f"rec:{r['recommendation_id']}".encode())] for r in rows]
        out.append([Button.inline("🏠 Home", b"home")])
        return out

    def _review_buttons(self, Button):
        with self.db.connect() as con:
            rows = con.execute("SELECT group_id,group_name FROM destinations WHERE needs_review=1 ORDER BY updated_at DESC LIMIT 6").fetchall()
        out = [[Button.inline("Review " + _short(r["group_name"], 24), f"dest:{r['group_id']}".encode())] for r in rows]
        out.append([Button.inline("🏠 Home", b"home")])
        return out

    async def _callback(self, event, data: str, Button, sender: int):
        actor = f"telegram:{sender}"
        mutation_prefixes = ("pause", "resume", "retry_failed", "campact:", "camppause:", "camparchive:", "camppost:",
                             "contentready:", "contentdisable:", "contentarchive:", "jobretry:", "jobcancel:", "jobdefer:",
                             "destapprove:", "destnever:", "destprotect:", "recapply:", "recdismiss:")
        if data.startswith(mutation_prefixes) and not self.can_control(sender):
            await event.answer("Read-only access", alert=True)
            return
        if data == "home":
            await event.edit(dashboard_text(self.db), buttons=self._home_buttons(Button))
        elif data == "campaigns":
            await event.edit(campaigns_text(self.db), buttons=self._campaign_buttons(Button))
        elif data == "content":
            await event.edit(content_text(self.db), buttons=self._content_buttons(Button))
        elif data == "accounts":
            await event.edit(accounts_text(self.db), buttons=self._home_buttons(Button))
        elif data == "queue":
            await event.edit(queue_text(self.db), buttons=self._queue_buttons(Button))
        elif data == "errors":
            await event.edit(errors_text(self.db), buttons=self._error_buttons(Button))
        elif data == "review":
            await event.edit(review_text(self.db), buttons=self._review_buttons(Button))
        elif data == "collections":
            await event.edit(collections_text(self.db), buttons=self._home_buttons(Button))
        elif data == "recommendations":
            await event.edit(recommendations_text(self.db), buttons=self._recommendation_buttons(Button))
        elif data == "pause":
            self.safety.pause("Telegram admin emergency pause", manual=True)
            audit(self.db, actor, "pause_all")
            await event.edit("⏸ Outbound posting paused.", buttons=self._home_buttons(Button))
        elif data == "resume":
            self.safety.resume("Telegram admin resume")
            audit(self.db, actor, "resume_all")
            await event.edit("▶️ Outbound posting resumed.", buttons=self._home_buttons(Button))
        elif data == "retry_failed":
            with self.db.connect() as con:
                cur = con.execute(
                    "UPDATE queue SET status='retry',due_at=?,last_error='Telegram admin bulk retry',error_kind=NULL,resolved_at=NULL,updated_at=? WHERE status='failed'",
                    (utcnow(), utcnow()),
                )
                n = cur.rowcount
            audit(self.db, actor, "retry_failed", jobs=n)
            await event.edit(f"🔁 Retried {n} failed job(s).", buttons=self._queue_buttons(Button))
        elif data.startswith("camp:"):
            cid = data.split(":", 1)[1]
            preview = campaign_preview(self.db, cid)
            mark_campaign_previewed(self.db, cid, actor=actor)
            with self.db.connect() as con:
                c = con.execute("SELECT lifecycle_state,start_at,end_at,category,target_collections,max_cycles,completed_cycles FROM campaigns WHERE campaign_id=?", (cid,)).fetchone()
            state = c["lifecycle_state"] if c else "?"
            text = (
                f"📣 {cid}\nState: {state}\nVariants: {preview['variant_count']}\nDestinations: {preview['selected']}\n"
                f"Rotation: {preview['rotation_mode']}\nCategory: {c['category'] or '-'}\nCollections: {c['target_collections'] or '-'}\nCycles: {c['completed_cycles']}/{c['max_cycles'] or '∞'}\nSkipped: {preview['skipped']}\nStart: {c['start_at'] or 'now'}\nEnd: {c['end_at'] or 'none'}"
            )
            buttons = [
                [Button.inline("▶ Activate", f"campact:{cid}".encode()), Button.inline("⏸ Pause", f"camppause:{cid}".encode())],
                [Button.inline("🚀 Post Now", f"camppost:{cid}".encode()), Button.inline("🗄 Archive", f"camparchive:{cid}".encode())],
                [Button.inline("⬅ Campaigns", b"campaigns")],
            ]
            await event.edit(text, buttons=buttons)
        elif data.startswith("campact:"):
            cid = data.split(":", 1)[1]
            set_campaign_state(self.db, cid, "active", actor=actor)
            await event.answer("Campaign active")
            await event.edit(campaigns_text(self.db), buttons=self._campaign_buttons(Button))
        elif data.startswith("camppause:"):
            cid = data.split(":", 1)[1]
            set_campaign_state(self.db, cid, "paused", actor=actor)
            await event.answer("Campaign paused")
            await event.edit(campaigns_text(self.db), buttons=self._campaign_buttons(Button))
        elif data.startswith("camparchive:"):
            cid = data.split(":", 1)[1]
            set_campaign_state(self.db, cid, "archived", actor=actor)
            await event.answer("Campaign archived")
            await event.edit(campaigns_text(self.db), buttons=self._campaign_buttons(Button))
        elif data.startswith("camppost:"):
            cid = data.split(":", 1)[1]
            result = enqueue_campaign(
                self.db,
                cid,
                run_key=f"telegram-post-now:{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
                limits=self._queue_limits(),
            )
            audit(self.db, actor, "post_now", "campaign", cid, inserted=result["inserted"])
            await event.edit(f"🚀 Queued {result['inserted']} job(s) for {cid}.", buttons=self._home_buttons(Button))
        elif data.startswith("contentitem:"):
            cid = data.split(":", 1)[1]
            with self.db.connect() as con:
                row = con.execute("SELECT * FROM content WHERE content_id=?", (cid,)).fetchone()
                tags = [r[0] for r in con.execute("SELECT tag FROM content_tags WHERE content_id=? ORDER BY tag", (cid,)).fetchall()]
            if not row:
                raise RuntimeError("Content not found")
            text = f"🗂 {cid}\nState: {row['lifecycle_state']}\nCaption: {_short(row['caption'],180)}\nTags: {', '.join(tags) or '-'}"
            buttons = [
                [Button.inline("✅ Ready", f"contentready:{cid}".encode()), Button.inline("⏸ Disable", f"contentdisable:{cid}".encode())],
                [Button.inline("🗄 Archive", f"contentarchive:{cid}".encode()), Button.inline("⬅ Content", b"content")],
            ]
            await event.edit(text, buttons=buttons)
        elif data.startswith("contentready:"):
            cid = data.split(":",1)[1]
            set_content_state(self.db, cid, "ready", actor=actor)
            await event.edit(content_text(self.db), buttons=self._content_buttons(Button))
        elif data.startswith("contentdisable:"):
            cid = data.split(":",1)[1]
            set_content_state(self.db, cid, "disabled", actor=actor)
            await event.edit(content_text(self.db), buttons=self._content_buttons(Button))
        elif data.startswith("contentarchive:"):
            cid = data.split(":",1)[1]
            set_content_state(self.db, cid, "archived", actor=actor)
            await event.edit(content_text(self.db), buttons=self._content_buttons(Button))
        elif data.startswith("job:"):
            jid = int(data.split(":",1)[1])
            with self.db.connect() as con:
                r = con.execute('''SELECT q.*,d.group_name FROM queue q LEFT JOIN destinations d ON d.group_id=q.group_id WHERE q.id=?''',(jid,)).fetchone()
            if not r:
                raise RuntimeError("Queue job not found")
            text = f"📬 Job #{jid}\nStatus: {r['status']}\nCampaign: {r['campaign_id']}\nDestination: {_short(r['group_name'],40)}\nAccount: {r['account_key'] or 'auto'}\nContent: {r['content_id'] or '-'}\nError: {_short(r['last_error'],180)}"
            await event.edit(text, buttons=[
                [Button.inline("🔁 Retry", f"jobretry:{jid}".encode()), Button.inline("❌ Cancel", f"jobcancel:{jid}".encode())],
                [Button.inline("⏰ +30m", f"jobdefer:{jid}".encode()), Button.inline("⬅ Errors", b"errors")],
            ])
        elif data.startswith("jobretry:"):
            jid = int(data.split(":",1)[1]); manage_job(self.db,jid,"retry",actor=actor)
            await event.answer("Retry queued"); await event.edit(errors_text(self.db),buttons=self._error_buttons(Button))
        elif data.startswith("jobcancel:"):
            jid = int(data.split(":",1)[1]); manage_job(self.db,jid,"cancel",actor=actor)
            await event.answer("Cancelled"); await event.edit(errors_text(self.db),buttons=self._error_buttons(Button))
        elif data.startswith("jobdefer:"):
            jid = int(data.split(":",1)[1]); manage_job(self.db,jid,"defer",actor=actor,minutes=30)
            await event.answer("Deferred 30 minutes"); await event.edit(queue_text(self.db),buttons=self._queue_buttons(Button))
        elif data.startswith("rec:"):
            rid=data.split(":",1)[1]
            rows=[r for r in list_recommendations(self.db,'open',200) if r['recommendation_id']==rid]
            if not rows: raise RuntimeError("Recommendation not found")
            r=rows[0]
            text=f"💡 {r['title']}\nSeverity: {r['severity']}\n\n{_short(r['message'],800)}\n\nSuggested: {r['suggested_action']}"
            await event.edit(text,buttons=[[Button.inline("✅ Apply safe action",f"recapply:{rid}".encode()),Button.inline("Dismiss",f"recdismiss:{rid}".encode())],[Button.inline("⬅ Recommendations",b"recommendations")]])
        elif data.startswith("recapply:"):
            rid=data.split(":",1)[1]
            apply_recommendation(self.db,rid,actor=actor)
            await event.answer("Recommendation applied")
            await event.edit(recommendations_text(self.db),buttons=self._recommendation_buttons(Button))
        elif data.startswith("recdismiss:"):
            rid=data.split(":",1)[1]
            dismiss_recommendation(self.db,rid)
            audit(self.db,actor,"recommendation_dismiss","recommendation",rid)
            await event.answer("Dismissed")
            await event.edit(recommendations_text(self.db),buttons=self._recommendation_buttons(Button))
        elif data.startswith("dest:"):
            gid = int(data.split(":", 1)[1])
            with self.db.connect() as con:
                d = con.execute("SELECT * FROM destinations WHERE group_id=?", (gid,)).fetchone()
            if not d:
                raise RuntimeError("Destination no longer exists")
            text = f"🆕 {_short(d['group_name'],45)}\nID: {gid}\nP/S: {d['primary_access']}/{d['secondary_access']}\nMode: {d['mode']}\nReview: {d['needs_review']}\nEnabled: {d['enabled']}\nProtected: {d['protected']}\nNever auto: {d['never_auto_post']}"
            await event.edit(text, buttons=[
                [Button.inline("✅ Approve", f"destapprove:{gid}".encode()), Button.inline("⛔ Never Auto", f"destnever:{gid}".encode())],
                [Button.inline("🛡 Protect", f"destprotect:{gid}".encode()), Button.inline("⬅ Review", b"review")],
            ])
        elif data.startswith("destapprove:"):
            gid = int(data.split(":", 1)[1])
            with self.db.connect() as con:
                d = con.execute("SELECT mode FROM destinations WHERE group_id=?", (gid,)).fetchone()
                if not d:
                    raise RuntimeError("Destination not found")
                enable = 1 if d["mode"] in {"photo", "text"} else 0
                con.execute("UPDATE destinations SET needs_review=0,enabled=?,updated_at=? WHERE group_id=?", (enable, utcnow(), gid))
            audit(self.db, actor, "destination_approve", "destination", str(gid), enabled=bool(enable))
            await event.answer("Approved")
            await event.edit(review_text(self.db), buttons=self._review_buttons(Button))
        elif data.startswith("destnever:"):
            gid = int(data.split(":", 1)[1])
            with self.db.connect() as con:
                con.execute("UPDATE destinations SET never_auto_post=1,enabled=0,needs_review=0,updated_at=? WHERE group_id=?", (utcnow(), gid))
            audit(self.db, actor, "destination_never_auto", "destination", str(gid))
            await event.answer("Blocked from auto-posting")
            await event.edit(review_text(self.db), buttons=self._review_buttons(Button))
        elif data.startswith("destprotect:"):
            gid = int(data.split(":", 1)[1])
            with self.db.connect() as con:
                con.execute("UPDATE destinations SET protected=1,updated_at=? WHERE group_id=?", (utcnow(), gid))
            audit(self.db, actor, "destination_protect", "destination", str(gid))
            await event.answer("Protected")
            await event.edit(review_text(self.db), buttons=self._review_buttons(Button))
        else:
            await event.answer("Unknown action", alert=True)

    async def _wizard_input(self, event, text: str):
        sender = int(event.sender_id)
        state = self._wizard[sender]
        d = state.data
        try:
            if state.step == "campaign_id":
                cid = text.lower().replace(" ", "_")
                if not cid.replace("_", "").replace("-", "").isalnum():
                    raise ValueError("Use letters/numbers/_/- only")
                d["campaign_id"] = cid
                state.step = "name"
                await event.respond("Campaign name?")
            elif state.step == "name":
                d["name"] = text
                state.step = "content"
                await event.respond("Content IDs, comma-separated?")
            elif state.step == "content":
                ids = [x.strip() for x in text.split(",") if x.strip()]
                with self.db.connect() as con:
                    missing = [x for x in ids if not con.execute("SELECT 1 FROM content WHERE content_id=? AND enabled=1", (x,)).fetchone()]
                if not ids or missing:
                    raise ValueError("Unknown/disabled content: " + ", ".join(missing or ["none supplied"]))
                d["content"] = ids
                state.step = "include"
                await event.respond("Destination INCLUDE tags, comma-separated (example main_groups)?")
            elif state.step == "include":
                d["include"] = text
                state.step = "exclude"
                await event.respond("EXCLUDE tags, or '-' for none?")
            elif state.step == "exclude":
                d["exclude"] = "" if text == "-" else text
                state.step = "collections"
                await event.respond("Destination collections, comma-separated, or '-' for none?")
            elif state.step == "collections":
                d["collections"] = "" if text == "-" else text
                state.step = "category"
                await event.respond("Campaign category, or '-' for none?")
            elif state.step == "category":
                d["category"] = "" if text == "-" else text
                state.step = "max_cycles"
                await event.respond("Maximum cycles? Use 0 for unlimited.")
            elif state.step == "max_cycles":
                d["max_cycles"] = max(0, int(text))
                state.step = "rotation"
                await event.respond("Rotation: sequential / random / least_recent / weighted")
            elif state.step == "rotation":
                if text not in {"sequential", "random", "least_recent", "weighted"}:
                    raise ValueError("Invalid rotation")
                d["rotation"] = text
                state.step = "schedule"
                await event.respond("Schedule: manual OR every:360 (minutes) OR daily:09:00,18:00 OR once:2026-09-01T19:00")
            elif state.step == "schedule":
                d["schedule"] = text.lower()
                state.step = "window"
                await event.respond("Active date window as start,end ISO timestamps, or '-' for no window?")
            elif state.step == "window":
                if text == "-":
                    d["start_at"] = d["end_at"] = None
                else:
                    bits = [x.strip() for x in text.split(",", 1)]
                    if len(bits) != 2:
                        raise ValueError("Use start,end or -")
                    # Validate ISO values now; core still preserves the exact values.
                    for raw in bits:
                        datetime.fromisoformat(raw)
                    d["start_at"], d["end_at"] = bits
                state.step = "spread"
                await event.respond("Spread each run across how many minutes? Use 0 for no spread.")
            elif state.step == "spread":
                d["spread"] = max(0, int(float(text)))
                state.step = "confirm"
                await event.respond(f"Create campaign {d['campaign_id']} with {len(d['content'])} variants targeting [{d['include']}]? Reply CREATE or /cancel")
            elif state.step == "confirm":
                if text.upper() != "CREATE":
                    raise ValueError("Reply CREATE or /cancel")
                cid = d["campaign_id"]
                create_campaign(
                    self.db,
                    cid,
                    d["name"],
                    d["content"][0],
                    tags=d["include"],
                    exclude_tags=d["exclude"],
                    rotation_mode=d["rotation"],
                    conflict_gap_seconds=3600,
                    spread_seconds=d["spread"] * 60,
                    start_at=d.get("start_at"),
                    end_at=d.get("end_at"),
                    category=d.get("category", ""),
                    target_collections=d.get("collections", ""),
                    max_cycles=d.get("max_cycles", 0),
                )
                for pos, content_id in enumerate(d["content"]):
                    add_campaign_content(self.db, cid, content_id, position=pos)
                sched = d["schedule"]
                if sched.startswith("every:"):
                    configure_interval(self.db, cid, int(float(sched.split(":", 1)[1]) * 60), self.settings.timezone)
                elif sched.startswith("daily:"):
                    configure_daily(self.db, cid, [x.strip() for x in sched.split(":", 1)[1].split(",") if x.strip()], None, self.settings.timezone)
                elif sched.startswith("once:"):
                    configure_once(self.db, cid, sched.split(":", 1)[1], self.settings.timezone)
                elif sched != "manual":
                    raise ValueError("Unknown schedule format")
                preview = campaign_preview(self.db, cid)
                mark_campaign_previewed(self.db, cid, actor=f"telegram:{sender}")
                audit(self.db, f"telegram:{sender}", "campaign_create", "campaign", cid, preview=preview)
                self._wizard.pop(sender, None)
                await event.respond(f"✅ Saved as READY. Destinations: {preview['selected']}; variants: {preview['variant_count']}. Activate from /campaigns after reviewing.")
        except Exception as exc:
            await event.respond(f"⚠️ {exc}\nTry again or /cancel.")

    async def _notification_loop(self):
        while not self.stop_requested:
            self.db.heartbeat("admin_bot", "ok", "notification loop active")
            if self.client:
                for item in self.notifier.pending(self.settings.admin_notifications_min_severity, limit=10):
                    try:
                        text = f"{'🚨' if item.severity == 'CRITICAL' else '⚠️'} {item.title}\n\n{item.message}"
                        for uid in self.settings.admin_user_ids:
                            await self.client.send_message(uid, text)
                        self.notifier.mark_sent(item.id)
                    except Exception as exc:
                        self.notifier.mark_error(item.id, str(exc))
            await asyncio.sleep(10)

    async def run(self):
        if not self.settings.admin_bot_enabled:
            self.ready_event.set()
            return
        notification_task = None
        client = None
        try:
            client = await self._build_client()
            self.db.event("INFO", "admin_bot_started", "Telegram admin control bot started")
            self.db.heartbeat("admin_bot", "ok", "Telegram admin control bot connected")
            self.ready_event.set()
            notification_task = asyncio.create_task(self._notification_loop())
            await client.run_until_disconnected()
        except BaseException as exc:
            self.startup_error = exc
            self.ready_event.set()
            raise
        finally:
            self.stop_requested = True
            if notification_task:
                notification_task.cancel()
                try:
                    await notification_task
                except BaseException:
                    pass
            if client:
                try:
                    await client.disconnect()
                except BaseException:
                    pass
            if self.db:
                self.db.heartbeat("admin_bot", "stopped", "Telegram admin control bot disconnected")

    async def start_background(self):
        if not self.settings.admin_bot_enabled:
            return None
        return asyncio.create_task(self.run(), name="telegram-admin-bot")

    async def wait_until_ready(self, timeout_seconds: float = 30.0):
        try:
            await asyncio.wait_for(self.ready_event.wait(), timeout=max(1.0, float(timeout_seconds)))
        except asyncio.TimeoutError as exc:
            raise RuntimeError("Telegram admin bot did not become ready before startup timeout") from exc
        if self.startup_error is not None:
            raise RuntimeError(f"Telegram admin bot startup failed: {self.startup_error}") from self.startup_error
        return True
