import unittest
from smart_autoposter.progress import render_terminal_dashboard, _terminal_bar

class TerminalProgressTests(unittest.TestCase):
    def sample(self):
        return {
            'found': True, 'campaign_id':'main_production_01','run_key':'schedule:test','total':4,'finalised':1,
            'progress_percent':43,'counts':{'sent':1,'deferred':1,'sending':1,'pending':1},'active':3,'state':'ACTIVE',
            'eta_seconds':125,'stuck_count':0,'current_pass':1,'pass_counts':{1:3},'first_pass_remaining':3,
            'jobs':[
                {'id':1,'group_name':'Alpha','status':'sending','stage':'UPLOADING MEDIA','stage_percent':72,'pass_no':1,'mode':'photo','account_key':'primary','progress_current':10,'progress_total':20,'progress_unit':'bytes'},
                {'id':2,'group_name':'Beta','status':'deferred','stage':'DEFERRED','stage_percent':35,'pass_no':2,'mode':'photo','account_key':'secondary','due_at':'2099-01-01T00:00:00+00:00','error_kind':'slow_mode'},
                {'id':3,'group_name':'Gamma','status':'pending','stage':'QUEUED','stage_percent':5,'pass_no':1,'mode':'text'},
                {'id':4,'group_name':'Delta','status':'sent','stage':'SENT','stage_percent':100,'pass_no':1,'mode':'photo','account_key':'primary'},
            ]
        }

    def test_dashboard_contains_focus_outcomes_and_pipeline(self):
        text = render_terminal_dashboard(self.sample(), terminal_width=100)
        self.assertIn('LIVE PRODUCTION PROGRESS', text)
        self.assertIn('CURRENT POST', text)
        self.assertIn('#1', text)
        self.assertIn('UPLOADING MEDIA', text)
        self.assertIn('DESTINATION PIPELINE', text)
        self.assertIn('DEFERRED', text)
        self.assertIn('slow_mode', text)
        self.assertIn('43%', text)

    def test_dashboard_is_ascii_safe(self):
        text = render_terminal_dashboard(self.sample(), terminal_width=80)
        text.encode('ascii')

    def test_terminal_bar_has_directional_head(self):
        self.assertEqual(len(_terminal_bar(50, 20)), 22)
        self.assertIn('>', _terminal_bar(50, 20))
        self.assertNotIn('>', _terminal_bar(100, 20))

    def test_terminal_width_clamped(self):
        text = render_terminal_dashboard(self.sample(), terminal_width=60)
        self.assertIn('SMART AUTO POSTER', text)

if __name__ == '__main__':
    unittest.main()
