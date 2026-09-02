from core import utc_now
from match_engine import score_marketplace_pair
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

    def _existing_unresolved_pairs_for_logical(self, logical_id):
        with self.conn() as c:
            return c.execute(
                """SELECT id,demand_logical_id,supply_logical_id,status
                   FROM marketplace_matches
                   WHERE (demand_logical_id=? OR supply_logical_id=?)
                     AND status NOT IN ('accepted','dismissed','inactive')""",
                (logical_id, logical_id),
            ).fetchall()

    def _mark_match_inactive(self, match_id):
        with self.conn() as c:
            cur = c.execute(
                """UPDATE marketplace_matches
                   SET status='inactive',updated_utc=?
                   WHERE id=? AND status NOT IN ('accepted','dismissed','inactive')""",
                (utc_now(), int(match_id)),
            )
        return int(cur.rowcount)

    def reconcile_logical_listing(self, logical_id, *, min_score=45.0, candidate_limit=500):
        """Incrementally reconcile one logical listing without window false-negatives.

        SQL candidate limits bound discovery work only. Existing unresolved pairs
        that fall outside the current candidate window are revalidated directly
        before any inactivation, so an old but still-valid match cannot disappear
        merely because many newer candidates exist.
        """
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

        evaluated_keys = set()
        evaluated = 0
        eligible = 0
        created = 0
        updated = 0
        inactivated = 0

        for demand, supply in oriented:
            key = (demand["logical_listing_id"], supply["logical_listing_id"])
            evaluated_keys.add(key)
            evaluated += 1
            result = score_marketplace_pair(demand, supply)
            if not result.eligible or result.score < min_score:
                continue
            eligible += 1
            _, was_created = self._upsert_scored_pair(demand, supply, result)
            if was_created:
                created += 1
            else:
                updated += 1

        for existing in self._existing_unresolved_pairs_for_logical(logical_id):
            key = (existing["demand_logical_id"], existing["supply_logical_id"])
            if key in evaluated_keys:
                # Candidate pairs that failed eligibility/threshold must still be
                # explicitly inactivated; successful pairs were already upserted.
                demand = self._active_representative(existing["demand_logical_id"])
                supply = self._active_representative(existing["supply_logical_id"])
                if demand and supply:
                    result = score_marketplace_pair(demand, supply)
                    if result.eligible and result.score >= min_score:
                        continue
                inactivated += self._mark_match_inactive(existing["id"])
                continue

            demand = self._active_representative(existing["demand_logical_id"])
            supply = self._active_representative(existing["supply_logical_id"])
            evaluated += 1
            if not demand or not supply:
                inactivated += self._mark_match_inactive(existing["id"])
                continue
            result = score_marketplace_pair(demand, supply)
            if not result.eligible or result.score < min_score:
                inactivated += self._mark_match_inactive(existing["id"])
                continue
            eligible += 1
            self._upsert_scored_pair(demand, supply, result)
            updated += 1

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
