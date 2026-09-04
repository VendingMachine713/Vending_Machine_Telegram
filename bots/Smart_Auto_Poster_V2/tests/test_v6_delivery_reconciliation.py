import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from smart_autoposter.core import create_campaign, create_content
from smart_autoposter.db import Database, utcnow
from smart_autoposter.media_cache import MediaCache
from smart_autoposter.telegram_io import TelegramPool, album_timeout_seconds, is_file_reference_expired
from smart_autoposter.worker import Worker


class _Message:
    def __init__(self, message_id, media=None):
        self.id = message_id
        self.media = media


class MediaCacheTests(unittest.TestCase):
    def test_targeted_invalidation_reuploads_only_requested_album(self):
        class Client:
            def __init__(self):
                self.uploads = 0

            async def send_file(self, chat_id, media):
                self.uploads += 1
                return [_Message(100 + self.uploads, media=f"ref-{self.uploads}")]

            async def get_messages(self, chat_id, ids):
                return [_Message(ids[0], media="persisted-ref")]

        async def scenario():
            with tempfile.TemporaryDirectory() as td:
                source = Path(td) / "photo.jpg"
                source.write_bytes(b"demo-photo")
                client = Client()
                cache = MediaCache("primary", client, -100123, Path(td) / "cache")
                first = await cache.get([str(source)])
                self.assertEqual(client.uploads, 1)
                self.assertEqual(first, ["ref-1"])
                self.assertTrue(await cache.invalidate([str(source)]))
                second = await cache.get([str(source)])
                self.assertEqual(client.uploads, 2)
                self.assertEqual(second, ["ref-2"])
                state = json.loads(cache.path.read_text(encoding="utf-8"))
                self.assertEqual(len(state["items"]), 1)

        asyncio.run(scenario())

    def test_album_timeout_is_bounded_and_ten_photos_get_180_seconds(self):
        self.assertEqual(album_timeout_seconds(1), 60)
        self.assertEqual(album_timeout_seconds(10), 180)
        self.assertEqual(album_timeout_seconds(50), 180)

    def test_expired_reference_detector_handles_telegram_forms(self):
        class FileReferenceExpiredError(Exception):
            pass

        self.assertTrue(is_file_reference_expired(FileReferenceExpiredError("FILE_REFERENCE_0_EXPIRED")))
        self.assertTrue(is_file_reference_expired(RuntimeError("The file reference has expired")))
        self.assertFalse(is_file_reference_expired(RuntimeError("connection reset")))


class TelegramPoolDeliveryTests(unittest.TestCase):
    def test_expired_cached_reference_is_invalidated_and_retried_once(self):
        class FileReferenceExpiredError(Exception):
            pass

        class Cache:
            def __init__(self):
                self.gets = 0
                self.invalidations = 0

            async def get(self, files):
                self.gets += 1
                return ["cached-ref"] if self.gets == 1 else ["fresh-ref"]

            async def invalidate(self, files):
                self.invalidations += 1
                return True

        class Client:
            def __init__(self):
                self.sent = []

            async def get_entity(self, group_id):
                return group_id

            async def send_file(self, entity, files, caption=None, **kwargs):
                self.sent.append(list(files))
                if len(self.sent) == 1:
                    raise FileReferenceExpiredError("FILE_REFERENCE_0_EXPIRED")
                return [_Message(777)]

        async def scenario():
            pool = TelegramPool(1, "hash", {"primary": "unused"})
            client = Client()
            cache = Cache()
            pool.clients["primary"] = client
            pool.media_caches["primary"] = cache
            ids = await pool.send("primary", -1001, "caption", ["local.jpg"], "photo")
            self.assertEqual(ids, [777])
            self.assertEqual(client.sent, [["cached-ref"], ["fresh-ref"]])
            self.assertEqual(cache.invalidations, 1)
            self.assertEqual(cache.gets, 2)

        asyncio.run(scenario())

    def test_one_in_flight_send_per_account(self):
        class Client:
            def __init__(self):
                self.active = 0
                self.max_active = 0
                self.counter = 0

            async def get_entity(self, group_id):
                return group_id

            async def send_message(self, entity, caption, **kwargs):
                self.active += 1
                self.max_active = max(self.max_active, self.active)
                await asyncio.sleep(0.02)
                self.active -= 1
                self.counter += 1
                return _Message(self.counter)

        async def scenario():
            pool = TelegramPool(1, "hash", {"primary": "unused"})
            client = Client()
            pool.clients["primary"] = client
            await asyncio.gather(
                pool.send("primary", -1001, "a", [], "text"),
                pool.send("primary", -1002, "b", [], "text"),
            )
            self.assertEqual(client.max_active, 1)

        asyncio.run(scenario())


class WorkerReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "sap.sqlite3")
        self.db.init()
        now = utcnow()
        with self.db.connect() as con:
            con.execute("INSERT INTO accounts(account_key,session_name,enabled,authorized,identity,health_score,updated_at) VALUES('primary','p',1,1,'Primary',100,?)", (now,))
            con.execute("INSERT INTO accounts(account_key,session_name,enabled,authorized,identity,health_score,updated_at) VALUES('secondary','s',1,1,'Secondary',100,?)", (now,))
            con.execute("""INSERT INTO destinations(group_id,group_name,primary_access,secondary_access,preferred_account,mode,enabled,needs_review,updated_at)
                           VALUES(-1001,'Destination',1,1,'primary','text',1,0,?)""", (now,))
        create_content(self.db, "content", "caption", [])
        create_campaign(self.db, "campaign", "Campaign", "content")
        with self.db.connect() as con:
            con.execute("UPDATE campaigns SET enabled=1,lifecycle_state='active',last_preview_at=? WHERE campaign_id='campaign'", (now,))
        self.auth = {"primary": {"authorized": True}, "secondary": {"authorized": True}}

    def tearDown(self):
        self.tmp.cleanup()

    def _insert_job(self, status, account_key=None, key="job"):
        now = utcnow()
        with self.db.connect() as con:
            con.execute(
                """INSERT INTO queue(job_key,campaign_id,group_id,content_id,account_key,due_at,status,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (key, "campaign", -1001, "content", account_key, now, status, now, now),
            )

    def test_collapsed_preferred_account_fails_over_to_healthy_account(self):
        with self.db.connect() as con:
            con.execute("UPDATE accounts SET health_score=0 WHERE account_key='primary'")
        worker = Worker(self.db, None, min_send_gap_seconds=0)
        job = {"preferred_account": "primary", "primary_access": 1, "secondary_access": 1, "account_key": None}
        self.assertEqual(worker.choose_account(job, self.auth)[0], "secondary")

    def test_healthy_preferred_account_keeps_affinity(self):
        worker = Worker(self.db, None, min_send_gap_seconds=0)
        job = {"preferred_account": "primary", "primary_access": 1, "secondary_access": 1, "account_key": None}
        self.assertEqual(worker.choose_account(job, self.auth)[0], "primary")

    def test_retry_claim_unpins_previous_account(self):
        self._insert_job("retry", account_key="primary")
        worker = Worker(self.db, None, min_send_gap_seconds=0)
        job = worker.claim()
        self.assertIsNotNone(job)
        self.assertEqual(job["claimed_from_status"], "retry")
        self.assertIsNone(job["account_key"])
        with self.db.connect() as con:
            row = con.execute("SELECT status,account_key FROM queue WHERE job_key='job'").fetchone()
        self.assertEqual(row["status"], "sending")
        self.assertIsNone(row["account_key"])

    def test_uncertain_job_is_never_claimed(self):
        self._insert_job("uncertain")
        worker = Worker(self.db, None, min_send_gap_seconds=0)
        self.assertIsNone(worker.claim())

    def test_busy_preferred_account_uses_other_account(self):
        class Pool:
            @staticmethod
            def account_busy(key):
                return key == "primary"

        worker = Worker(self.db, Pool(), min_send_gap_seconds=0)
        job = {"preferred_account": "primary", "primary_access": 1, "secondary_access": 1, "account_key": None}
        self.assertEqual(worker.choose_account(job, self.auth)[0], "secondary")


class AdminSeparationTests(unittest.TestCase):
    def test_smart_auto_poster_service_has_no_embedded_admin_runtime(self):
        service = Path(__file__).parents[1] / "smart_autoposter" / "service.py"
        source = service.read_text(encoding="utf-8")
        self.assertNotIn("TelegramAdminController", source)
        self.assertNotIn("_start_admin", source)
        self.assertNotIn("admin_task", source)
        self.assertIn("_run_worker_batch", source)


if __name__ == "__main__":
    unittest.main()
