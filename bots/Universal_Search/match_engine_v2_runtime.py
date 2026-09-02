from match_engine_v2 import MatchEngineV2


class HardenedMatchEngineV2(MatchEngineV2):
    """Canonical v2 runtime with portability/security hardening.

    MatchEngineV2 owns the incremental architecture. This layer contains narrow
    runtime fixes that should remain independently testable and easy to remove
    once the core implementation is consolidated at the next release boundary.
    """

    def candidate_demands_for_supply(self, supply, *, limit=500):
        """Pre-filter active WTBs whose explicit budget can afford supply.

        A missing WTB budget remains eligible. A missing supply price remains
        eligible for semantic scoring. Concrete supply prices are compared to
        the demand row's budget column, never to themselves.
        """
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
                   AND (l.price_cents IS NULL OR ? IS NULL OR l.price_cents>=?)
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
            limit,
        )
        with self.conn() as c:
            rows = c.execute(sql, args).fetchall()
        return self._dedupe_logical(rows)

    def cancel_stale_wtb_expiry_alerts(self, owner_user_id=None):
        """Cancel invalid reminder deliveries using conservative SQLite syntax."""
        clauses = [
            "status IN ('pending','retry')",
            "NOT EXISTS("
            "SELECT 1 FROM marketplace_wtb_expiry e "
            "JOIN marketplace_listings l ON l.id=e.listing_id "
            "WHERE e.demand_logical_id=marketplace_wtb_expiry_alert_queue.demand_logical_id "
            "AND e.status='scheduled' "
            "AND l.listing_type='wanted' AND l.status='wanted'"
            ")",
        ]
        args = []
        invalid_clause = clauses[1]
        if owner_user_id:
            invalid_clause = f"({invalid_clause} OR owner_user_id<>?)"
            args.append(int(owner_user_id))
        with self.conn() as c:
            cur = c.execute(
                """UPDATE marketplace_wtb_expiry_alert_queue
                   SET status='cancelled',last_error='WTB reminder no longer deliverable'
                   WHERE status IN ('pending','retry') AND """ + invalid_clause,
                args,
            )
        return int(cur.rowcount)
