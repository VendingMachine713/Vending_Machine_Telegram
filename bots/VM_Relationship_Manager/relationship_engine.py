from __future__ import annotations

from datetime import datetime, timezone, timedelta
from statistics import median
import math
from typing import Optional

from database import Database, utcnow
from behavior_engine import BehaviorEngine
from network_engine import NetworkEngine
from opportunity_engine import OpportunityEngine
from automation_engine import AutomationEngine
from privacy_engine import PrivacyEngine
from integration_engine import IntegrationEngine
from query_engine import QueryEngine
from priority_engine import PriorityEngine
from memory_engine import MemoryEngine
from group_engine import GroupEngine
from risk_engine import RiskEngine
from reporting_engine import ReportingEngine
from goal_engine import GoalEngine
from segment_engine import SegmentEngine
from session_engine import SessionEngine
from forecast_engine import ForecastEngine
from data_quality_engine import DataQualityEngine
from playbook_engine import PlaybookEngine
from briefing_engine import BriefingEngine
from classification_engine import ClassificationEngine
from action_engine import ActionEngine
from autonomy_engine import AutonomyEngine
from calibration_engine import CalibrationEngine
from exception_policy_engine import ExceptionPolicyEngine
from operations_engine import OperationsEngine


RELATIONSHIP_TYPES = {
    "unknown", "prospect", "customer", "regular", "vip", "supplier",
    "vendor", "partner", "admin", "group_owner"
}
VERIFICATION_STATES = {"unknown", "pending", "verified", "trusted", "restricted"}


class RelationshipEngine:
    def __init__(self, db: Database):
        self.db = db
        self.behavior = BehaviorEngine(db)
        self.network = NetworkEngine(db)
        self.opportunities = OpportunityEngine(db)
        self.automation = AutomationEngine(db)
        self.privacy = PrivacyEngine(db)
        self.integration = IntegrationEngine(db)
        self.query = QueryEngine(db)
        self.priority = PriorityEngine(db)
        self.memory = MemoryEngine(db)
        self.groups = GroupEngine(db)
        self.risk = RiskEngine(db)
        self.reporting = ReportingEngine(db)
        self.goals = GoalEngine(db)
        self.segments = SegmentEngine(db)
        self.sessions = SessionEngine(db)
        self.forecast = ForecastEngine(db)
        self.quality = DataQualityEngine(db)
        self.playbooks = PlaybookEngine(db)
        self.exception_policy = ExceptionPolicyEngine(db)
        self.briefing = BriefingEngine(db, self.exception_policy)
        self.autonomy = AutonomyEngine(db)
        self.calibration = CalibrationEngine(db, self.integration)
        self.classification = ClassificationEngine(db, self.integration, self.calibration)
        self.actions = ActionEngine(db, self.integration)
        self.operations = OperationsEngine(db, integration=self.integration)

    def upsert_identity(
        self,
        telegram_id: int,
        username: Optional[str],
        display_name: Optional[str],
        observed_at: Optional[datetime] = None,
        chat_id: Optional[int] = None,
        chat_title: Optional[str] = None,
        source: str = "telegram_lookup",
    ):
        """Create/update a contact identity without inventing an interaction count."""
        if self.privacy.is_excluded(telegram_id):
            return self.db.one("SELECT * FROM contacts WHERE telegram_id=?", (telegram_id,))
        observed_at = observed_at or datetime.now(timezone.utc)
        observed_iso = observed_at.astimezone(timezone.utc).isoformat()
        existing = self.db.one("SELECT * FROM contacts WHERE telegram_id=?", (telegram_id,))

        if not existing:
            self.db.execute(
                """INSERT INTO contacts
                   (telegram_id, username, display_name, first_seen, last_seen,
                    interaction_count, active_days, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, 0, 0, ?, ?)""",
                (
                    telegram_id, username, display_name,
                    observed_iso, observed_iso, utcnow(), utcnow()
                ),
            )
            self.event(telegram_id, "identity_seeded", source)
        else:
            if existing["username"] != username or existing["display_name"] != display_name:
                self.db.execute(
                    """INSERT INTO identity_history
                       (telegram_id, username, display_name, changed_at)
                       VALUES (?, ?, ?, ?)""",
                    (
                        telegram_id,
                        existing["username"],
                        existing["display_name"],
                        utcnow(),
                    ),
                )
                self.event(
                    telegram_id,
                    "identity_changed",
                    f"{existing['username'] or '-'} -> {username or '-'}",
                )

            # Preserve both ends of the observable history window: bootstrap may
            # discover activity older than the first direct lookup, while live
            # monitoring moves last_seen forward.
            observed_utc = observed_at.astimezone(timezone.utc)
            current_first = datetime.fromisoformat(existing["first_seen"])
            current_last = datetime.fromisoformat(existing["last_seen"])
            oldest = min(current_first, observed_utc)
            newest = max(current_last, observed_utc)
            self.db.execute(
                """UPDATE contacts
                   SET username=?, display_name=?, first_seen=?, last_seen=?, updated_at=?
                   WHERE telegram_id=?""",
                (
                    username,
                    display_name,
                    oldest.isoformat(),
                    newest.isoformat(),
                    utcnow(),
                    telegram_id,
                ),
            )

        if chat_id is not None:
            row = self.db.one(
                "SELECT 1 FROM contact_groups WHERE telegram_id=? AND chat_id=?",
                (telegram_id, chat_id),
            )
            if not row:
                self.db.execute(
                    """INSERT INTO contact_groups
                       (telegram_id, chat_id, chat_title, first_seen, last_seen, interaction_count)
                       VALUES (?, ?, ?, ?, ?, 0)""",
                    (
                        telegram_id, chat_id, chat_title,
                        observed_iso, observed_iso
                    ),
                )
            else:
                self.db.execute(
                    """UPDATE contact_groups
                       SET chat_title=?,
                           last_seen=CASE WHEN last_seen < ? THEN ? ELSE last_seen END
                       WHERE telegram_id=? AND chat_id=?""",
                    (
                        chat_title, observed_iso, observed_iso,
                        telegram_id, chat_id
                    ),
                )

        return self.db.one("SELECT * FROM contacts WHERE telegram_id=?", (telegram_id,))

    def upsert_interaction(
        self,
        telegram_id: int,
        username: Optional[str],
        display_name: Optional[str],
        chat_id: Optional[int],
        chat_title: Optional[str],
        occurred_at: datetime,
    ):
        if self.privacy.is_excluded(telegram_id):
            return
        now = occurred_at.astimezone(timezone.utc).isoformat()
        today = occurred_at.astimezone(timezone.utc).date().isoformat()
        existing = self.db.one("SELECT * FROM contacts WHERE telegram_id=?", (telegram_id,))

        if not existing:
            self.db.execute(
                """INSERT INTO contacts
                   (telegram_id, username, display_name, first_seen, last_seen,
                    interaction_count, active_days, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, 1, 1, ?, ?)""",
                (telegram_id, username, display_name, now, now, now, now),
            )
            self.event(telegram_id, "first_seen", f"First observed in {chat_title or chat_id}")
        else:
            if existing["username"] != username or existing["display_name"] != display_name:
                self.db.execute(
                    """INSERT INTO identity_history
                       (telegram_id, username, display_name, changed_at)
                       VALUES (?, ?, ?, ?)""",
                    (telegram_id, existing["username"], existing["display_name"], utcnow()),
                )
                self.event(
                    telegram_id,
                    "identity_changed",
                    f"{existing['username'] or '-'} -> {username or '-'}",
                )

            active_today = self.db.one(
                """SELECT 1 FROM daily_activity
                   WHERE telegram_id=? AND activity_date=?""",
                (telegram_id, today),
            )
            active_day_increment = 0 if active_today else 1
            self.db.execute(
                """UPDATE contacts
                   SET username=?, display_name=?, last_seen=?,
                       interaction_count=interaction_count+1,
                       active_days=active_days+?,
                       updated_at=?
                   WHERE telegram_id=?""",
                (username, display_name, now, active_day_increment, utcnow(), telegram_id),
            )

        self.db.execute(
            """INSERT INTO daily_activity (telegram_id, activity_date, interaction_count)
               VALUES (?, ?, 1)
               ON CONFLICT(telegram_id, activity_date)
               DO UPDATE SET interaction_count=interaction_count+1""",
            (telegram_id, today),
        )

        if chat_id is not None:
            self.db.execute(
                """INSERT INTO group_daily_activity(chat_id,activity_date,interaction_count)
                   VALUES (?,?,1)
                   ON CONFLICT(chat_id,activity_date) DO UPDATE SET interaction_count=interaction_count+1""",
                (chat_id,today),
            )
            row = self.db.one(
                "SELECT 1 FROM contact_groups WHERE telegram_id=? AND chat_id=?",
                (telegram_id, chat_id),
            )
            if not row:
                self.db.execute(
                    """INSERT INTO contact_groups
                       (telegram_id, chat_id, chat_title, first_seen, last_seen, interaction_count)
                       VALUES (?, ?, ?, ?, ?, 1)""",
                    (telegram_id, chat_id, chat_title, now, now),
                )
                self.event(telegram_id, "new_group_seen", chat_title or str(chat_id))
            else:
                self.db.execute(
                    """UPDATE contact_groups
                       SET chat_title=?, last_seen=?, interaction_count=interaction_count+1
                       WHERE telegram_id=? AND chat_id=?""",
                    (chat_title, now, telegram_id, chat_id),
                )

        # Keep scores reasonably fresh without performing the full scoring query
        # for every message in busy groups. Recalculate on first/new active day
        # and every fifth observed interaction. Profiles always force a fresh
        # recalculation when opened.
        refreshed = self.db.one(
            "SELECT interaction_count, active_days FROM contacts WHERE telegram_id=?",
            (telegram_id,),
        )
        if refreshed and (
            refreshed["interaction_count"] <= 1
            or refreshed["interaction_count"] % 5 == 0
            or (existing is not None and active_day_increment == 1)
        ):
            self.recalculate_contact(telegram_id)

    def record_private_interaction(self, telegram_id: int, chat_id: int, message_id: int, direction: str, occurred_at: datetime):
        if self.privacy.is_excluded(telegram_id):
            return
        self.behavior.record(telegram_id, chat_id, message_id, direction, occurred_at)

    def get_behavior(self, telegram_id: int, refresh: bool = False):
        return self.behavior.get(telegram_id, refresh=refresh)

    def recalculate_behavior_all(self):
        self.behavior.compute_all()

    def get_network(self, telegram_id: int, refresh: bool = False):
        return self.network.get(telegram_id, refresh=refresh)

    def recalculate_network_all(self):
        self.network.compute_all()

    def event(self, telegram_id: int, event_type: str, details: str | None = None):
        self.db.execute(
            """INSERT INTO relationship_events
               (telegram_id, event_type, details, created_at)
               VALUES (?, ?, ?, ?)""",
            (telegram_id, event_type, details, utcnow()),
        )
        self.integration.emit(event_type, telegram_id, {"details": details} if details else {})

    def add_note(self, telegram_id: int, author_id: int, note: str):
        self.db.execute(
            "INSERT INTO notes (telegram_id, author_id, note, created_at) VALUES (?, ?, ?, ?)",
            (telegram_id, author_id, note, utcnow()),
        )
        self.audit(author_id, "add_note", telegram_id, note[:120])

    def add_tag(self, telegram_id: int, tag: str):
        tag = tag.strip().lower()
        if not tag:
            return
        self.db.execute(
            "INSERT OR IGNORE INTO tags (telegram_id, tag, created_at) VALUES (?, ?, ?)",
            (telegram_id, tag, utcnow()),
        )
        self.event(telegram_id, "tag_added", tag)

    def set_relationship_type(self, telegram_id: int, value: str, admin_id: int):
        value = value.lower().strip()
        if value not in RELATIONSHIP_TYPES:
            raise ValueError(f"Invalid relationship type: {value}")
        old = self.db.one("SELECT relationship_type FROM contacts WHERE telegram_id=?", (telegram_id,))
        self.db.execute(
            "UPDATE contacts SET relationship_type=?, updated_at=? WHERE telegram_id=?",
            (value, utcnow(), telegram_id),
        )
        self.event(telegram_id, "relationship_type_changed", f"{old['relationship_type']} -> {value}")
        self.classification.record_manual(telegram_id, old['relationship_type'], value, admin_id, 'Manual relationship type change')
        self.integration.emit('classification_changed', telegram_id, {'old_type': old['relationship_type'], 'new_type': value, 'confidence': 100, 'auto': False})
        self.audit(admin_id, "set_relationship_type", telegram_id, value)

    def set_verification(self, telegram_id: int, value: str, admin_id: int, reason: str = ""):
        value = value.lower().strip()
        if value not in VERIFICATION_STATES:
            raise ValueError(f"Invalid verification state: {value}")
        old = self.db.one("SELECT verification_status FROM contacts WHERE telegram_id=?", (telegram_id,))
        old_value = old["verification_status"]
        self.db.execute(
            "UPDATE contacts SET verification_status=?, updated_at=? WHERE telegram_id=?",
            (value, utcnow(), telegram_id),
        )
        self.db.execute(
            """INSERT INTO verification_history
               (telegram_id, old_status, new_status, changed_by, reason, changed_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (telegram_id, old_value, value, admin_id, reason, utcnow()),
        )
        self.event(telegram_id, "verification_changed", f"{old_value} -> {value}")
        self.audit(admin_id, "set_verification", telegram_id, f"{value}: {reason}")

    def add_followup(self, telegram_id: int, due_at: datetime, reason: str, admin_id: int):
        due = due_at.astimezone(timezone.utc).isoformat()
        followup_id = self.db.execute(
            """INSERT INTO followups
               (telegram_id, due_at, reason, created_by, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (telegram_id, due, reason, admin_id, utcnow()),
        )
        self.event(telegram_id, "followup_created", f"{due}: {reason}")
        self.audit(admin_id, "add_followup", telegram_id, f"{due}: {reason}")
        return followup_id

    def complete_followup(self, followup_id: int, admin_id: int):
        row = self.db.one("SELECT telegram_id FROM followups WHERE id=?", (followup_id,))
        if not row:
            return False
        telegram_id = row["telegram_id"]
        self.db.execute(
            "UPDATE followups SET status='done', completed_at=? WHERE id=?",
            (utcnow(), followup_id),
        )
        self.event(telegram_id, "followup_completed", f"Follow-up #{followup_id}")
        self.audit(admin_id, "complete_followup", telegram_id, str(followup_id))

        remaining_due = self.db.one(
            """SELECT COUNT(*) n FROM followups
               WHERE telegram_id=? AND status='open' AND due_at<=?""",
            (telegram_id, utcnow()),
        )["n"]
        if remaining_due == 0:
            self._resolve_attention_category(telegram_id, "followup")
        self.recalculate_contact(telegram_id)
        return True

    def resolve_attention(self, attention_id: int, admin_id: int):
        row = self.db.one(
            "SELECT telegram_id, category FROM attention_queue WHERE id=? AND status='open'",
            (attention_id,),
        )
        if not row:
            return False
        self.db.execute(
            """UPDATE attention_queue
               SET status='resolved', resolved_at=?
               WHERE id=?""",
            (utcnow(), attention_id),
        )
        self.audit(
            admin_id,
            "resolve_attention",
            row["telegram_id"],
            f"{attention_id}:{row['category']}",
        )
        return True

    def recalculate_contact(self, telegram_id: int):
        c = self.db.one("SELECT * FROM contacts WHERE telegram_id=?", (telegram_id,))
        if not c:
            return

        now = datetime.now(timezone.utc)
        first_seen = datetime.fromisoformat(c["first_seen"])
        last_seen = datetime.fromisoformat(c["last_seen"])
        age_days = max((now - first_seen).days, 0)
        inactive_days = max((now - last_seen).days, 0)

        # Relationship score: transparent, deterministic core model.
        recency = max(0, 25 - min(inactive_days, 25))
        frequency = min(20, int(c["interaction_count"] / 5))
        duration = min(15, int(age_days / 14))
        consistency = min(15, int(c["active_days"] / 3))
        importance = min(10, max(0, int(c["manual_importance"])))
        group_count = self.db.one(
            "SELECT COUNT(*) AS n FROM contact_groups WHERE telegram_id=? AND chat_id<0", (telegram_id,)
        )["n"]
        shared_presence = min(5, int(group_count))
        important_events = self.db.one(
            """SELECT COUNT(*) AS n FROM relationship_events
               WHERE telegram_id=? AND event_type IN
               ('verification_changed','followup_completed','successful_interaction')""",
            (telegram_id,),
        )["n"]
        important = min(10, int(important_events * 2))
        relationship_score = max(
            0,
            min(
                100,
                recency + frequency + duration + consistency + importance
                + shared_presence + important,
            ),
        )

        trust = 50
        verify = c["verification_status"]
        if verify == "verified":
            trust += 20
        elif verify == "trusted":
            trust += 35
        elif verify == "restricted":
            trust -= 35

        trust += min(10, age_days // 30)
        confirmed_flags = self.db.one(
            """SELECT COALESCE(SUM(severity),0) AS n FROM risk_flags
               WHERE telegram_id=? AND review_status='confirmed'""",
            (telegram_id,),
        )["n"]
        trust -= int(confirmed_flags) * 8
        trust = max(0, min(100, trust))

        cycle = self._estimate_cycle_days(telegram_id)
        activity_status = self._activity_status(inactive_days, cycle, c["activity_status"])
        intelligence = self._calculate_intelligence(
            c,
            relationship_score=relationship_score,
            trust_score=trust,
            activity_status=activity_status,
            cycle=cycle,
            inactive_days=inactive_days,
            group_count=group_count,
            now=now,
        )

        self.db.execute(
            """UPDATE contacts
               SET relationship_score=?, trust_score=?, typical_cycle_days=?,
                   activity_status=?, last_score_update=?, updated_at=?
               WHERE telegram_id=?""",
            (
                relationship_score, trust, cycle, activity_status,
                utcnow(), utcnow(), telegram_id,
            ),
        )

        previous_intel = self.db.one(
            "SELECT * FROM contact_intelligence WHERE telegram_id=?", (telegram_id,)
        )
        self.db.execute(
            """INSERT INTO contact_intelligence
               (telegram_id, health_score, momentum_label, momentum_score,
                lifecycle_stage, days_overdue, recent_7_interactions,
                previous_7_interactions, recent_7_active_days,
                previous_7_active_days, suggested_action, computed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(telegram_id) DO UPDATE SET
                 health_score=excluded.health_score,
                 momentum_label=excluded.momentum_label,
                 momentum_score=excluded.momentum_score,
                 lifecycle_stage=excluded.lifecycle_stage,
                 days_overdue=excluded.days_overdue,
                 recent_7_interactions=excluded.recent_7_interactions,
                 previous_7_interactions=excluded.previous_7_interactions,
                 recent_7_active_days=excluded.recent_7_active_days,
                 previous_7_active_days=excluded.previous_7_active_days,
                 suggested_action=excluded.suggested_action,
                 computed_at=excluded.computed_at""",
            (
                telegram_id,
                intelligence["health_score"],
                intelligence["momentum_label"],
                intelligence["momentum_score"],
                intelligence["lifecycle_stage"],
                intelligence["days_overdue"],
                intelligence["recent_7_interactions"],
                intelligence["previous_7_interactions"],
                intelligence["recent_7_active_days"],
                intelligence["previous_7_active_days"],
                intelligence["suggested_action"],
                utcnow(),
            ),
        )

        # Keep one rolling snapshot per contact/day for longer-term trend work.
        snapshot_date = now.date().isoformat()
        self.db.execute(
            """INSERT INTO relationship_snapshots
               (telegram_id, snapshot_date, relationship_score, trust_score,
                health_score, momentum_score, interaction_count, active_days, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(telegram_id, snapshot_date) DO UPDATE SET
                 relationship_score=excluded.relationship_score,
                 trust_score=excluded.trust_score,
                 health_score=excluded.health_score,
                 momentum_score=excluded.momentum_score,
                 interaction_count=excluded.interaction_count,
                 active_days=excluded.active_days,
                 created_at=excluded.created_at""",
            (
                telegram_id, snapshot_date, relationship_score, trust,
                intelligence["health_score"], intelligence["momentum_score"],
                c["interaction_count"], c["active_days"], utcnow(),
            ),
        )

        # Keep the timeline meaningful: record stage changes, not every score tick.
        if previous_intel:
            if previous_intel["lifecycle_stage"] != intelligence["lifecycle_stage"]:
                self.event(
                    telegram_id,
                    "lifecycle_changed",
                    f"{previous_intel['lifecycle_stage']} -> {intelligence['lifecycle_stage']}",
                )
            prev_momentum = previous_intel["momentum_label"]
            new_momentum = intelligence["momentum_label"]
            if prev_momentum != new_momentum and {
                prev_momentum, new_momentum
            } & {"surging", "growing", "cooling", "fading"}:
                self.event(
                    telegram_id,
                    "momentum_changed",
                    f"{prev_momentum} -> {new_momentum}",
                )

        self._queue_attention(
            c,
            activity_status,
            inactive_days,
            relationship_score,
            intelligence,
        )
        # Re-rank the contact after relationship/attention state changes.
        self.priority.compute(telegram_id)
        return intelligence

    def _activity_window(self, telegram_id: int, start_date, end_date):
        row = self.db.one(
            """SELECT COALESCE(SUM(interaction_count),0) AS interactions,
                      COUNT(*) AS active_days
               FROM daily_activity
               WHERE telegram_id=? AND activity_date BETWEEN ? AND ?""",
            (telegram_id, start_date.isoformat(), end_date.isoformat()),
        )
        return int(row["interactions"] or 0), int(row["active_days"] or 0)

    def _calculate_intelligence(
        self,
        contact,
        relationship_score: int,
        trust_score: int,
        activity_status: str,
        cycle: float | None,
        inactive_days: int,
        group_count: int,
        now: datetime,
    ):
        tid = contact["telegram_id"]
        today = now.date()
        recent7_i, recent7_d = self._activity_window(
            tid, today - timedelta(days=6), today
        )
        previous7_i, previous7_d = self._activity_window(
            tid, today - timedelta(days=13), today - timedelta(days=7)
        )

        total_active_days = int(contact["active_days"])
        total_interactions = int(contact["interaction_count"])

        if total_active_days < 2 or total_interactions < 3:
            momentum_score = 0
            momentum_label = "learning"
        else:
            recent_signal = recent7_i + (recent7_d * 3)
            previous_signal = previous7_i + (previous7_d * 3)
            if previous_signal == 0 and recent_signal > 0:
                momentum_score = min(100, 35 + recent_signal * 3)
            elif recent_signal == 0 and previous_signal > 0:
                momentum_score = max(-100, -45 - previous_signal * 2)
            elif recent_signal == 0 and previous_signal == 0:
                momentum_score = -25 if inactive_days >= 7 else 0
            else:
                ratio_delta = (recent_signal - previous_signal) / max(previous_signal, 1)
                momentum_score = int(max(-100, min(100, ratio_delta * 65 + (recent7_d - previous7_d) * 8)))

            # A sparse/weekly contact should not be labelled as fading merely
            # because their last active day falls just outside the rolling
            # seven-day comparison. Respect the learned personal cadence first.
            if cycle and inactive_days <= max(2, int(math.ceil(float(cycle) * 1.25))):
                momentum_score = max(momentum_score, -10)

            if momentum_score >= 45:
                momentum_label = "surging"
            elif momentum_score >= 15:
                momentum_label = "growing"
            elif momentum_score <= -45:
                momentum_label = "fading"
            elif momentum_score <= -15:
                momentum_label = "cooling"
            else:
                momentum_label = "stable"

        # Relationship health is intentionally about current condition, not
        # absolute importance. It uses each person's learned cycle where possible.
        if total_interactions == 0:
            recency_health = 55
        elif cycle:
            ratio = inactive_days / max(float(cycle), 1.0)
            if ratio <= 0.75:
                recency_health = 100
            elif ratio <= 1.25:
                recency_health = 85
            elif ratio <= 1.5:
                recency_health = 70
            elif ratio <= 2.0:
                recency_health = 45
            elif ratio <= 2.5:
                recency_health = 25
            else:
                recency_health = 10
        else:
            if inactive_days <= 2:
                recency_health = 95
            elif inactive_days <= 7:
                recency_health = 85
            elif inactive_days <= 14:
                recency_health = 65
            elif inactive_days <= 30:
                recency_health = 35
            else:
                recency_health = 15

        momentum_health = 55 if momentum_label == "learning" else int(50 + momentum_score / 2)
        consistency_health = min(100, 35 + total_active_days * 7 + min(group_count, 5) * 3)
        health_score = int(round(
            recency_health * 0.60 + momentum_health * 0.25 + consistency_health * 0.15
        ))
        health_score = max(0, min(100, health_score))

        if activity_status == "dormant":
            lifecycle = "dormant"
        elif activity_status == "cooling":
            lifecycle = "cooling"
        elif activity_status == "returned":
            lifecycle = "returned"
        elif total_interactions == 0:
            lifecycle = "discovered"
        elif total_active_days <= 1 and relationship_score < 40:
            lifecycle = "new"
        elif relationship_score < 50:
            lifecycle = "developing"
        elif relationship_score < 70:
            lifecycle = "established"
        elif relationship_score < 85:
            lifecycle = "strong"
        elif contact["relationship_type"] == "vip":
            lifecycle = "vip"
        else:
            lifecycle = "vip_candidate"

        days_overdue = 0
        if cycle and total_interactions > 0:
            expected_window = max(3, int(math.ceil(float(cycle) * 1.35)))
            days_overdue = max(0, inactive_days - expected_window)

        due_followups = self.db.one(
            """SELECT COUNT(*) AS n FROM followups
               WHERE telegram_id=? AND status='open' AND due_at<=?""",
            (tid, utcnow()),
        )["n"]

        if due_followups:
            action = "Follow-up is due now."
        elif contact["verification_status"] == "restricted":
            action = "Review restrictions/risk before engaging."
        elif days_overdue > 0:
            action = f"Contact is {days_overdue} day(s) beyond their learned activity window; consider a check-in."
        elif health_score < 40 and relationship_score >= 50:
            action = "High-value relationship health is low; review or check in."
        elif momentum_label in {"cooling", "fading"} and relationship_score >= 45:
            action = "Momentum is declining; consider a light check-in."
        elif lifecycle == "vip_candidate":
            action = "Review as a possible VIP."
        elif contact["relationship_type"] in {"unknown", "prospect"} and total_interactions >= 3:
            action = "Classify this relationship when convenient."
        elif contact["verification_status"] in {"unknown", "pending"} and relationship_score >= 60:
            action = "Consider verification review."
        elif momentum_label in {"growing", "surging"}:
            action = "Relationship momentum is positive; no intervention needed."
        elif total_interactions == 0:
            action = "No live interaction data yet; keep learning."
        else:
            action = "No immediate action needed."

        return {
            "health_score": health_score,
            "momentum_label": momentum_label,
            "momentum_score": momentum_score,
            "lifecycle_stage": lifecycle,
            "days_overdue": days_overdue,
            "recent_7_interactions": recent7_i,
            "previous_7_interactions": previous7_i,
            "recent_7_active_days": recent7_d,
            "previous_7_active_days": previous7_d,
            "suggested_action": action,
        }

    def get_intelligence(self, telegram_id: int, refresh: bool = False):
        if refresh or not self.db.one(
            "SELECT 1 FROM contact_intelligence WHERE telegram_id=?", (telegram_id,)
        ):
            self.recalculate_contact(telegram_id)
        return self.db.one(
            "SELECT * FROM contact_intelligence WHERE telegram_id=?", (telegram_id,)
        )

    def recalculate_all(self):
        for row in self.db.all("SELECT telegram_id FROM contacts"):
            self.recalculate_contact(row["telegram_id"])

    def _estimate_cycle_days(self, telegram_id: int):
        rows = self.db.all(
            """SELECT activity_date FROM daily_activity
               WHERE telegram_id=? ORDER BY activity_date DESC LIMIT 12""",
            (telegram_id,),
        )
        if len(rows) < 4:
            return None
        dates = [datetime.fromisoformat(r["activity_date"]).date() for r in reversed(rows)]
        gaps = [(b - a).days for a, b in zip(dates, dates[1:]) if (b - a).days > 0]
        if len(gaps) < 3:
            return None
        return round(float(median(gaps)), 1)

    @staticmethod
    def _activity_status(inactive_days: int, cycle: float | None, previous: str):
        if cycle:
            cooling = max(7, int(cycle * 1.5))
            dormant = max(14, int(cycle * 2.5))
        else:
            cooling, dormant = 14, 30
        if inactive_days >= dormant:
            return "dormant"
        if inactive_days >= cooling:
            return "cooling"
        if previous == "dormant":
            return "returned"
        if previous == "returned" and inactive_days <= 1:
            return "returned"
        return "active"

    def _queue_attention(self, contact, status: str, inactive_days: int, score: int, intelligence):
        tid = contact["telegram_id"]
        rel_type = contact["relationship_type"]
        verification = contact["verification_status"]
        health = intelligence["health_score"]
        momentum = intelligence["momentum_label"]
        overdue = intelligence["days_overdue"]
        interactions = int(contact["interaction_count"])

        if status == "dormant" and (
            rel_type in {"regular", "vip", "supplier", "partner", "customer"} or score >= 60
        ):
            self._attention(
                tid, "orange", "dormant",
                "Important relationship is dormant",
                f"No observed interaction for {inactive_days} days.",
            )
        else:
            self._resolve_attention_category(tid, "dormant")

        if status == "returned":
            self._attention(
                tid, "yellow", "returned",
                "Dormant relationship has returned",
                "New activity was observed after a dormant period.",
            )
        elif status in {"cooling", "dormant"}:
            self._resolve_attention_category(tid, "returned")

        if score >= 80 and rel_type not in {"vip", "admin", "partner"}:
            self._attention(
                tid, "yellow", "vip_candidate",
                "Potential VIP candidate",
                f"Relationship score is {score}/100.",
            )
        else:
            self._resolve_attention_category(tid, "vip_candidate")

        if score >= 60 and rel_type in {"unknown", "prospect"} and status != "dormant":
            self._attention(
                tid, "yellow", "relationship_review",
                "Relationship type may need review",
                f"Relationship score is {score}/100 but type is still {rel_type}.",
            )
        else:
            self._resolve_attention_category(tid, "relationship_review")

        if score >= 60 and verification in {"unknown", "pending"} and status != "dormant":
            self._attention(
                tid, "yellow", "verification_review",
                "Consider verification review",
                f"Relationship score is {score}/100 and verification is {verification}.",
            )
        else:
            self._resolve_attention_category(tid, "verification_review")

        # Smart cycle follow-up: only surfaces after enough history exists to
        # learn a contact-specific cadence. It suggests action; it does not send
        # messages or create a follow-up automatically.
        if overdue > 0 and (score >= 40 or rel_type in {"customer", "regular", "vip", "supplier", "partner"}):
            priority = "orange" if overdue >= 5 or health < 45 else "yellow"
            self._attention(
                tid, priority, "smart_followup",
                "Outside normal contact cycle",
                f"{overdue} day(s) beyond learned activity window Â· health {health}/100.",
            )
        else:
            self._resolve_attention_category(tid, "smart_followup")

        if score >= 50 and health < 55 and momentum in {"cooling", "fading"}:
            priority = "orange" if health < 40 else "yellow"
            self._attention(
                tid, priority, "relationship_slipping",
                "Relationship health is slipping",
                f"Health {health}/100 Â· momentum {momentum}.",
            )
        else:
            self._resolve_attention_category(tid, "relationship_slipping")

        # Triage only genuinely active new/unclassified people so historical
        # bootstrap discoveries do not flood the admin inbox.
        if rel_type == "unknown" and interactions >= 3 and status in {"active", "returned"}:
            self._attention(
                tid, "blue", "new_contact_triage",
                "Active contact is still unclassified",
                f"{interactions} observed interactions Â· score {score}/100.",
            )
        else:
            self._resolve_attention_category(tid, "new_contact_triage")

        if rel_type in {"vip", "supplier", "partner", "customer", "regular"} and health < 35:
            self._attention(
                tid, "red", "relationship_health",
                "Important relationship health is critical",
                f"Health is {health}/100. Review this relationship soon.",
            )
        else:
            self._resolve_attention_category(tid, "relationship_health")

    def _resolve_attention_category(self, telegram_id: int, category: str):
        self.db.execute(
            """UPDATE attention_queue
               SET status='resolved', resolved_at=?
               WHERE telegram_id=? AND category=? AND status='open'""",
            (utcnow(), telegram_id, category),
        )

    def process_due_followups(self):
        now = utcnow()
        rows = self.db.all(
            """SELECT f.*, c.display_name, c.username
               FROM followups f JOIN contacts c ON c.telegram_id=f.telegram_id
               WHERE f.status='open' AND f.due_at<=?""",
            (now,),
        )
        for r in rows:
            self._attention(
                r["telegram_id"], "orange", "followup",
                "Follow-up due",
                r["reason"] or "Follow-up is due.",
            )

    def _attention(self, telegram_id: int, priority: str, category: str, title: str, details: str):
        # One open item of each category per person.
        row = self.db.one(
            """SELECT id FROM attention_queue
               WHERE telegram_id=? AND category=? AND status='open'""",
            (telegram_id, category),
        )
        if row:
            self.db.execute(
                "UPDATE attention_queue SET priority=?, title=?, details=? WHERE id=?",
                (priority, title, details, row["id"]),
            )
        else:
            self.db.execute(
                """INSERT INTO attention_queue
                   (telegram_id, priority, category, title, details, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (telegram_id, priority, category, title, details, utcnow()),
            )

    def audit(self, admin_id: int, action: str, telegram_id: int | None, details: str | None):
        self.db.execute(
            """INSERT INTO admin_audit
               (admin_id, action, telegram_id, details, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (admin_id, action, telegram_id, details, utcnow()),
        )
