from datetime import datetime, timedelta, timezone

from core import utc_now
from match_engine import MatchEngine


class HardenedMatchEngine(MatchEngine):
    """Operational hardening around the v1.5 matching core.

    The base MatchEngine owns scoring and match persistence. This subclass keeps
    the alert queue aligned with match lifecycle state and provides explicit
    operator recovery controls without changing the matching algorithm.
    """

    def cancel_stale_alerts(self, match_id=None):
        """Cancel pending/retry alerts whose match is no longer alertable."""
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
                     AND (mm.id IS NULL OR mm.status<>'new')""" + match_filter,
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

    def retry_failed_alerts(self, owner_user_id=None, *, limit=50):
        """Requeue terminal failures only when the underlying match is still new."""
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
                   WHERE q.status='failed' AND mm.status='new'""" + owner_sql +
                " ORDER BY q.id LIMIT ?",
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
