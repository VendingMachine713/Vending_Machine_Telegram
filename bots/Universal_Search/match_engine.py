import json
import math
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core import utc_now


MATCH_SCHEMA = """
CREATE TABLE IF NOT EXISTS marketplace_matches(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  demand_logical_id TEXT NOT NULL,
  supply_logical_id TEXT NOT NULL,
  demand_listing_id INTEGER NOT NULL,
  supply_listing_id INTEGER NOT NULL,
  score REAL NOT NULL,
  confidence REAL NOT NULL,
  reasons_json TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'new',
  first_seen_utc TEXT NOT NULL,
  updated_utc TEXT NOT NULL,
  notified_utc TEXT,
  UNIQUE(demand_logical_id,supply_logical_id)
);
CREATE INDEX IF NOT EXISTS ix_market_matches_status_score
  ON marketplace_matches(status,score DESC,updated_utc DESC);
CREATE INDEX IF NOT EXISTS ix_market_matches_demand
  ON marketplace_matches(demand_logical_id,status);
CREATE INDEX IF NOT EXISTS ix_market_matches_supply
  ON marketplace_matches(supply_logical_id,status);

CREATE TABLE IF NOT EXISTS marketplace_match_feedback(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  match_id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  verdict TEXT NOT NULL,
  note TEXT,
  created_utc TEXT NOT NULL,
  UNIQUE(match_id,user_id)
);
CREATE INDEX IF NOT EXISTS ix_market_match_feedback_verdict
  ON marketplace_match_feedback(verdict,created_utc DESC);

CREATE TABLE IF NOT EXISTS marketplace_match_alert_queue(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  match_id INTEGER NOT NULL,
  owner_user_id INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  attempts INTEGER NOT NULL DEFAULT 0,
  due_utc TEXT NOT NULL,
  created_utc TEXT NOT NULL,
  sent_utc TEXT,
  last_error TEXT,
  UNIQUE(match_id,owner_user_id)
);
CREATE INDEX IF NOT EXISTS ix_market_match_alert_due
  ON marketplace_match_alert_queue(status,due_utc);

CREATE TABLE IF NOT EXISTS marketplace_match_state(
  key TEXT PRIMARY KEY,
  value TEXT,
  updated_utc TEXT NOT NULL
);
"""

ACTIVE_MATCH_STATES = {"new", "baseline", "notified", "accepted"}
MANUAL_MATCH_STATES = {"accepted", "dismissed"}
FEEDBACK_VERDICTS = {"relevant", "not_relevant", "accepted", "ignore"}
SUPPLY_TYPES = {"sale", "trade", "service"}

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "available", "buy", "buying", "cash", "chasing",
    "dm", "for", "from", "have", "i", "in", "is", "it", "looking", "me", "need", "of",
    "on", "only", "or", "please", "pm", "price", "sale", "selling", "the", "to", "trade",
    "want", "wanted", "wtb", "wtt", "with", "pickup", "delivery", "budget", "after", "asking",
    "firm", "ono", "condition", "located", "location", "brand", "new", "used",
}


@dataclass(frozen=True)
class MatchScore:
    eligible: bool
    score: float
    confidence: float
    reasons: tuple[dict, ...]
    reject_reason: str | None = None


def _parse_dt(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _tokens(*values):
    result = set()
    for value in values:
        for token in re.findall(r"[a-z0-9]+", (value or "").lower()):
            if token in STOPWORDS:
                continue
            if len(token) <= 2 and not token.isdigit():
                continue
            if token.isdigit() and len(token) >= 4:
                # Prices and years are weak identity signals; model numbers such as 15/350 remain useful.
                continue
            result.add(token)
    return result


def _location_tokens(value):
    return {
        token for token in re.findall(r"[a-z0-9]+", (value or "").lower())
        if len(token) >= 3
    }


def _freshness_points(date_value, now=None):
    dt = _parse_dt(date_value)
    if not dt:
        return 0.0
    now = now or datetime.now(timezone.utc)
    age = max(timedelta(0), now - dt)
    days = age.total_seconds() / 86400
    if days <= 2:
        return 8.0
    if days <= 7:
        return 6.0
    if days <= 30:
        return 3.0
    if days <= 90:
        return 1.0
    return 0.0


def _same_sender(demand, supply):
    return (
        demand["sender_id"] is not None
        and supply["sender_id"] is not None
        and int(demand["sender_id"]) == int(supply["sender_id"])
    )


def score_marketplace_pair(demand, supply, *, now=None):
    reasons = []
    if demand["listing_type"] != "wanted" or demand["status"] != "wanted":
        return MatchScore(False, 0.0, 0.0, tuple(), "not_active_demand")
    if supply["listing_type"] not in SUPPLY_TYPES or supply["status"] != "available":
        return MatchScore(False, 0.0, 0.0, tuple(), "not_active_supply")
    if demand["logical_listing_id"] == supply["logical_listing_id"]:
        return MatchScore(False, 0.0, 0.0, tuple(), "same_logical_listing")
    if _same_sender(demand, supply):
        return MatchScore(False, 0.0, 0.0, tuple(), "self_match")

    demand_category = demand["category"] or "other"
    supply_category = supply["category"] or "other"
    if (
        demand_category != "other"
        and supply_category != "other"
        and demand_category != supply_category
    ):
        return MatchScore(False, 0.0, 0.0, tuple(), "category_mismatch")

    demand_budget = demand["price_cents"]
    supply_price = supply["price_cents"]
    if (
        demand_budget is not None
        and supply_price is not None
        and int(supply_price) > int(demand_budget)
    ):
        return MatchScore(False, 0.0, 0.0, tuple(), "over_budget")

    score = 0.0
    if demand_category != "other" and demand_category == supply_category:
        score += 16.0
        reasons.append({"code": "category", "points": 16.0, "detail": demand_category})
    elif demand_category == "other" or supply_category == "other":
        score += 3.0
        reasons.append({"code": "category_unknown", "points": 3.0})

    demand_terms = _tokens(demand["title"], demand["text"])
    supply_terms = _tokens(supply["title"], supply["text"])
    intersection = demand_terms & supply_terms
    union = demand_terms | supply_terms
    demand_coverage = len(intersection) / max(1, len(demand_terms))
    jaccard = len(intersection) / max(1, len(union))
    token_points = min(40.0, demand_coverage * 28.0 + jaccard * 18.0)
    if intersection:
        score += token_points
        reasons.append(
            {
                "code": "terms",
                "points": round(token_points, 2),
                "detail": sorted(intersection)[:10],
            }
        )
    elif demand_category == "other":
        return MatchScore(False, 0.0, 0.0, tuple(), "no_product_overlap")

    if demand_budget is not None and supply_price is not None:
        score += 15.0
        reasons.append(
            {
                "code": "within_budget",
                "points": 15.0,
                "detail": {"budget": int(demand_budget), "price": int(supply_price)},
            }
        )
    elif supply_price is not None:
        score += 3.0
        reasons.append({"code": "priced_supply", "points": 3.0})

    demand_location = _location_tokens(demand["location_hint"])
    supply_location = _location_tokens(supply["location_hint"])
    if demand_location and supply_location:
        location_overlap = demand_location & supply_location
        if location_overlap:
            score += 10.0
            reasons.append(
                {"code": "location", "points": 10.0, "detail": sorted(location_overlap)}
            )
        else:
            reasons.append({"code": "location_mismatch", "points": 0.0})

    freshness = (_freshness_points(demand["date_utc"], now) + _freshness_points(supply["date_utc"], now)) / 2
    if freshness:
        score += freshness
        reasons.append({"code": "freshness", "points": round(freshness, 2)})

    extraction_confidence = (
        float(demand["confidence"] or 0.0) + float(supply["confidence"] or 0.0)
    ) / 2
    confidence_points = extraction_confidence * 10.0
    score += confidence_points
    reasons.append(
        {"code": "extraction_confidence", "points": round(confidence_points, 2)}
    )

    if supply["listing_type"] == "sale":
        score += 3.0
        reasons.append({"code": "direct_sale", "points": 3.0})

    score = round(min(100.0, score), 2)
    semantic_confidence = min(1.0, 0.55 * demand_coverage + 0.2 * jaccard + 0.25 * extraction_confidence)
    if not intersection and demand_category != "other":
        semantic_confidence *= 0.6
    confidence = round(max(0.0, semantic_confidence), 4)
    return MatchScore(True, score, confidence, tuple(reasons), None)


class MatchEngine:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        with self.conn() as c:
            c.executescript(MATCH_SCHEMA)

    @contextmanager
    def conn(self):
        c = sqlite3.connect(self.db_path, timeout=10)
        c.row_factory = sqlite3.Row
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    def get_state(self, key, default=None):
        with self.conn() as c:
            row = c.execute(
                "SELECT value FROM marketplace_match_state WHERE key=?", (key,)
            ).fetchone()
        return row["value"] if row else default

    def set_state(self, key, value):
        with self.conn() as c:
            c.execute(
                """INSERT INTO marketplace_match_state(key,value,updated_utc)
                   VALUES(?,?,?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_utc=excluded.updated_utc""",
                (key, str(value), utc_now()),
            )

    def notifications_enabled(self):
        return self.get_state("notifications_enabled", "1") == "1"

    def set_notifications_enabled(self, enabled):
        self.set_state("notifications_enabled", "1" if enabled else "0")

    def _listing_rows(self, *, demand):
        if demand:
            where = "l.listing_type='wanted' AND l.status='wanted'"
        else:
            where = "l.listing_type IN ('sale','trade','service') AND l.status='available'"
        sql = f"""SELECT l.*,m.text,m.date_utc,m.has_media,
                         c.title chat_title,c.username chat_username,
                         s.username sender_username,s.display_name
                  FROM marketplace_listings l
                  JOIN indexed_messages m ON m.chat_id=l.chat_id AND m.message_id=l.message_id
                  LEFT JOIN chats c ON c.chat_id=l.chat_id
                  LEFT JOIN senders s ON s.sender_id=l.sender_id
                  WHERE {where}
                  ORDER BY m.date_utc DESC,l.id DESC"""
        with self.conn() as c:
            rows = c.execute(sql).fetchall()
        latest = {}
        for row in rows:
            latest.setdefault(row["logical_listing_id"], row)
        return list(latest.values())

    def _status_for_new_pair(self, demand, supply, baseline_utc):
        if not baseline_utc:
            return "new"
        cutoff = _parse_dt(baseline_utc)
        if not cutoff:
            return "new"
        source_dates = [dt for dt in (_parse_dt(demand["date_utc"]), _parse_dt(supply["date_utc"])) if dt]
        if source_dates and max(source_dates) <= cutoff:
            return "baseline"
        return "new"

    def refresh_all(self, *, min_score=45.0, force_baseline=False):
        min_score = max(0.0, min(float(min_score), 100.0))
        now_text = utc_now()
        baseline_utc = self.get_state("baseline_completed_utc")
        demands = self._listing_rows(demand=True)
        supplies = self._listing_rows(demand=False)

        supplies_by_category = {}
        for supply in supplies:
            supplies_by_category.setdefault(supply["category"] or "other", []).append(supply)

        active_keys = set()
        created = 0
        updated = 0
        high_confidence = 0

        with self.conn() as c:
            for demand in demands:
                category = demand["category"] or "other"
                if category == "other":
                    candidates = supplies
                else:
                    candidates = supplies_by_category.get(category, []) + supplies_by_category.get("other", [])
                seen_supply = set()
                for supply in candidates:
                    supply_key = supply["logical_listing_id"]
                    if supply_key in seen_supply:
                        continue
                    seen_supply.add(supply_key)
                    result = score_marketplace_pair(demand, supply)
                    if not result.eligible or result.score < min_score:
                        continue
                    key = (demand["logical_listing_id"], supply["logical_listing_id"])
                    active_keys.add(key)
                    if result.score >= 65:
                        high_confidence += 1
                    existing = c.execute(
                        """SELECT id,status FROM marketplace_matches
                           WHERE demand_logical_id=? AND supply_logical_id=?""",
                        key,
                    ).fetchone()
                    if existing:
                        status = existing["status"]
                        if status == "inactive":
                            status = self._status_for_new_pair(demand, supply, baseline_utc)
                        c.execute(
                            """UPDATE marketplace_matches SET
                                   demand_listing_id=?,supply_listing_id=?,score=?,confidence=?,
                                   reasons_json=?,status=?,updated_utc=?
                               WHERE id=?""",
                            (
                                demand["id"], supply["id"], result.score, result.confidence,
                                json.dumps(result.reasons, separators=(",", ":")),
                                status, now_text, existing["id"],
                            ),
                        )
                        updated += 1
                    else:
                        status = "baseline" if force_baseline else self._status_for_new_pair(
                            demand, supply, baseline_utc
                        )
                        c.execute(
                            """INSERT INTO marketplace_matches(
                                   demand_logical_id,supply_logical_id,demand_listing_id,supply_listing_id,
                                   score,confidence,reasons_json,status,first_seen_utc,updated_utc
                               ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                            (
                                demand["logical_listing_id"], supply["logical_listing_id"],
                                demand["id"], supply["id"], result.score, result.confidence,
                                json.dumps(result.reasons, separators=(",", ":")),
                                status, now_text, now_text,
                            ),
                        )
                        created += 1

            rows = c.execute(
                """SELECT id,demand_logical_id,supply_logical_id,status
                   FROM marketplace_matches WHERE status NOT IN ('dismissed','accepted','inactive')"""
            ).fetchall()
            inactivated = 0
            for row in rows:
                key = (row["demand_logical_id"], row["supply_logical_id"])
                if key not in active_keys:
                    c.execute(
                        "UPDATE marketplace_matches SET status='inactive',updated_utc=? WHERE id=?",
                        (now_text, row["id"]),
                    )
                    inactivated += 1

        return {
            "demands": len(demands),
            "supplies": len(supplies),
            "active_pairs": len(active_keys),
            "high_confidence": high_confidence,
            "created": created,
            "updated": updated,
            "inactivated": inactivated,
        }

    def bootstrap(self, *, min_score=45.0):
        baseline = self.get_state("baseline_completed_utc")
        if baseline:
            return {"bootstrapped": False, "baseline_completed_utc": baseline, **self.refresh_all(min_score=min_score)}
        baseline = utc_now()
        result = self.refresh_all(min_score=min_score, force_baseline=True)
        self.set_state("baseline_completed_utc", baseline)
        self.set_state("notifications_enabled", self.get_state("notifications_enabled", "1"))
        return {"bootstrapped": True, "baseline_completed_utc": baseline, **result}

    def list_matches(self, *, min_score=0.0, limit=20, statuses=None):
        limit = max(1, min(int(limit), 100))
        min_score = max(0.0, min(float(min_score), 100.0))
        statuses = statuses or ACTIVE_MATCH_STATES
        placeholders = ",".join("?" for _ in statuses)
        args = list(statuses) + [min_score, limit]
        sql = f"""SELECT mm.*,
                          d.title demand_title,d.category demand_category,d.price_cents demand_budget,
                          d.chat_id demand_chat_id,d.message_id demand_message_id,d.location_hint demand_location,
                          s.title supply_title,s.category supply_category,s.price_cents supply_price,
                          s.chat_id supply_chat_id,s.message_id supply_message_id,s.location_hint supply_location,
                          dc.title demand_chat_title,sc.title supply_chat_title,
                          ds.username demand_username,ss.username supply_username
                   FROM marketplace_matches mm
                   JOIN marketplace_listings d ON d.id=mm.demand_listing_id
                   JOIN marketplace_listings s ON s.id=mm.supply_listing_id
                   LEFT JOIN chats dc ON dc.chat_id=d.chat_id
                   LEFT JOIN chats sc ON sc.chat_id=s.chat_id
                   LEFT JOIN senders ds ON ds.sender_id=d.sender_id
                   LEFT JOIN senders ss ON ss.sender_id=s.sender_id
                   WHERE mm.status IN ({placeholders}) AND mm.score>=?
                   ORDER BY mm.score DESC,mm.updated_utc DESC
                   LIMIT ?"""
        with self.conn() as c:
            return c.execute(sql, args).fetchall()

    def get_match(self, match_id):
        rows = self.list_matches(min_score=0, limit=100, statuses={"new", "baseline", "notified", "accepted", "dismissed", "inactive"})
        for row in rows:
            if int(row["id"]) == int(match_id):
                return row
        # Match count can exceed the normal list limit; fall back to a direct join.
        with self.conn() as c:
            return c.execute(
                """SELECT mm.*,
                          d.title demand_title,d.category demand_category,d.price_cents demand_budget,
                          d.chat_id demand_chat_id,d.message_id demand_message_id,d.location_hint demand_location,
                          s.title supply_title,s.category supply_category,s.price_cents supply_price,
                          s.chat_id supply_chat_id,s.message_id supply_message_id,s.location_hint supply_location,
                          dc.title demand_chat_title,sc.title supply_chat_title,
                          ds.username demand_username,ss.username supply_username
                   FROM marketplace_matches mm
                   JOIN marketplace_listings d ON d.id=mm.demand_listing_id
                   JOIN marketplace_listings s ON s.id=mm.supply_listing_id
                   LEFT JOIN chats dc ON dc.chat_id=d.chat_id
                   LEFT JOIN chats sc ON sc.chat_id=s.chat_id
                   LEFT JOIN senders ds ON ds.sender_id=d.sender_id
                   LEFT JOIN senders ss ON ss.sender_id=s.sender_id
                   WHERE mm.id=?""",
                (match_id,),
            ).fetchone()

    def record_feedback(self, match_id, user_id, verdict, note=None):
        verdict = (verdict or "").strip().lower()
        if verdict not in FEEDBACK_VERDICTS:
            raise ValueError("Unsupported match feedback verdict")
        match = self.get_match(match_id)
        if not match:
            return False
        now = utc_now()
        with self.conn() as c:
            c.execute(
                """INSERT INTO marketplace_match_feedback(match_id,user_id,verdict,note,created_utc)
                   VALUES(?,?,?,?,?)
                   ON CONFLICT(match_id,user_id) DO UPDATE SET
                     verdict=excluded.verdict,note=excluded.note,created_utc=excluded.created_utc""",
                (match_id, user_id, verdict, (note or "")[:500] or None, now),
            )
            if verdict == "accepted":
                c.execute(
                    "UPDATE marketplace_matches SET status='accepted',updated_utc=? WHERE id=?",
                    (now, match_id),
                )
            elif verdict in {"not_relevant", "ignore"}:
                c.execute(
                    "UPDATE marketplace_matches SET status='dismissed',updated_utc=? WHERE id=?",
                    (now, match_id),
                )
        return True

    def enqueue_new_alerts(self, owner_user_id, *, min_score=65.0, limit=50):
        if not owner_user_id or not self.notifications_enabled():
            return 0
        now = utc_now()
        min_score = max(0.0, min(float(min_score), 100.0))
        limit = max(1, min(int(limit), 200))
        with self.conn() as c:
            rows = c.execute(
                """SELECT id FROM marketplace_matches
                   WHERE status='new' AND score>=?
                   ORDER BY score DESC,first_seen_utc LIMIT ?""",
                (min_score, limit),
            ).fetchall()
            created = 0
            for row in rows:
                cur = c.execute(
                    """INSERT OR IGNORE INTO marketplace_match_alert_queue(
                           match_id,owner_user_id,status,attempts,due_utc,created_utc
                       ) VALUES(?,?, 'pending',0,?,?)""",
                    (row["id"], owner_user_id, now, now),
                )
                created += cur.rowcount
        return created

    def due_alerts(self, limit=20):
        limit = max(1, min(int(limit), 100))
        with self.conn() as c:
            return c.execute(
                """SELECT q.id alert_id,q.attempts,q.owner_user_id,mm.*,
                          d.title demand_title,d.price_cents demand_budget,d.chat_id demand_chat_id,
                          s.title supply_title,s.price_cents supply_price,s.chat_id supply_chat_id,
                          dc.title demand_chat_title,sc.title supply_chat_title
                   FROM marketplace_match_alert_queue q
                   JOIN marketplace_matches mm ON mm.id=q.match_id AND mm.status='new'
                   JOIN marketplace_listings d ON d.id=mm.demand_listing_id
                   JOIN marketplace_listings s ON s.id=mm.supply_listing_id
                   LEFT JOIN chats dc ON dc.chat_id=d.chat_id
                   LEFT JOIN chats sc ON sc.chat_id=s.chat_id
                   WHERE q.status IN ('pending','retry') AND q.due_utc<=?
                   ORDER BY mm.score DESC,q.due_utc,q.id LIMIT ?""",
                (utc_now(), limit),
            ).fetchall()

    def mark_alert_sent(self, alert_id, match_id):
        now = utc_now()
        with self.conn() as c:
            c.execute(
                "UPDATE marketplace_match_alert_queue SET status='sent',sent_utc=?,last_error=NULL WHERE id=?",
                (now, alert_id),
            )
            c.execute(
                """UPDATE marketplace_matches SET status='notified',notified_utc=?,updated_utc=?
                   WHERE id=? AND status='new'""",
                (now, now, match_id),
            )

    def mark_alert_retry(self, alert_id, error, attempts):
        attempts = int(attempts) + 1
        delay = min(3600, 30 * (2 ** min(attempts - 1, 7)))
        due = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()
        status = "failed" if attempts >= 5 else "retry"
        with self.conn() as c:
            c.execute(
                """UPDATE marketplace_match_alert_queue
                   SET status=?,attempts=?,due_utc=?,last_error=? WHERE id=?""",
                (status, attempts, due, str(error)[:500], alert_id),
            )
        return status, due

    def cleanup_alert_history(self, *, sent_days=30, failed_days=90):
        sent_cutoff = (datetime.now(timezone.utc) - timedelta(days=max(1, sent_days))).isoformat()
        failed_cutoff = (datetime.now(timezone.utc) - timedelta(days=max(1, failed_days))).isoformat()
        with self.conn() as c:
            sent = c.execute(
                "DELETE FROM marketplace_match_alert_queue WHERE status='sent' AND sent_utc<?",
                (sent_cutoff,),
            ).rowcount
            failed = c.execute(
                "DELETE FROM marketplace_match_alert_queue WHERE status='failed' AND created_utc<?",
                (failed_cutoff,),
            ).rowcount
        return sent + failed

    def stats(self):
        with self.conn() as c:
            matches = c.execute(
                """SELECT COUNT(*) total,
                          SUM(status IN ('new','baseline','notified','accepted')) active,
                          SUM(status='new') new_count,
                          SUM(score>=65 AND status IN ('new','baseline','notified','accepted')) high_confidence
                   FROM marketplace_matches"""
            ).fetchone()
            feedback = c.execute(
                "SELECT verdict,COUNT(*) count FROM marketplace_match_feedback GROUP BY verdict"
            ).fetchall()
        return matches, feedback
