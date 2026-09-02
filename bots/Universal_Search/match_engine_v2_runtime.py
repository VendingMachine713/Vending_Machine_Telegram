from match_engine_v2 import MatchEngineV2, _parse_dt


class HardenedMatchEngineV2(MatchEngineV2):
    """Canonical v2 runtime with portability and no-flood hardening."""

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

    def ensure_wtb_expiry(
        self,
        demand,
        *,
        ttl_days=30,
        reminder_lead_days=7,
        baseline_mode=False,
    ):
        """Schedule WTB lifecycle without flooding reminders for backfill.

        Once v2 has established its baseline, any WTB whose original first-seen
        timestamp is at or before that baseline is historical even if the row is
        imported later by a Telethon/backfill pass. Such rows are allowed to
        participate in matching immediately, but overdue reminder state is
        baselined rather than queued as a new notification.
        """
        baseline_completed = _parse_dt(self.get_v2_state("baseline_completed_utc"))
        first_seen = _parse_dt(demand["first_seen_utc"] or demand["date_utc"])
        historical_import = bool(
            baseline_completed and first_seen and first_seen <= baseline_completed
        )
        return super().ensure_wtb_expiry(
            demand,
            ttl_days=ttl_days,
            reminder_lead_days=reminder_lead_days,
            baseline_mode=bool(baseline_mode or historical_import),
        )

    def cancel_stale_wtb_expiry_alerts(self, owner_user_id=None):
        """Cancel invalid reminder deliveries using conservative SQLite syntax."""
        invalid_clause = (
            "NOT EXISTS("
            "SELECT 1 FROM marketplace_wtb_expiry e "
            "JOIN marketplace_listings l ON l.id=e.listing_id "
            "WHERE e.demand_logical_id=marketplace_wtb_expiry_alert_queue.demand_logical_id "
            "AND e.status='scheduled' "
            "AND l.listing_type='wanted' AND l.status='wanted'"
            ")"
        )
        args = []
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
