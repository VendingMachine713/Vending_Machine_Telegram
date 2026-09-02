import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core import Store, utc_now
from marketplace import MarketplaceStore
from match_engine_v2_runtime import HardenedMatchEngineV2


class MatchEngineV2Tests(unittest.TestCase):
    def make_stores(self, directory):
        path = Path(directory) / "x.db"
        core = Store(path)
        market = MarketplaceStore(path)
        engine = HardenedMatchEngineV2(path)
        return core, market, engine

    def add_listing(
        self,
        core,
        market,
        *,
        chat_id,
        message_id,
        sender_id,
        text,
        date_utc=None,
    ):
        date_utc = date_utc or utc_now()
        core.upsert(
            chat_id,
            f"Chat {chat_id}",
            None,
            sender_id,
            f"u{sender_id}",
            f"User {sender_id}",
            message_id,
            date_utc,
            text,
            False,
            source="live",
        )
        return market.ingest(chat_id, message_id, sender_id, date_utc, text)

    def test_migration_is_idempotent_and_listing_insert_creates_event(self):
        with tempfile.TemporaryDirectory() as d:
            core, market, engine = self.make_stores(d)
            HardenedMatchEngineV2(engine.db_path)
            self.assertEqual(engine.event_backlog_count(), 0)
            self.add_listing(
                core, market, chat_id=-1001, message_id=1, sender_id=10,
                text="WTB iPhone 15 Pro budget $1000",
            )
            self.assertEqual(engine.event_backlog_count(), 1)
            with engine.conn() as c:
                event = c.execute(
                    "SELECT event_kind,logical_listing_id FROM marketplace_match_events"
                ).fetchone()
            self.assertEqual(event["event_kind"], "insert")
            self.assertTrue(event["logical_listing_id"])

    def test_supply_event_matches_existing_demand_without_full_refresh(self):
        with tempfile.TemporaryDirectory() as d:
            core, market, engine = self.make_stores(d)
            self.add_listing(
                core, market, chat_id=-1001, message_id=1, sender_id=10,
                text="WTB iPhone 15 Pro budget $1000 pickup Marion",
            )
            first = engine.process_events(min_score=45)
            self.assertEqual(first["events"], 1)
            self.assertEqual(len(engine.list_matches(min_score=0, limit=20)), 0)

            self.add_listing(
                core, market, chat_id=-1002, message_id=2, sender_id=20,
                text="For sale iPhone 15 Pro $900 brand new pickup Marion",
            )
            second = engine.process_events(min_score=45)
            self.assertEqual(second["events"], 1)
            self.assertGreaterEqual(second["created"], 1)
            matches = engine.list_matches(min_score=0, limit=20)
            self.assertEqual(len(matches), 1)
            self.assertEqual(matches[0]["status"], "new")

    def test_demand_event_matches_existing_supply_in_reverse_direction(self):
        with tempfile.TemporaryDirectory() as d:
            core, market, engine = self.make_stores(d)
            self.add_listing(
                core, market, chat_id=-1002, message_id=2, sender_id=20,
                text="For sale iPhone 15 Pro $900 brand new pickup Marion",
            )
            engine.process_events(min_score=45)
            self.add_listing(
                core, market, chat_id=-1001, message_id=1, sender_id=10,
                text="WTB iPhone 15 Pro budget $1000 pickup Marion",
            )
            result = engine.process_events(min_score=45)
            self.assertGreaterEqual(result["created"], 1)
            self.assertEqual(len(engine.list_matches(min_score=0, limit=20)), 1)

    def test_supply_to_demand_sql_prefilter_enforces_wtb_budget(self):
        with tempfile.TemporaryDirectory() as d:
            core, market, engine = self.make_stores(d)
            affordable = self.add_listing(
                core, market, chat_id=-1001, message_id=1, sender_id=10,
                text="WTB iPhone 15 Pro budget $1000",
            )
            too_low = self.add_listing(
                core, market, chat_id=-1002, message_id=2, sender_id=11,
                text="WTB iPhone 15 Pro budget $500",
            )
            supply = self.add_listing(
                core, market, chat_id=-1003, message_id=3, sender_id=20,
                text="For sale iPhone 15 Pro $900 available",
            )
            supply_row = market.get_listing(supply["id"])
            candidates = engine.candidate_demands_for_supply(supply_row)
            ids = {row["id"] for row in candidates}
            self.assertIn(affordable["id"], ids)
            self.assertNotIn(too_low["id"], ids)

    def test_sql_prefilters_exclude_same_sender_and_concrete_category_mismatch(self):
        with tempfile.TemporaryDirectory() as d:
            core, market, engine = self.make_stores(d)
            same_sender = self.add_listing(
                core, market, chat_id=-1001, message_id=1, sender_id=20,
                text="WTB iPhone 15 Pro budget $1000",
            )
            wrong_category = self.add_listing(
                core, market, chat_id=-1002, message_id=2, sender_id=30,
                text="WTB Hilux wheels budget $1000",
            )
            supply = self.add_listing(
                core, market, chat_id=-1003, message_id=3, sender_id=20,
                text="For sale iPhone 15 Pro $900 available",
            )
            candidates = engine.candidate_demands_for_supply(market.get_listing(supply["id"]))
            ids = {row["id"] for row in candidates}
            self.assertNotIn(same_sender["id"], ids)
            self.assertNotIn(wrong_category["id"], ids)

    def test_listing_status_update_event_inactivates_existing_match(self):
        with tempfile.TemporaryDirectory() as d:
            core, market, engine = self.make_stores(d)
            demand = self.add_listing(
                core, market, chat_id=-1001, message_id=1, sender_id=10,
                text="WTB iPhone 15 Pro budget $1000",
            )
            supply = self.add_listing(
                core, market, chat_id=-1002, message_id=2, sender_id=20,
                text="For sale iPhone 15 Pro $900 available",
            )
            engine.process_events(min_score=45)
            match = engine.list_matches(min_score=0, limit=20)[0]
            with market.conn() as c:
                c.execute(
                    "UPDATE marketplace_listings SET status='sold' WHERE id=?",
                    (supply["id"],),
                )
            self.assertGreater(engine.event_backlog_count(), 0)
            result = engine.process_events(min_score=45)
            self.assertGreaterEqual(result["inactivated"], 1)
            self.assertEqual(engine.get_match(match["id"])["status"], "inactive")

    def test_old_wtb_is_baselined_without_reminder_flood(self):
        with tempfile.TemporaryDirectory() as d:
            core, market, engine = self.make_stores(d)
            old = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
            demand = self.add_listing(
                core, market, chat_id=-1001, message_id=1, sender_id=10,
                text="WTB iPhone 15 Pro budget $1000",
                date_utc=old,
            )
            result = engine.bootstrap_v2(ttl_days=30, reminder_lead_days=7)
            self.assertTrue(result["v2_bootstrapped"])
            with engine.conn() as c:
                expiry = c.execute(
                    "SELECT status FROM marketplace_wtb_expiry WHERE demand_logical_id=?",
                    (demand["logical_listing_id"],),
                ).fetchone()
            self.assertEqual(expiry["status"], "baseline")
            self.assertEqual(engine.enqueue_due_wtb_expiry_alerts(999), 0)

    def test_due_wtb_reminder_is_duplicate_safe_and_owner_bound(self):
        with tempfile.TemporaryDirectory() as d:
            core, market, engine = self.make_stores(d)
            first_seen = (datetime.now(timezone.utc) - timedelta(days=25)).isoformat()
            demand = self.add_listing(
                core, market, chat_id=-1001, message_id=1, sender_id=10,
                text="WTB iPhone 15 Pro budget $1000",
                date_utc=first_seen,
            )
            row = market.get_listing(demand["id"])
            engine.ensure_wtb_expiry(row, ttl_days=30, reminder_lead_days=7)
            self.assertEqual(engine.enqueue_due_wtb_expiry_alerts(999), 1)
            self.assertEqual(engine.enqueue_due_wtb_expiry_alerts(999), 0)
            due = engine.due_wtb_expiry_alerts()
            self.assertEqual(len(due), 1)
            listing, queue = due[0]
            self.assertEqual(queue["owner_user_id"], 999)
            engine.mark_wtb_expiry_alert_sent(queue["alert_id"], listing["logical_listing_id"])
            self.assertEqual(engine.due_wtb_expiry_alerts(), [])

    def test_admin_change_cancels_old_owner_wtb_reminder(self):
        with tempfile.TemporaryDirectory() as d:
            core, market, engine = self.make_stores(d)
            first_seen = (datetime.now(timezone.utc) - timedelta(days=25)).isoformat()
            demand = self.add_listing(
                core, market, chat_id=-1001, message_id=1, sender_id=10,
                text="WTB iPhone 15 Pro budget $1000",
                date_utc=first_seen,
            )
            engine.ensure_wtb_expiry(
                market.get_listing(demand["id"]), ttl_days=30, reminder_lead_days=7
            )
            self.assertEqual(engine.enqueue_due_wtb_expiry_alerts(999), 1)
            self.assertEqual(engine.cancel_stale_wtb_expiry_alerts(12345), 1)
            self.assertEqual(engine.due_wtb_expiry_alerts(), [])

    def test_calibration_is_recommendation_only_and_raises_threshold_on_noise(self):
        with tempfile.TemporaryDirectory() as d:
            core, market, engine = self.make_stores(d)
            now = utc_now()
            with engine.conn() as c:
                for i in range(20):
                    demand_id = f"d{i}"
                    supply_id = f"s{i}"
                    cur = c.execute(
                        """INSERT INTO marketplace_matches(
                               demand_logical_id,supply_logical_id,demand_listing_id,supply_listing_id,
                               score,confidence,reasons_json,status,first_seen_utc,updated_utc
                           ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                        (demand_id, supply_id, 1, 2, 70.0, 0.8, "[]", "notified", now, now),
                    )
                    verdict = "relevant" if i < 10 else "not_relevant"
                    c.execute(
                        """INSERT INTO marketplace_match_feedback(
                               match_id,user_id,verdict,note,created_utc
                           ) VALUES(?,?,?,?,?)""",
                        (cur.lastrowid, 999, verdict, None, now),
                    )
            summary = engine.calibration_summary(current_threshold=65, min_samples=20)
            self.assertTrue(summary["enough_feedback"])
            self.assertEqual(summary["recommended_threshold"], 70.0)
            self.assertFalse(summary["automatic_change"])

    def test_demand_stats_report_active_matched_unmatched_and_event_backlog(self):
        with tempfile.TemporaryDirectory() as d:
            core, market, engine = self.make_stores(d)
            self.add_listing(
                core, market, chat_id=-1001, message_id=1, sender_id=10,
                text="WTB iPhone 15 Pro budget $1000",
            )
            self.add_listing(
                core, market, chat_id=-1002, message_id=2, sender_id=11,
                text="WTB Hilux wheels budget $800",
            )
            self.add_listing(
                core, market, chat_id=-1003, message_id=3, sender_id=20,
                text="For sale iPhone 15 Pro $900 available",
            )
            self.assertGreater(engine.event_backlog_count(), 0)
            engine.process_events(min_score=45)
            stats = engine.demand_stats()
            self.assertEqual(stats["active_wtb"], 2)
            self.assertEqual(stats["matched_wtb"], 1)
            self.assertEqual(stats["unmatched_wtb"], 1)
            self.assertIn("electronics", stats["categories"])


if __name__ == "__main__":
    unittest.main()
