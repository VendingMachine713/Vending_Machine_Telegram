from __future__ import annotations

from datetime import datetime, timedelta, timezone
from statistics import median

from database import Database, utcnow


class SessionEngine:
    """Derives conversation-session aggregates from direction/timing metadata only."""

    GAP_SECONDS = 30 * 60

    def __init__(self, db: Database):
        self.db = db

    @staticmethod
    def _dt(value: str):
        return datetime.fromisoformat(value)

    def _sessions(self, telegram_id: int, days: int = 90):
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        rows = self.db.all(
            """SELECT direction,occurred_at FROM private_interactions
               WHERE telegram_id=? AND occurred_at>=? ORDER BY occurred_at ASC,id ASC""",
            (telegram_id, cutoff),
        )
        sessions = []
        current = None
        for r in rows:
            ts = self._dt(r["occurred_at"])
            if current is None or (ts - current["last"]).total_seconds() > self.GAP_SECONDS:
                if current:
                    sessions.append(current)
                current = {
                    "start": ts,
                    "last": ts,
                    "incoming": 0,
                    "outgoing": 0,
                    "initiator": r["direction"],
                }
            current["last"] = ts
            current[r["direction"]] += 1
        if current:
            sessions.append(current)
        for s in sessions:
            s["messages"] = s["incoming"] + s["outgoing"]
            s["duration_seconds"] = max(0, int((s["last"] - s["start"]).total_seconds()))
        return sessions

    def compute(self, telegram_id: int):
        s90 = self._sessions(telegram_id, 90)
        cutoff30 = datetime.now(timezone.utc) - timedelta(days=30)
        s30 = [s for s in s90 if s["start"] >= cutoff30]
        durations = [s["duration_seconds"] for s in s30]
        messages = [s["messages"] for s in s30]
        incoming_started = sum(1 for s in s30 if s["initiator"] == "incoming")
        outgoing_started = sum(1 for s in s30 if s["initiator"] == "outgoing")
        count = len(s30)
        depth = round(sum(messages) / count, 1) if count else 0.0
        median_duration = int(median(durations)) if durations else 0
        balanced = 50
        if incoming_started + outgoing_started:
            balanced = round(100 * min(incoming_started, outgoing_started) / max(incoming_started, outgoing_started, 1))
        label = "learning"
        if count >= 3:
            if depth >= 8 and balanced >= 60:
                label = "deep_mutual"
            elif depth >= 5:
                label = "engaged"
            elif count >= 8:
                label = "frequent_short"
            else:
                label = "light"
        self.db.execute(
            """INSERT INTO conversation_session_metrics
               (telegram_id,sessions_30,avg_messages_per_session,median_duration_seconds,
                incoming_started_30,outgoing_started_30,initiation_balance_score,session_label,computed_at)
               VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT(telegram_id) DO UPDATE SET
                sessions_30=excluded.sessions_30,
                avg_messages_per_session=excluded.avg_messages_per_session,
                median_duration_seconds=excluded.median_duration_seconds,
                incoming_started_30=excluded.incoming_started_30,
                outgoing_started_30=excluded.outgoing_started_30,
                initiation_balance_score=excluded.initiation_balance_score,
                session_label=excluded.session_label,
                computed_at=excluded.computed_at""",
            (
                telegram_id, count, depth, median_duration, incoming_started, outgoing_started,
                balanced, label, utcnow(),
            ),
        )
        return self.get(telegram_id)

    def get(self, telegram_id: int, refresh: bool = False):
        row = self.db.one("SELECT * FROM conversation_session_metrics WHERE telegram_id=?", (telegram_id,))
        if refresh or row is None:
            return self.compute(telegram_id)
        return row

    def compute_all(self):
        count = 0
        for r in self.db.all("SELECT telegram_id FROM contacts"):
            self.compute(r["telegram_id"])
            count += 1
        return count

    def recent_sessions(self, telegram_id: int, days: int = 30, limit: int = 10):
        sessions = self._sessions(telegram_id, max(days, 1))
        return list(reversed(sessions[-limit:]))
