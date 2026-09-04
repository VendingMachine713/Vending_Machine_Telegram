from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
import unittest

from smart_autoposter.uncertain_evidence import evaluate_messages, evaluate_diagnostic_messages, uncertain_evidence_jobs


class Msg(SimpleNamespace):
    pass


def msg(mid, dt, text='', grouped=None, media=True, out=True):
    return Msg(id=mid, date=dt, message=text, grouped_id=grouped, media=(object() if media else None), out=out)


class EvidenceMatcherTests(unittest.TestCase):
    def job(self, media_count=10):
        return {
            'id': 41, 'account_key': 'secondary', 'group_id': -1001, 'group_name': 'Test',
            'mode': 'photo' if media_count else 'text', 'expected_media_count': media_count,
            'caption': 'Expected caption here', 'attempt_at': '2026-09-01T05:00:00+00:00'
        }

    def test_unique_album_exact_match_high_confidence(self):
        t = datetime(2026,9,1,5,1,tzinfo=timezone.utc)
        rows = [msg(100+i,t+timedelta(seconds=i), 'Expected caption here' if i==0 else '', grouped=900, media=True) for i in range(10)]
        r = evaluate_messages(self.job(), rows)
        self.assertEqual(r.confidence, 'high')
        self.assertEqual(r.matched_message_ids, list(range(100,110)))
        self.assertEqual(r.matched_grouped_id, 900)

    def test_wrong_album_size_not_auto_match(self):
        t = datetime(2026,9,1,5,1,tzinfo=timezone.utc)
        rows = [msg(100+i,t,'Expected caption here' if i==0 else '', grouped=900, media=True) for i in range(9)]
        r = evaluate_messages(self.job(), rows)
        self.assertEqual(r.confidence, 'none')

    def test_two_exact_albums_are_ambiguous(self):
        t = datetime(2026,9,1,5,1,tzinfo=timezone.utc)
        rows=[]
        for gid, base in ((900,100),(901,200)):
            rows += [msg(base+i,t+timedelta(seconds=i),'Expected caption here' if i==0 else '', grouped=gid, media=True) for i in range(10)]
        r=evaluate_messages(self.job(), rows)
        self.assertEqual(r.confidence,'ambiguous')

    def test_text_requires_exact_caption(self):
        t=datetime(2026,9,1,5,1,tzinfo=timezone.utc)
        r=evaluate_messages(self.job(0), [msg(1,t,'Expected caption here',grouped=None,media=False)])
        self.assertEqual(r.confidence,'high')

    def test_incoming_message_ignored(self):
        t=datetime(2026,9,1,5,1,tzinfo=timezone.utc)
        rows=[msg(100+i,t,'Expected caption here' if i==0 else '',grouped=900,media=True,out=False) for i in range(10)]
        self.assertEqual(evaluate_messages(self.job(),rows).confidence,'none')


class EvidenceDiagnosticTests(unittest.TestCase):
    def test_broader_window_is_diagnostic_only(self):
        job = EvidenceMatcherTests().job()
        t = datetime(2026,9,1,6,0,tzinfo=timezone.utc)  # one hour after uncertain attempt
        rows = [msg(300+i,t+timedelta(seconds=i),'Expected caption here' if i==0 else '',grouped=777,media=True) for i in range(10)]
        strict = evaluate_messages(job, rows, window_minutes=20)
        diag = evaluate_diagnostic_messages(job, rows, window_minutes=120)
        self.assertEqual(strict.confidence, 'none')
        self.assertEqual(diag['exact_match_count'], 1)
        self.assertIn('HUMAN REVIEW ONLY', diag['reason'])

    def test_nearby_nonmatching_history_is_reported(self):
        job = EvidenceMatcherTests().job()
        t = datetime(2026,9,1,5,30,tzinfo=timezone.utc)
        rows = [msg(1,t,'different payload',grouped=None,media=False)]
        diag = evaluate_diagnostic_messages(job, rows, window_minutes=120)
        self.assertEqual(diag['candidate_count'], 1)
        self.assertEqual(diag['exact_match_count'], 0)
        self.assertIsNotNone(diag['nearest_seconds'])


class EvidenceAccountInferenceTests(unittest.TestCase):
    def test_delivery_attempt_account_fills_legacy_null_queue_account(self):
        import tempfile
        from pathlib import Path
        from smart_autoposter.db import Database, utcnow
        with tempfile.TemporaryDirectory() as td:
            db=Database(Path(td)/'db.sqlite3'); db.init(); now=utcnow()
            with db.connect() as con:
                con.execute("INSERT INTO content(content_id,caption,media_json,lifecycle_state,created_at,updated_at) VALUES('c','Expected caption here','[]','ready',?,?)",(now,now))
                con.execute("INSERT INTO campaigns(campaign_id,name,content_id,lifecycle_state,enabled,created_at,updated_at) VALUES('x','X','c','paused',0,?,?)",(now,now))
                con.execute("INSERT INTO destinations(group_id,group_name,primary_access,secondary_access,preferred_account,mode,enabled,needs_review,updated_at) VALUES(-123,'G',1,1,'both','text',1,0,?)",(now,))
                con.execute("INSERT INTO queue(job_key,run_key,campaign_id,group_id,content_id,due_at,status,account_key,error_kind,created_at,updated_at) VALUES('j','r','x',-123,'c',?,'uncertain',NULL,'interrupted_send',?,?)",(now,now,now))
                qid=con.execute('SELECT id FROM queue').fetchone()[0]
                con.execute("INSERT INTO delivery_attempts(created_at,queue_id,run_key,campaign_id,group_id,account_key,attempt_number,outcome,error_kind) VALUES(?,?,?,?,?,?,?,?,?)",(now,qid,'r','x',-123,'secondary',1,'uncertain','send_timeout_uncertain'))
            rows=uncertain_evidence_jobs(db)
            self.assertEqual(len(rows),1)
            self.assertIsNone(rows[0]['account_key'])
            self.assertEqual(rows[0]['inferred_account_key'],'secondary')
