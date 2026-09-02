import importlib
import json
from datetime import datetime, timedelta, timezone

from core import utc_now
from match_engine import score_marketplace_pair
from match_runtime import HardenedMatchEngine


SUPPLY_TYPES = {"sale", "trade", "service"}
POSITIVE_FEEDBACK = {"relevant", "accepted"}
NEGATIVE_FEEDBACK = {"not_relevant", "ignore"}
ALL_FEEDBACK = POSITIVE_FEEDBACK | NEGATIVE_FEEDBACK


def _parse_dt(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat()


class MatchEngineV2(HardenedMatchEngine):
    """Incremental two-way demand/supply matching with conservative learning.

    v1.5 remains the source of truth for pair scoring and match persistence.
    v2 adds durable change events, SQL candidate pre-filtering, WTB lifecycle
    reminders, and feedback-derived threshold recommendations. It never changes
    the notification threshold automatically.
    """

    def __init__(self, db_path):
        super().__init__(db_path)
        migration = importlib.import_module("migrations.0007_match_feedback")
        with self.conn() as c:
            migration.upgrade(c)

    # ------------------------------------------------------------------
    # v2 state / event queue
    # ------------------------------------------------------------------
    def get_v2_state(self, key, default=None):
        with self.conn() as c:
            row = c.execute(
                "SELECT value FROM marketplace_match_v2_state WHERE key=?", (key,)
            ).fetchone()
        return row["value"] if row else default

    def set_v2_state(self, key, value):
        with self.conn() as c:
            c.execute(
                """INSERT INTO marketplace_match_v2_state(key,value,updated_utc)
                   VALUES(?,?,?)
                   ON CONFLICT(key) DO UPDATE SET
                     value=excluded.value,updated_utc=excluded.updated_utc""",
                (key, str(value), utc_now()),
            )

    def event_backlog_count(self):
        with self.conn() as c:
            return int(
                c.execute(
                    "SELECT COUNT(*) FROM marketplace_match_events WHERE processed_utc IS NULL"
                ).fetchone()[0]
            )

    def _joined_listing_sql(self):
        return """SELECT l.*,m.text,m.date_utc,m.has_media,
                         c.title chat_title,c.username chat_username,
                         s.username sender_username,s.display_name
                  FROM marketplace_listings l
                  JOIN indexed_messages m
                    ON m.chat_id=l.chat_id AND m.message_id=l.message_id
                  LEFT JOIN chats c ON c.chat_id=l.chat_id
                  LEFT JOIN senders s ON s.sender_id=l.sender_id"""

    def _active_representative(self, logical_id):
        sql = self._joined_listing_sql() + """
                 WHERE l.logical_listing_id=?
                   AND ((l.listing_type='wanted' AND l.status='wanted')
                     OR (l.listing_type IN ('sale','trade','service') AND l.status='available'))
                 ORDER BY m.date_utc DESC,l.id DESC LIMIT 1"""
        with self.conn() as c:
            return c.execute(sql, (logical_id,)).fetchone()

    @staticmethod
    def _dedupe_logical(rows):
        latest = {}
        for row in rows:
            latest.setdefault(row["logical_listing_id"], row)
        return list(latest.values())

    def candidate_supplies_for_demand(self, demand, *, limit=500):
        """SQL pre-filter supply before Python semantic scoring."""
        limit = max(1, min(int(limit), 2000))
        category = demand["category"] or "other"
        sender_id = demand["sender_id"]
        budget = demand["price_cents"]
        sql = self._joined_listing_sql() + """
                 WHERE l.listing_type IN ('sale','trade','service')
                   AND l.status='available'
                   AND l.logical_listing_id<>?
                   AND (?='other' OR l.category='other' OR l.category=?)
                   AND (? IS NULL OR l.sender_id IS NULL OR l.sender_id<>?)
                   AND (? IS NULL OR l.price_cents IS NULL OR l.price_cents<=?)
                 ORDER BY m.date_utc DESC,l.id DESC
                 LIMIT ?"""
        args = (
            demand["logical_listing_id"],
            category,
            category,
            sender_id,
            sender_id,
            budget,
            budget,
            limit,
        )
        with self.conn() as c:
            rows = c.execute(sql, args).fetchall()
        return self._dedupe_logical(rows)

    def candidate_demands_for_supply(self, supply, *, limit=500):
        """SQL pre-filter WTB demand when a supply listing changes."""
        limit = max(1, min(int(limit), 2000))
        category = supply["category"] or "other"
        sender_id = supply["sender_id"]
        price = supply["price_cents"]
        sql = self._joined_listing_sql() + """
                 WHERE l.listing_type='wanted'
                   AND l.status='wanted'
                   AND l.logical_listing_id<>?
                   AND (?='other' OR l.category='other' OR l.category=?)
                   AND (? IS NULL OR l.sender_id IS NULL OR l.sender_id<>?)
                   AND (l.price_cents IS NULL OR ? IS NULL OR ?>=?)
                 ORDER BY m.date_utc DESC,l.id DESC
                 LIMIT ?"""
        args = (
            supply["logical_listing_id"],
            category,
            category,
            sender_id,
            sender_id,
            price,
            price,
            price,
            limit,
        )
        with self.conn() as c:
            rows = c.execute(sql, args).fetchall()
        return self._dedupe_logical(rows)

    def _upsert_scored_pair(self, demand, supply, result):
        now = utc_now()
        key = (demand["logical_listing_id"], supply["logical_listing_id"])
        baseline_utc = self.get_state("baseline_completed_utc")
        with self.conn() as c:
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
                        demand["id"],
                        supply["id"],
                        result.score,
                        result.confidence,
                        json.dumps(result.reasons, separators=(",", ":")),
                        status,
                        now,
                        existing["id"],
                    ),
                )
                return int(existing["id"]), False

            status = self._status_for_new_pair(demand, supply, baseline_utc)
            cur = c.execute(
                """INSERT INTO marketplace_matches(
                       demand_logical_id,supply_logical_id,demand_listing_id,supply_listing_id,
                       score,confidence,reasons_json,status,first_seen_utc,updated_utc
                   ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    demand["logical_listing_id"],
                    supply["logical_listing_id"],
                    demand["id"],
                    supply["id"],
                    result.score,
                    result.confidence,
                    json.dumps(result.reasons, separators=(",", ":")),
                    status,
                    now,
                    now,
                ),
            )
            return int(cur.lastrowid), True

    def _inactivate_missing_pairs(self, logical_id, active_keys):
        now = utc_now()
        with self.conn() as c:
            rows = c.execute(
                """SELECT id,demand_logical_id,supply_logical_id,status
                   FROM marketplace_matches
                   WHERE (demand_logical_id=? OR supply_logical_id=?)
                     AND status NOT IN ('accepted','dismissed','inactive')""",
                (logical_id, logical_id),
            ).fetchall()
            changed = 0
            for row in rows:
                key = (row["demand_logical_id"], row["supply_logical_id"])
                if key not in active_keys:
                    c.execute(
                        "UPDATE marketplace_matches SET status='inactive',updated_utc=? WHERE id=?",
                        (now, row["id"]),
                    )
                    changed += 1
        return changed

    def reconcile_logical_listing(self, logical_id, *, min_score=45.0, candidate_limit=500):
        min_score = max(0.0, min(float(min_score), 100.0))
        representative = self._active_representative(logical_id)
        if not representative:
            inactivated = self._inactivate_missing_pairs(logical_id, set())
            self.cancel_wtb_expiry(logical_id)
            return {
                "logical_id": logical_id,
                "active": False,
                "pairs_evaluated": 0,
                "eligible_pairs": 0,
                "created": 0,
                "updated": 0,
                "inactivated": inactivated,
            }

        active_keys = set()
        evaluated = 0
        eligible = 0
        created = 0
        updated = 0

        if representative["listing_type"] == "wanted":
            self.ensure_wtb_expiry(representative)
            candidates = self.candidate_supplies_for_demand(
                representative, limit=candidate_limit
            )
            oriented = ((representative, supply) for supply in candidates)
        else:
            candidates = self.candidate_demands_for_supply(
                representative, limit=candidate_limit
            )
            oriented = ((demand, representative) for demand in candidates)

        for demand, supply in oriented:
            evaluated += 1
            result = score_marketplace_pair(demand, supply)
            if not result.eligible or result.score < min_score:
                continue
            eligible += 1
            key = (demand["logical_listing_id"], supply["logical_listing_id"])
            active_keys.add(key)
            _, was_created = self._upsert_scored_pair(demand, supply, result)
            if was_created:
                created += 1
            else:
                updated += 1

        inactivated = self._inactivate_missing_pairs(logical_id, active_keys)
        return {
            "logical_id": logical_id,
            "active": True,
            "listing_type": representative["listing_type"],
            "pairs_evaluated": evaluated,
            "eligible_pairs": eligible,
            "created": created,
            "updated": updated,
            "inactivated": inactivated,
        }

    def process_events(self, *, limit=250, min_score=45.0, candidate_limit=500):
        """Consume durable marketplace changes and reconcile impacted listings."""
        limit = max(1, min(int(limit), 2000))
        with self.conn() as c:
            events = c.execute(
                """SELECT * FROM marketplace_match_events
                   WHERE processed_utc IS NULL ORDER BY id LIMIT ?""",
                (limit,),
            ).fetchall()
        if not events:
            return {
                "events": 0,
                "impacted_logical": 0,
                "pairs_evaluated": 0,
                "eligible_pairs": 0,
                "created": 0,
                "updated": 0,
                "inactivated": 0,
                "cancelled_alerts": self.cancel_stale_alerts(),
                "backlog": 0,
            }

        impacted = set()
        ids = []
        for event in events:
            ids.append(int(event["id"]))
            if event["previous_logical_listing_id"]:
                impacted.add(event["previous_logical_listing_id"])
            if event["logical_listing_id"]:
                impacted.add(event["logical_listing_id"])

        totals = {
            "pairs_evaluated": 0,
            "eligible_pairs": 0,
            "created": 0,
            "updated": 0,
            "inactivated": 0,
        }
        for logical_id in sorted(impacted):
            result = self.reconcile_logical_listing(
                logical_id,
                min_score=min_score,
                candidate_limit=candidate_limit,
            )
            for key in totals:
                totals[key] += int(result.get(key, 0))

        now = utc_now()
        placeholders = ",".join("?" for _ in ids)
        with self.conn() as c:
            c.execute(
                f"UPDATE marketplace_match_events SET processed_utc=? WHERE id IN ({placeholders})",
                [now, *ids],
            )
        self.set_v2_state("last_event_processed_utc", now)
        cancelled = self.cancel_stale_alerts()
        return {
            "events": len(events),
            "impacted_logical": len(impacted),
            **totals,
            "cancelled_alerts": cancelled,
            "backlog": self.event_backlog_count(),
        }

    # ------------------------------------------------------------------
    # WTB expiry / reminder state
    # ------------------------------------------------------------------
    def ensure_wtb_expiry(
        self,
        demand,
        *,
        ttl_days=30,
        reminder_lead_days=7,
        baseline_mode=False,
    ):
        ttl_days = max(1, min(int(ttl_days), 365))
        reminder_lead_days = max(1, min(int(reminder_lead_days), ttl_days))
        first_seen = (
            _parse_dt(demand["first_seen_utc"])
            or _parse_dt(demand["date_utc"])
            or datetime.now(timezone.utc)
        )
        expires = first_seen + timedelta(days=ttl_days)
        remind = expires - timedelta(days=reminder_lead_days)
        now = datetime.now(timezone.utc)

        with self.conn() as c:
            existing = c.execute(
                "SELECT * FROM marketplace_wtb_expiry WHERE demand_logical_id=?",
                (demand["logical_listing_id"],),
            ).fetchone()
            if existing and existing["status"] in {"reminded", "dismissed", "baseline"}:
                status = existing["status"]
            elif baseline_mode and remind <= now:
                status = "baseline"
            else:
                status = "scheduled"
            c.execute(
                """INSERT INTO marketplace_wtb_expiry(
                       demand_logical_id,listing_id,first_seen_utc,remind_utc,expires_utc,
                       status,created_utc,updated_utc
                   ) VALUES(?,?,?,?,?,?,?,?)
                   ON CONFLICT(demand_logical_id) DO UPDATE SET
                     listing_id=excluded.listing_id,
                     first_seen_utc=excluded.first_seen_utc,
                     remind_utc=excluded.remind_utc,
                     expires_utc=excluded.expires_utc,
                     status=?,updated_utc=excluded.updated_utc""",
                (
                    demand["logical_listing_id"],
                    demand["id"],
                    _iso(first_seen),
                    _iso(remind),
                    _iso(expires),
                    status,
                    utc_now(),
                    utc_now(),
                    status,
                ),
            )
        return {
            "demand_logical_id": demand["logical_listing_id"],
            "remind_utc": _iso(remind),
            "expires_utc": _iso(expires),
            "status": status,
        }

    def cancel_wtb_expiry(self, logical_id):
        with self.conn() as c:
            cur = c.execute(
                """UPDATE marketplace_wtb_expiry
                   SET status='inactive',updated_utc=?
                   WHERE demand_logical_id=? AND status IN ('scheduled','baseline')""",
                (utc_now(), logical_id),
            )
            c.execute(
                """UPDATE marketplace_wtb_expiry_alert_queue
                   SET status='cancelled',last_error='WTB no longer active'
                   WHERE demand_logical_id=? AND status IN ('pending','retry')""",
                (logical_id,),
            )
        return int(cur.rowcount)

    def refresh_wtb_expiry(self, *, ttl_days=30, reminder_lead_days=7, baseline_mode=False):
        demands = self._listing_rows(demand=True)
        active = set()
        scheduled = 0
        for demand in demands:
            active.add(demand["logical_listing_id"])
            self.ensure_wtb_expiry(
                demand,
                ttl_days=ttl_days,
                reminder_lead_days=reminder_lead_days,
                baseline_mode=baseline_mode,
            )
            scheduled += 1

        with self.conn() as c:
            rows = c.execute(
                "SELECT demand_logical_id FROM marketplace_wtb_expiry WHERE status IN ('scheduled','baseline')"
            ).fetchall()
        cancelled = 0
        for row in rows:
            if row["demand_logical_id"] not in active:
                cancelled += self.cancel_wtb_expiry(row["demand_logical_id"])
        return {"active_demands": len(active), "scheduled_checked": scheduled, "cancelled": cancelled}

    def bootstrap_v2(self, *, min_score=45.0, ttl_days=30, reminder_lead_days=7):
        base = self.bootstrap(min_score=min_score)
        existing = self.get_v2_state("baseline_completed_utc")
        if existing:
            expiry = self.refresh_wtb_expiry(
                ttl_days=ttl_days,
                reminder_lead_days=reminder_lead_days,
                baseline_mode=False,
            )
            return {"v2_bootstrapped": False, "v2_baseline_completed_utc": existing, "base": base, "expiry": expiry}

        expiry = self.refresh_wtb_expiry(
            ttl_days=ttl_days,
            reminder_lead_days=reminder_lead_days,
            baseline_mode=True,
        )
        completed = utc_now()
        self.set_v2_state("baseline_completed_utc", completed)
        return {"v2_bootstrapped": True, "v2_baseline_completed_utc": completed, "base": base, "expiry": expiry}

    def due_wtb_expiry(self, limit=50):
        limit = max(1, min(int(limit), 200))
        now = utc_now()
        sql = self._joined_listing_sql() + """
                 JOIN marketplace_wtb_expiry e ON e.listing_id=l.id
                 WHERE e.status='scheduled' AND e.remind_utc<=?
                   AND l.listing_type='wanted' AND l.status='wanted'
                 ORDER BY e.remind_utc,e.demand_logical_id LIMIT ?"""
        with self.conn() as c:
            return c.execute(sql, (now, limit)).fetchall()

    def enqueue_due_wtb_expiry_alerts(self, owner_user_id, *, limit=50):
        if not owner_user_id or not self.notifications_enabled():
            return 0
        rows = self.due_wtb_expiry(limit=limit)
        now = utc_now()
        created = 0
        with self.conn() as c:
            for row in rows:
                cur = c.execute(
                    """INSERT OR IGNORE INTO marketplace_wtb_expiry_alert_queue(
                           demand_logical_id,owner_user_id,status,attempts,due_utc,created_utc
                       ) VALUES(?,?, 'pending',0,?,?)""",
                    (row["logical_listing_id"], int(owner_user_id), now, now),
                )
                created += cur.rowcount
        return created

    def due_wtb_expiry_alerts(self, limit=20):
        limit = max(1, min(int(limit), 100))
        sql = self._joined_listing_sql() + """
                 JOIN marketplace_wtb_expiry e ON e.listing_id=l.id
                 JOIN marketplace_wtb_expiry_alert_queue q
                   ON q.demand_logical_id=e.demand_logical_id
                 WHERE q.status IN ('pending','retry') AND q.due_utc<=?
                   AND e.status='scheduled'
                   AND l.listing_type='wanted' AND l.status='wanted'
                 ORDER BY q.due_utc,q.id LIMIT ?"""
        with self.conn() as c:
            rows = c.execute(sql, (utc_now(), limit)).fetchall()
            # Re-query queue metadata separately to avoid ambiguous joined id fields.
            result = []
            for row in rows:
                q = c.execute(
                    """SELECT id alert_id,attempts,owner_user_id
                       FROM marketplace_wtb_expiry_alert_queue
                       WHERE demand_logical_id=? AND status IN ('pending','retry')
                       ORDER BY id LIMIT 1""",
                    (row["logical_listing_id"],),
                ).fetchone()
                if q:
                    result.append((row, q))
        return result

    def mark_wtb_expiry_alert_sent(self, alert_id, logical_id):
        now = utc_now()
        with self.conn() as c:
            c.execute(
                """UPDATE marketplace_wtb_expiry_alert_queue
                   SET status='sent',sent_utc=?,last_error=NULL WHERE id=?""",
                (now, int(alert_id)),
            )
            c.execute(
                """UPDATE marketplace_wtb_expiry
                   SET status='reminded',reminded_utc=?,updated_utc=?
                   WHERE demand_logical_id=? AND status='scheduled'""",
                (now, now, logical_id),
            )

    def mark_wtb_expiry_alert_retry(self, alert_id, error, attempts):
        attempts = int(attempts) + 1
        delay = min(3600, 30 * (2 ** min(attempts - 1, 7)))
        due = datetime.now(timezone.utc) + timedelta(seconds=delay)
        status = "failed" if attempts >= 5 else "retry"
        with self.conn() as c:
            c.execute(
                """UPDATE marketplace_wtb_expiry_alert_queue
                   SET status=?,attempts=?,due_utc=?,last_error=? WHERE id=?""",
                (status, attempts, _iso(due), str(error)[:500], int(alert_id)),
            )
        return status, _iso(due)

    def cancel_stale_wtb_expiry_alerts(self, owner_user_id=None):
        args = []
        owner_sql = ""
        if owner_user_id:
            owner_sql = " OR q.owner_user_id<>?"
            args.append(int(owner_user_id))
        with self.conn() as c:
            cur = c.execute(
                """UPDATE marketplace_wtb_expiry_alert_queue AS q
                   SET status='cancelled',last_error='WTB reminder no longer deliverable'
                   WHERE q.status IN ('pending','retry') AND (
                     NOT EXISTS(
                       SELECT 1 FROM marketplace_wtb_expiry e
                       JOIN marketplace_listings l ON l.id=e.listing_id
                       WHERE e.demand_logical_id=q.demand_logical_id
                         AND e.status='scheduled'
                         AND l.listing_type='wanted' AND l.status='wanted'
                     )""" + owner_sql + ")",
                args,
            )
        return int(cur.rowcount)

    def cleanup_wtb_expiry_alert_history(self, *, sent_days=30, failed_days=90, cancelled_days=30):
        sent_cutoff = _iso(datetime.now(timezone.utc) - timedelta(days=max(1, int(sent_days))))
        failed_cutoff = _iso(datetime.now(timezone.utc) - timedelta(days=max(1, int(failed_days))))
        cancelled_cutoff = _iso(datetime.now(timezone.utc) - timedelta(days=max(1, int(cancelled_days))))
        with self.conn() as c:
            sent = c.execute(
                "DELETE FROM marketplace_wtb_expiry_alert_queue WHERE status='sent' AND sent_utc<?",
                (sent_cutoff,),
            ).rowcount
            failed = c.execute(
                "DELETE FROM marketplace_wtb_expiry_alert_queue WHERE status='failed' AND created_utc<?",
                (failed_cutoff,),
            ).rowcount
            cancelled = c.execute(
                "DELETE FROM marketplace_wtb_expiry_alert_queue WHERE status='cancelled' AND created_utc<?",
                (cancelled_cutoff,),
            ).rowcount
        return int(sent + failed + cancelled)

    # ------------------------------------------------------------------
    # Demand analytics / conservative calibration
    # ------------------------------------------------------------------
    def calibration_summary(self, *, current_threshold=65.0, min_samples=20):
        current_threshold = max(0.0, min(float(current_threshold), 100.0))
        min_samples = max(5, int(min_samples))
        with self.conn() as c:
            rows = c.execute(
                """SELECT f.verdict,m.score
                   FROM marketplace_match_feedback f
                   JOIN marketplace_matches m ON m.id=f.match_id
                   WHERE f.verdict IN ('relevant','accepted','not_relevant','ignore')"""
            ).fetchall()

        labelled = [(row["verdict"], float(row["score"])) for row in rows]
        positives = sum(1 for verdict, _ in labelled if verdict in POSITIVE_FEEDBACK)
        negatives = sum(1 for verdict, _ in labelled if verdict in NEGATIVE_FEEDBACK)

        def metrics(threshold):
            selected = [(v, s) for v, s in labelled if s >= threshold]
            pos = sum(1 for v, _ in selected if v in POSITIVE_FEEDBACK)
            neg = sum(1 for v, _ in selected if v in NEGATIVE_FEEDBACK)
            total = pos + neg
            precision = (pos / total) if total else None
            return {
                "threshold": float(threshold),
                "samples": total,
                "positive": pos,
                "negative": neg,
                "precision": None if precision is None else round(precision, 4),
            }

        current = metrics(current_threshold)
        recommended = current_threshold
        reason = "insufficient_feedback"
        enough = len(labelled) >= min_samples
        if enough:
            precision = current["precision"]
            if precision is not None and current["samples"] >= 10 and precision < 0.80:
                recommended = min(85.0, current_threshold + 5.0)
                reason = "raise_threshold_to_reduce_false_positives"
            elif (
                precision is not None
                and precision >= 0.90
                and len(labelled) >= max(30, min_samples)
                and current_threshold >= 60
            ):
                lower = metrics(current_threshold - 5.0)
                if (
                    lower["samples"] >= 10
                    and lower["precision"] is not None
                    and lower["precision"] >= 0.85
                ):
                    recommended = current_threshold - 5.0
                    reason = "lower_threshold_one_step_with_strong_precision"
                else:
                    reason = "keep_threshold_lower_step_not_supported"
            else:
                reason = "keep_threshold_evidence_stable"

        return {
            "labelled": len(labelled),
            "positive": positives,
            "negative": negatives,
            "minimum_samples": min_samples,
            "enough_feedback": enough,
            "current": current,
            "recommended_threshold": float(recommended),
            "recommendation_reason": reason,
            "automatic_change": False,
        }

    def demand_stats(self, *, alert_threshold=65.0):
        demands = self._listing_rows(demand=True)
        active_ids = {row["logical_listing_id"] for row in demands}
        budgets = [int(row["price_cents"]) for row in demands if row["price_cents"] is not None]
        categories = {}
        for demand in demands:
            category = demand["category"] or "other"
            categories[category] = categories.get(category, 0) + 1

        with self.conn() as c:
            matched_rows = c.execute(
                """SELECT DISTINCT demand_logical_id FROM marketplace_matches
                   WHERE status IN ('new','baseline','notified','accepted')"""
            ).fetchall()
            now = utc_now()
            next_7d = _iso(datetime.now(timezone.utc) + timedelta(days=7))
            expiring = c.execute(
                """SELECT COUNT(*) FROM marketplace_wtb_expiry
                   WHERE status='scheduled' AND expires_utc>? AND expires_utc<=?""",
                (now, next_7d),
            ).fetchone()[0]
            overdue = c.execute(
                """SELECT COUNT(*) FROM marketplace_wtb_expiry
                   WHERE status='scheduled' AND expires_utc<=?""",
                (now,),
            ).fetchone()[0]
            expiry_queue = c.execute(
                """SELECT status,COUNT(*) count FROM marketplace_wtb_expiry_alert_queue
                   GROUP BY status"""
            ).fetchall()

        matched = {row["demand_logical_id"] for row in matched_rows} & active_ids
        average_budget = int(sum(budgets) / len(budgets)) if budgets else None
        return {
            "active_wtb": len(active_ids),
            "matched_wtb": len(matched),
            "unmatched_wtb": max(0, len(active_ids) - len(matched)),
            "average_budget_cents": average_budget,
            "expiring_within_7d": int(expiring or 0),
            "overdue_reminder": int(overdue or 0),
            "event_backlog": self.event_backlog_count(),
            "categories": dict(sorted(categories.items(), key=lambda item: (-item[1], item[0]))[:8]),
            "expiry_alert_queue": {row["status"]: int(row["count"]) for row in expiry_queue},
            "calibration": self.calibration_summary(current_threshold=alert_threshold),
        }
