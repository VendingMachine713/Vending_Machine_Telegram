from datetime import datetime, timedelta, timezone

from core import utc_now
from match_engine import MatchEngine


class HardenedMatchEngine(MatchEngine):
    """Operational hardening around the v1.5 matching core.

    The base MatchEngine owns scoring and durable match persistence. This layer
    keeps outbound alert state aligned with match lifecycle and the current set
    of authorised VM owners. It deliberately separates match lifecycle from
    per-owner delivery lifecycle so one owner's successful alert cannot cancel
    another authorised owner's already-queued delivery.
    """

    @staticmethod
    def _normalized_owner_ids(owner_user_ids):
        result = set()
        if isinstance(owner_user_ids, (int, str)):
            owner_user_ids = (owner_user_ids,)
        for value in owner_user_ids or ():
            try:
                uid = int(value)
            except (TypeError, ValueError):
                continue
            if uid > 0:
                result.add(uid)
        return tuple(sorted(result))

    def cancel_stale_alerts(self, match_id=None):
        """Cancel queued alerts whose match is no longer deliverable.

        `notified` remains deliverable for a queue row that was already created
        for another authorised owner before the first owner received the match.
        No new alert rows are created for notified historical matches.
        """
        args = []
        match_filter = ""
        if match_id is not None:
            match_filter = " AND q.match_id=?"
            args.append(int(match_id))
        with self.conn() as c:
            rows = c.execute(
                """SELECT q.id
                   FROM marketplace_match_alert_queue q
                   LEFT JOIN marketplace_matches mm ON mm.id=q.match_id
                   WHERE q.status IN ('pending','retry')
                     AND (mm.id IS NULL OR mm.status NOT IN ('new','notified'))"""
                + match_filter,
                args,
            ).fetchall()
            if not rows:
                return 0
            ids = [int(row["id"]) for row in rows]
            placeholders = ",".join("?" for _ in ids)
            c.execute(
                f"""UPDATE marketplace_match_alert_queue
                    SET status='cancelled',last_error='match no longer alertable'
                    WHERE id IN ({placeholders})""",
                ids,
            )
        return len(ids)

    def reconcile_alert_owners(self, owner_user_ids):
        """Fail closed against the complete currently-authorised owner set.

        Pending/retry alerts for superseded owners are cancelled before the
        daemon reads the queue. An empty owner set cancels all undelivered alert
        rows. Sent/failed history is retained for diagnostics/retention cleanup.
        """
        owners = self._normalized_owner_ids(owner_user_ids)
        with self.conn() as c:
            if owners:
                marks = ",".join("?" for _ in owners)
                cur = c.execute(
                    f"""UPDATE marketplace_match_alert_queue
                        SET status='cancelled',last_error='owner superseded'
                        WHERE status IN ('pending','retry')
                          AND owner_user_id NOT IN ({marks})""",
                    owners,
                )
            else:
                cur = c.execute(
                    """UPDATE marketplace_match_alert_queue
                       SET status='cancelled',last_error='no authorized owner'
                       WHERE status IN ('pending','retry')"""
                )
        return int(cur.rowcount)

    def cancel_wrong_owner_alerts(self, owner_user_id):
        """Backward-compatible single-owner wrapper."""
        return self.reconcile_alert_owners((owner_user_id,) if owner_user_id else ())

    def enqueue_new_alerts_for_owners(self, owner_user_ids, *, min_score=65.0, limit=50):
        owners = self._normalized_owner_ids(owner_user_ids)
        if not owners or not self.notifications_enabled():
            return 0
        created = 0
        for owner in owners:
            created += self.enqueue_new_alerts(owner, min_score=min_score, limit=limit)
        return created

    def due_alerts_for_owners(self, owner_user_ids, limit=20):
        """Return due rows only for currently-authorised owners.

        A match may already be `notified` because another authorised owner got
        its copy. Existing pending/retry rows remain deliverable in that state.
        """
        owners = self._normalized_owner_ids(owner_user_ids)
        if not owners:
            return []
        limit = max(1, min(int(limit), 100))
        marks = ",".join("?" for _ in owners)
        with self.conn() as c:
            return c.execute(
                f"""SELECT q.id alert_id,q.attempts,q.owner_user_id,mm.*,
                           d.title demand_title,d.price_cents demand_budget,d.chat_id demand_chat_id,
                           s.title supply_title,s.price_cents supply_price,s.chat_id supply_chat_id,
                           dc.title demand_chat_title,sc.title supply_chat_title
                    FROM marketplace_match_alert_queue q
                    JOIN marketplace_matches mm
                      ON mm.id=q.match_id AND mm.status IN ('new','notified')
                    JOIN marketplace_listings d ON d.id=mm.demand_listing_id
                    JOIN marketplace_listings s ON s.id=mm.supply_listing_id
                    LEFT JOIN chats dc ON dc.chat_id=d.chat_id
                    LEFT JOIN chats sc ON sc.chat_id=s.chat_id
                    WHERE q.status IN ('pending','retry') AND q.due_utc<=?
                      AND q.owner_user_id IN ({marks})
                    ORDER BY mm.score DESC,q.due_utc,q.id LIMIT ?""",
                [utc_now(), *owners, limit],
            ).fetchall()

    def refresh_all(self, *, min_score=45.0, force_baseline=False):
        result = super().refresh_all(min_score=min_score, force_baseline=force_baseline)
        result["cancelled_alerts"] = self.cancel_stale_alerts()
        return result

    def record_feedback(self, match_id, user_id, verdict, note=None):
        changed = super().record_feedback(match_id, user_id, verdict, note)
        if changed and (verdict or "").strip().lower() in {"accepted", "not_relevant", "ignore"}:
            self.cancel_stale_alerts(match_id)
        return changed

    def queue_status(self):
        with self.conn() as c:
            rows = c.execute(
                """SELECT status,COUNT(*) count
                   FROM marketplace_match_alert_queue
                   GROUP BY status ORDER BY status"""
            ).fetchall()
        return {row["status"]: int(row["count"]) for row in rows}

    def queue_status_by_owner(self):
        with self.conn() as c:
            rows = c.execute(
                """SELECT owner_user_id,status,COUNT(*) count
                   FROM marketplace_match_alert_queue
                   GROUP BY owner_user_id,status
                   ORDER BY owner_user_id,status"""
            ).fetchall()
        result = {}
        for row in rows:
            result.setdefault(int(row["owner_user_id"]), {})[row["status"]] = int(row["count"])
        return result

    def retry_failed_alerts(self, owner_user_id=None, *, limit=50):
        """Requeue failures only while the underlying opportunity is active.

        `notified` is included because another owner may already have received
        the match while this owner's delivery exhausted its retry budget.
        """
        limit = max(1, min(int(limit), 200))
        args = []
        owner_sql = ""
        if owner_user_id:
            owner_sql = " AND q.owner_user_id=?"
            args.append(int(owner_user_id))
        args.append(limit)
        now = utc_now()
        with self.conn() as c:
            rows = c.execute(
                """SELECT q.id
                   FROM marketplace_match_alert_queue q
                   JOIN marketplace_matches mm ON mm.id=q.match_id
                   WHERE q.status='failed' AND mm.status IN ('new','notified')"""
                + owner_sql
                + " ORDER BY q.id LIMIT ?",
                args,
            ).fetchall()
            if not rows:
                return 0
            ids = [int(row["id"]) for row in rows]
            placeholders = ",".join("?" for _ in ids)
            c.execute(
                f"""UPDATE marketplace_match_alert_queue
                    SET status='retry',attempts=0,due_utc=?,last_error=NULL
                    WHERE id IN ({placeholders})""",
                [now, *ids],
            )
        return len(ids)

    def cleanup_alert_history(self, *, sent_days=30, failed_days=90, cancelled_days=30):
        removed = super().cleanup_alert_history(sent_days=sent_days, failed_days=failed_days)
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=max(1, int(cancelled_days)))
        ).isoformat()
        with self.conn() as c:
            removed += c.execute(
                """DELETE FROM marketplace_match_alert_queue
                   WHERE status='cancelled' AND created_utc<?""",
                (cutoff,),
            ).rowcount
        return removed
