import tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from smart_autoposter.db import Database, utcnow
from smart_autoposter.live_coverage import ensure_schema, _failure_help, render_dashboard

class LiveCoverageTests(unittest.TestCase):
    def test_failure_help_is_specific(self):
        self.assertIn('SlowMode', _failure_help('slow_mode'))
        self.assertIn('Do not retry', _failure_help('send_timeout_uncertain'))

    def test_dashboard_counts_coverage(self):
        snap={'run':{'run_key':'coverage:test','campaign_id':'main_production_01'},'target_count':4,'sent_count':2,'remaining':2,'coverage_percent':50,
              'counts':{'sent':2,'deferred':1,'blocked_uncertain':1},'targets':[
              {'group_id':1,'group_name':'A','queue_id':1,'state':'sent','pass_no':1},
              {'group_id':2,'group_name':'B','queue_id':2,'state':'sent','pass_no':1},
              {'group_id':3,'group_name':'C','queue_id':3,'state':'deferred','pass_no':2,'due_at':'2026-09-01T08:00:00+00:00','error_kind':'slow_mode','reason':'later'},
              {'group_id':4,'group_name':'D','queue_id':4,'state':'blocked_uncertain','pass_no':1,'error_kind':'send_timeout_uncertain','reason':'verify'},]}
        text=render_dashboard(snap,100)
        self.assertIn('FULL COVERAGE LIVE RUN',text)
        self.assertIn('Confirmed SENT 2/4',text)
        self.assertIn('COVERAGE',text)
        self.assertIn('BLOCKED_UNCERTAIN',text)

    def test_schema_is_additive(self):
        with tempfile.TemporaryDirectory() as td:
            db=Database(Path(td)/'x.sqlite3'); db.init(); ensure_schema(db)
            with db.connect() as con:
                self.assertIsNotNone(con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='live_coverage_runs'").fetchone())
                self.assertIsNotNone(con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='live_coverage_targets'").fetchone())

if __name__=='__main__': unittest.main()
