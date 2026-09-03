from __future__ import annotations

from datetime import datetime, timedelta, timezone
from statistics import median

from database import Database, utcnow


class BehaviorEngine:
    """Metadata-only private-chat behaviour analytics.

    No message text is stored. Metrics are derived from direction and timestamps
    in private dialogs only, because general group posts cannot safely be
    attributed as a direct interaction with one specific person.
    """

    SESSION_GAP_HOURS = 6
    RESPONSE_MAX_HOURS = 72
    RETENTION_DAYS = 120

    def __init__(self, db: Database):
        self.db = db

    def record(self, telegram_id: int, chat_id: int, message_id: int,
               direction: str, occurred_at: datetime):
        if direction not in {"incoming", "outgoing"}:
            raise ValueError("direction must be incoming or outgoing")
        occurred = occurred_at.astimezone(timezone.utc).isoformat()
        self.db.execute(
            """INSERT OR IGNORE INTO private_interactions
               (telegram_id, chat_id, message_id, direction, occurred_at, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (telegram_id, chat_id, message_id, direction, occurred, utcnow()),
        )
        count = self.db.one(
            "SELECT COUNT(*) n FROM private_interactions WHERE telegram_id=?",
            (telegram_id,),
        )["n"]
        if count <= 2 or count % 5 == 0:
            self.compute(telegram_id)

    def compute(self, telegram_id: int):
        now = datetime.now(timezone.utc)
        start60 = (now - timedelta(days=60)).isoformat()
        rows = self.db.all(
            """SELECT direction, occurred_at FROM private_interactions
               WHERE telegram_id=? AND occurred_at>=?
               ORDER BY occurred_at ASC""",
            (telegram_id, start60),
        )
        events = [(r["direction"], datetime.fromisoformat(r["occurred_at"])) for r in rows]
        cutoff30 = now - timedelta(days=30)
        incoming30 = sum(1 for d,t in events if d == "incoming" and t >= cutoff30)
        outgoing30 = sum(1 for d,t in events if d == "outgoing" and t >= cutoff30)

        incoming_inits = outgoing_inits = 0
        our_responses = []
        their_responses = []
        prev_d = None
        prev_t = None
        for d,t in events:
            if prev_t is None or (t-prev_t).total_seconds() > self.SESSION_GAP_HOURS*3600:
                if d == "incoming": incoming_inits += 1
                else: outgoing_inits += 1
            elif prev_d != d:
                seconds=(t-prev_t).total_seconds()
                if 0 <= seconds <= self.RESPONSE_MAX_HOURS*3600:
                    if prev_d == "incoming" and d == "outgoing":
                        our_responses.append(seconds)
                    elif prev_d == "outgoing" and d == "incoming":
                        their_responses.append(seconds)
            prev_d, prev_t = d,t

        total30=incoming30+outgoing30
        message_balance = 1.0 if total30 == 0 else 1 - abs(incoming30-outgoing30)/max(total30,1)
        init_total=incoming_inits+outgoing_inits
        init_balance = 1.0 if init_total == 0 else 1 - abs(incoming_inits-outgoing_inits)/max(init_total,1)
        reciprocity = round(max(0,min(100, 70*message_balance + 30*init_balance)))

        # Consistency = how many recent weeks contain any private interaction.
        active_weeks=set()
        for _,t in events:
            delta=(now.date()-t.date()).days
            if 0 <= delta < 56:
                active_weeks.add(delta//7)
        consistency=round(min(100, len(active_weeks)/8*100))

        recent14=sum(1 for _,t in events if t >= now-timedelta(days=14))
        prev14=sum(1 for _,t in events if now-timedelta(days=28) <= t < now-timedelta(days=14))
        if prev14 == 0:
            acceleration = 100.0 if recent14 >= 3 else 0.0
        else:
            acceleration = round(((recent14-prev14)/prev14)*100,1)
        acceleration=max(-300.0,min(300.0,acceleration))

        if len(events) < 4:
            label='learning'
        elif total30 == 0:
            label='quiet'
        elif acceleration >= 60 and recent14 >= 4:
            label='accelerating'
        elif acceleration <= -50 and prev14 >= 4:
            label='slowing'
        elif incoming_inits >= outgoing_inits*2 and incoming_inits >= 2:
            label='they_initiate'
        elif outgoing_inits >= incoming_inits*2 and outgoing_inits >= 2:
            label='you_initiate'
        elif reciprocity >= 70:
            label='mutual'
        else:
            label='mixed'

        self.db.execute(
            """INSERT INTO behavior_metrics
               (telegram_id, incoming_30, outgoing_30,
                incoming_initiations_60, outgoing_initiations_60,
                reciprocity_score, consistency_score,
                median_our_response_seconds, median_their_response_seconds,
                our_response_samples, their_response_samples,
                acceleration_pct, behavior_label, computed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(telegram_id) DO UPDATE SET
                 incoming_30=excluded.incoming_30,
                 outgoing_30=excluded.outgoing_30,
                 incoming_initiations_60=excluded.incoming_initiations_60,
                 outgoing_initiations_60=excluded.outgoing_initiations_60,
                 reciprocity_score=excluded.reciprocity_score,
                 consistency_score=excluded.consistency_score,
                 median_our_response_seconds=excluded.median_our_response_seconds,
                 median_their_response_seconds=excluded.median_their_response_seconds,
                 our_response_samples=excluded.our_response_samples,
                 their_response_samples=excluded.their_response_samples,
                 acceleration_pct=excluded.acceleration_pct,
                 behavior_label=excluded.behavior_label,
                 computed_at=excluded.computed_at""",
            (telegram_id, incoming30, outgoing30, incoming_inits, outgoing_inits,
             reciprocity, consistency,
             median(our_responses) if our_responses else None,
             median(their_responses) if their_responses else None,
             len(our_responses), len(their_responses), acceleration, label, utcnow()),
        )
        return self.db.one("SELECT * FROM behavior_metrics WHERE telegram_id=?", (telegram_id,))

    def get(self, telegram_id: int, refresh: bool=False):
        row=self.db.one("SELECT * FROM behavior_metrics WHERE telegram_id=?", (telegram_id,))
        if refresh or row is None:
            return self.compute(telegram_id)
        return row

    def compute_all(self):
        for r in self.db.all("SELECT telegram_id FROM contacts"):
            self.compute(r["telegram_id"])

    def prune(self):
        cutoff=(datetime.now(timezone.utc)-timedelta(days=self.RETENTION_DAYS)).isoformat()
        self.db.execute("DELETE FROM private_interactions WHERE occurred_at<?", (cutoff,))
