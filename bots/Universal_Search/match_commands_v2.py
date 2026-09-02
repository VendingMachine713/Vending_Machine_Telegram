import html

from telegram.ext import CommandHandler

from match_engine_v2_runtime import HardenedMatchEngineV2
from match_ui import format_match
from match_ui_v2 import format_demand_stats


FEEDBACK_ALIASES = {
    "good": "relevant",
    "relevant": "relevant",
    "bad": "not_relevant",
    "not_relevant": "not_relevant",
    "wrong": "not_relevant",
    "accepted": "accepted",
    "accept": "accepted",
    "ignore": "ignore",
}


class MatchCommandsV2:
    def __init__(self, db_path, is_admin):
        self.engine = HardenedMatchEngineV2(db_path)
        self.is_admin = is_admin

    async def _require_admin(self, update):
        if self.is_admin(update):
            return True
        if update.effective_message:
            await update.effective_message.reply_text("Match intelligence is available to the claimed admin only.")
        return False

    async def matches(self, update, context):
        if not await self._require_admin(update):
            return
        min_score = 45.0
        limit = 10
        if context.args:
            try:
                min_score = max(0.0, min(float(context.args[0]), 100.0))
            except ValueError:
                pass
        if len(context.args) > 1:
            try:
                limit = max(1, min(int(context.args[1]), 15))
            except ValueError:
                pass
        rows = self.engine.list_matches(min_score=min_score, limit=limit)
        if not rows:
            await update.effective_message.reply_text("No active demand/supply matches at that score.")
            return
        blocks = [format_match(row, include_reasons=False) for row in rows]
        heading = f"<b>Marketplace matches — score ≥ {min_score:.0f}</b>"
        text = heading + "\n\n" + "\n\n".join(blocks)
        if len(text) > 3900:
            kept = []
            for block in blocks:
                candidate = heading + "\n\n" + "\n\n".join(kept + [block])
                if len(candidate) > 3700:
                    break
                kept.append(block)
            text = heading + "\n\n" + "\n\n".join(kept) + "\n\n<i>List shortened by Telegram limits.</i>"
        await update.effective_message.reply_text(
            text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

    async def match(self, update, context):
        if not await self._require_admin(update):
            return
        if not context.args or not context.args[0].isdigit():
            await update.effective_message.reply_text("Use /match ID")
            return
        row = self.engine.get_match(int(context.args[0]))
        if not row:
            await update.effective_message.reply_text("Match not found.")
            return
        await update.effective_message.reply_text(
            format_match(row, include_reasons=True),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

    async def feedback(self, update, context):
        if not await self._require_admin(update):
            return
        if len(context.args) < 2 or not context.args[0].isdigit():
            await update.effective_message.reply_text(
                "Use /matchfeedback ID good|bad|accepted|ignore [optional note]"
            )
            return
        match_id = int(context.args[0])
        supplied = context.args[1].strip().lower()
        verdict = FEEDBACK_ALIASES.get(supplied)
        if not verdict:
            await update.effective_message.reply_text(
                "Feedback must be good, bad, accepted, or ignore."
            )
            return
        note = " ".join(context.args[2:]).strip()[:500] or None
        user_id = update.effective_user.id if update.effective_user else 0
        if not self.engine.record_feedback(match_id, user_id, verdict, note):
            await update.effective_message.reply_text("Match not found.")
            return
        calibration = self.engine.calibration_summary()
        label = {
            "relevant": "good/relevant",
            "not_relevant": "bad/not relevant",
            "accepted": "accepted",
            "ignore": "ignored",
        }[verdict]
        await update.effective_message.reply_text(
            f"✅ Match #{match_id} marked {label}.\n"
            f"Feedback samples: {calibration['labelled']}. "
            f"Advisory threshold: {calibration['recommended_threshold']:.0f}."
        )

    async def demand_stats(self, update, context):
        if not await self._require_admin(update):
            return
        stats = self.engine.demand_stats(alert_threshold=65.0)
        await update.effective_message.reply_text(
            format_demand_stats(stats),
            parse_mode="HTML",
        )

    async def match_alerts(self, update, context):
        if not await self._require_admin(update):
            return
        match_queue = self.engine.queue_status()
        stats = self.engine.demand_stats()
        reminder_queue = stats["expiry_alert_queue"]
        lines = [
            "Match Engine v2:",
            f"event backlog={stats['event_backlog']}",
            "match alerts: " + (" ".join(f"{k}={v}" for k, v in sorted(match_queue.items())) or "empty"),
            "WTB reminders: " + (" ".join(f"{k}={v}" for k, v in sorted(reminder_queue.items())) or "empty"),
            f"notifications={'on' if self.engine.notifications_enabled() else 'off'}",
        ]
        await update.effective_message.reply_text("\n".join(lines))


def register_match_commands_v2(app, db_path, is_admin):
    controller = MatchCommandsV2(db_path, is_admin)
    app.add_handler(CommandHandler("matches", controller.matches))
    app.add_handler(CommandHandler("match", controller.match))
    app.add_handler(CommandHandler("matchfeedback", controller.feedback))
    app.add_handler(CommandHandler("demandstats", controller.demand_stats))
    app.add_handler(CommandHandler("matchalerts", controller.match_alerts))
    return controller
