from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from smart_autoposter.db import Database, utcnow
from smart_autoposter.topic_routing import (
    normalise_topic,
    select_topic_route,
    sync_forum_topics,
    topic_route_preview,
)


class FakeTopicPool:
    def __init__(self, topics=None, errors=None):
        self.topics = topics or {}
        self.errors = errors or set()
        self.calls = []

    async def forum_topics(self, account_key, group_id):
        self.calls.append((account_key, group_id))
        if (account_key, group_id) in self.errors:
            raise RuntimeError("read failed")
        return list(self.topics.get((account_key, group_id), []))

    async def send(self, *_args, **_kwargs):
        raise AssertionError("topic discovery must never send")


class ForumTopicRoutingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "data" / "smart_autoposter.sqlite3")
        self.db.init()

    def tearDown(self):
        self.tmp.cleanup()

    def add_forum(self, group_id=-1001, *, topic_id=None, preferred_account="primary"):
        with self.db.connect() as con:
            con.execute(
                """INSERT INTO destinations(
                       group_id,group_name,forum,topic_id,primary_access,secondary_access,
                       preferred_account,mode,enabled,needs_review,updated_at
                   ) VALUES(?,?,?,?,1,1,?,'review',0,1,?)""",
                (group_id, f"Forum {abs(group_id)}", 1, topic_id, preferred_account, utcnow()),
            )

    def test_schema_and_malformed_topic_handling(self):
        with self.db.connect() as con:
            self.assertIsNotNone(
                con.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='destination_topics'"
                ).fetchone()
            )
        self.assertIsNone(normalise_topic(None))
        self.assertIsNone(normalise_topic({"topic_id": "bad"}))
        self.assertIsNone(normalise_topic({"topic_id": 2, "deleted": True}))

    def test_selection_preserves_existing_and_refuses_ambiguous_routes(self):
        topics = [
            normalise_topic({"topic_id": 10, "title": "Sales"}),
            normalise_topic({"topic_id": 20, "title": "Support"}),
        ]
        self.assertEqual(select_topic_route(topics, 20), (20, "preserve_existing"))
        self.assertEqual(select_topic_route(topics), (None, "topic_selection_required"))
        exact = topics + [normalise_topic({"topic_id": 30, "title": "General"})]
        self.assertEqual(select_topic_route(exact), (30, "exact:general"))

    async def test_account_coverage_is_merged_without_sending(self):
        self.add_forum()
        pool = FakeTopicPool(
            {
                ("primary", -1001): [
                    {"topic_id": 10, "title": "General"},
                    {"topic_id": 20, "title": "Sales"},
                ],
                ("secondary", -1001): [{"topic_id": 10, "title": "General"}],
            }
        )
        auth = {"primary": {"authorized": True}, "secondary": {"authorized": True}}
        result = await sync_forum_topics(self.db, pool, auth)
        self.assertEqual(result["routes_ready"], 1)
        self.assertTrue(result["read_only_telegram"])
        self.assertFalse(result["automatic_send"])
        with self.db.connect() as con:
            destination = con.execute("SELECT topic_id FROM destinations WHERE group_id=-1001").fetchone()
            general = con.execute(
                "SELECT primary_access,secondary_access,preferred FROM destination_topics WHERE group_id=-1001 AND topic_id=10"
            ).fetchone()
        self.assertEqual(destination["topic_id"], 10)
        self.assertEqual(tuple(general), (1, 1, 1))
        self.assertEqual(pool.calls, [("primary", -1001), ("secondary", -1001)])

    async def test_ambiguous_topics_fail_closed_and_preview_requires_review(self):
        self.add_forum()
        pool = FakeTopicPool(
            {("primary", -1001): [
                {"topic_id": 10, "title": "Sales"},
                {"topic_id": 20, "title": "Support"},
            ]}
        )
        auth = {"primary": {"authorized": True}, "secondary": {"authorized": False}}
        result = await sync_forum_topics(self.db, pool, auth)
        self.assertEqual(result["routes_requiring_review"], 1)
        preview = topic_route_preview(self.db)
        self.assertTrue(preview["read_only"])
        self.assertFalse(preview["telegram_mutations"])
        self.assertFalse(preview["automatic_send"])
        self.assertEqual(preview["routes"][0]["status"], "REVIEW_REQUIRED")

    async def test_repeated_scan_is_idempotent(self):
        self.add_forum()
        topics = {("primary", -1001): [{"topic_id": 10, "title": "General"}]}
        auth = {"primary": {"authorized": True}, "secondary": {"authorized": False}}
        pool = FakeTopicPool(topics)
        await sync_forum_topics(self.db, pool, auth)
        await sync_forum_topics(self.db, pool, auth)
        with self.db.connect() as con:
            count = con.execute("SELECT COUNT(*) FROM destination_topics").fetchone()[0]
            selected = con.execute("SELECT topic_id FROM destinations WHERE group_id=-1001").fetchone()[0]
        self.assertEqual(count, 1)
        self.assertEqual(selected, 10)

    async def test_failed_scan_preserves_existing_route_and_visibility(self):
        self.add_forum(topic_id=10)
        now = utcnow()
        with self.db.connect() as con:
            con.execute(
                """INSERT INTO destination_topics(
                       group_id,topic_id,title,primary_access,preferred,enabled,updated_at
                   ) VALUES(-1001,10,'General',1,1,1,?)""",
                (now,),
            )
        pool = FakeTopicPool(errors={("primary", -1001), ("secondary", -1001)})
        auth = {"primary": {"authorized": True}, "secondary": {"authorized": True}}
        result = await sync_forum_topics(self.db, pool, auth)
        self.assertEqual(result["scan_errors"], 2)
        with self.db.connect() as con:
            route = con.execute("SELECT topic_id FROM destinations WHERE group_id=-1001").fetchone()[0]
            visible = con.execute("SELECT enabled FROM destination_topics WHERE group_id=-1001 AND topic_id=10").fetchone()[0]
        self.assertEqual(route, 10)
        self.assertEqual(visible, 1)

    def test_preview_blocks_missing_required_account_access(self):
        self.add_forum(topic_id=10, preferred_account="both")
        with self.db.connect() as con:
            con.execute(
                """INSERT INTO destination_topics(
                       group_id,topic_id,title,primary_access,secondary_access,preferred,enabled,updated_at
                   ) VALUES(-1001,10,'General',1,0,1,1,?)""",
                (utcnow(),),
            )
        preview = topic_route_preview(self.db)
        self.assertEqual(preview["routes"][0]["status"], "BLOCKED_ACCOUNT_ACCESS")


if __name__ == "__main__":
    unittest.main()
