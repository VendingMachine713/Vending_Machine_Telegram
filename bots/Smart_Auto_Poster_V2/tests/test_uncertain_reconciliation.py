import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from smart_autoposter.db import Database, utcnow
from smart_autoposter.delivery_ledger import start_attempt
from smart_autoposter.uncertain_reconciliation import (
    audit_uncertain_deliveries,
    classify_history_evidence,
)


def job(**updates):
    row = {
        "id": 7,
        "group_id": -1001,
        "group_name": "Demo",
        "campaign_id": "camp",
        "caption": "hello\nworld",
        "mode": "text",
    }
    row.update(updates)
    return row


class EvidenceClassifierTests(unittest.TestCase):
    def test_stored_message_ids_are_high_confidence_proof(self):
        r = classify_history_evidence(
            job=job(),
            messages=[{"id": 91, "out": True, "text": "hello\nworld", "account_key": "primary"}],
            expected_media_count=0,
            direct_message_ids=[91],
        )
        self.assertEqual(r.classification, "PROVEN_SENT_BY_ID")
        self.assertTrue(r.safe_to_mark_sent)
        self.assertFalse(r.safe_to_retry)

    def test_exact_unique_text_is_proof(self):
        r = classify_history_evidence(
            job=job(),
            messages=[{"id": 92, "out": True, "text": "hello\r\nworld  ", "account_key": "primary"}],
            expected_media_count=0,
        )
        self.assertEqual(r.classification, "PROVEN_SENT_BY_TEXT")
        self.assertTrue(r.safe_to_mark_sent)

    def test_multiple_exact_matches_are_ambiguous(self):
        r = classify_history_evidence(
            job=job(),
            messages=[
                {"id": 1, "out": True, "text": "hello\nworld", "account_key": "primary"},
                {"id": 2, "out": True, "text": "hello\nworld", "account_key": "primary"},
            ],
            expected_media_count=0,
        )
        self.assertEqual(r.classification, "AMBIGUOUS_MULTIPLE_MATCHES")
        self.assertFalse(r.safe_to_mark_sent)
        self.assertFalse(r.safe_to_retry)

    def test_album_requires_expected_media_count(self):
        msgs = [
            {"id": 10, "out": True, "text": "album", "grouped_id": 55, "has_media": True, "account_key": "primary"},
            {"id": 11, "out": True, "text": "", "grouped_id": 55, "has_media": True, "account_key": "primary"},
        ]
        good = classify_history_evidence(
            job=job(caption="album", mode="photo"), messages=msgs, expected_media_count=2
        )
        bad = classify_history_evidence(
            job=job(caption="album", mode="photo"), messages=msgs, expected_media_count=3
        )
        self.assertEqual(good.classification, "PROVEN_SENT_BY_ALBUM")
        self.assertTrue(good.safe_to_mark_sent)
        self.assertEqual(bad.classification, "MEDIA_COUNT_MISMATCH")
        self.assertFalse(bad.safe_to_mark_sent)

    def test_no_match_never_authorizes_retry(self):
        r = classify_history_evidence(
            job=job(),
            messages=[],
            expected_media_count=0,
        )
        self.assertEqual(r.classification, "NO_MATCH")
        self.assertFalse(r.safe_to_mark_sent)
        self.assertFalse(r.safe_to_retry)


class FakePool:
    async def authorization(self):
        return {"primary": {"authorized": True}, "secondary": {"authorized": False}}

    async def history_window(self, account, group_id, start, end, *, limit):
        return [{"id": 500, "out": True, "text": "payload", "account_key": account, "has_media": False, "grouped_id": None}]

    async def message_evidence_by_ids(self, account, group_id, ids):
        return [{"id": int(ids[0]), "out": True, "text": "payload", "account_key": account, "has_media": False, "grouped_id": None}]


class AuditSafetyTests(unittest.TestCase):
    def test_audit_is_read_only_for_queue_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "db.sqlite3")
            db.init()
            now = utcnow()
            with db.connect() as con:
                con.execute("INSERT INTO accounts(account_key,session_name,enabled,authorized,identity,updated_at) VALUES('primary','p',1,1,'p',?)", (now,))
                con.execute("INSERT INTO destinations(group_id,group_name,primary_access,secondary_access,preferred_account,mode,enabled,needs_review,updated_at) VALUES(-1001,'Demo',1,0,'primary','text',1,0,?)", (now,))
                con.execute("INSERT INTO content(content_id,caption,media_json,enabled,lifecycle_state,created_at,updated_at) VALUES('content','payload','[]',1,'ready',?,?)", (now, now))
                con.execute("INSERT INTO campaigns(campaign_id,name,content_id,enabled,lifecycle_state,created_at,updated_at) VALUES('camp','C','content',1,'active',?,?)", (now, now))
                cur = con.execute("INSERT INTO queue(job_key,run_key,campaign_id,group_id,content_id,account_key,due_at,status,created_at,updated_at) VALUES('job','run','camp',-1001,'content','primary',?,'sending',?,?)", (now, now, now))
                job_id = int(cur.lastrowid)
            start_attempt(db, job_id, "primary")
            with db.connect() as con:
                con.execute("UPDATE queue SET status='uncertain',error_kind='interrupted_send' WHERE id=?", (job_id,))

            report = asyncio.run(audit_uncertain_deliveries(db, FakePool()))
            self.assertEqual(report["mode"], "READ_ONLY")
            self.assertEqual(report["proven_sent"], 1)
            self.assertFalse(report["safety"]["queue_mutations"])
            with db.connect() as con:
                state = con.execute("SELECT status,error_kind FROM queue WHERE id=?", (job_id,)).fetchone()
            self.assertEqual(tuple(state), ("uncertain", "interrupted_send"))


if __name__ == "__main__":
    unittest.main()
