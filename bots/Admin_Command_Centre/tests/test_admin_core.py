import sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
BOT=Path(__file__).resolve().parents[1]; ROOT=BOT.parents[1]
for p in (str(BOT),str(ROOT)):
    if p not in sys.path: sys.path.insert(0,p)
from admin_core import parse_command,is_admin,handle_command,set_local_env,load_local_env

ADMIN={'admin_ids':{123},'allow_mutations':False,'token':'x'}
ADMIN_MUTATING={'admin_ids':{123},'allow_mutations':True,'token':'x'}

class AdminCoreTests(unittest.TestCase):
    def test_parse(self): self.assertEqual(parse_command('/start@vm_bot autoposter'),('start',['autoposter']))
    def test_allowlist(self): self.assertTrue(is_admin(123,{'admin_ids':{123}}))
    def test_access_denied(self): self.assertEqual(handle_command(456,'/status',ADMIN),'Access denied.')
    def test_mutations_disabled(self): self.assertIn('disabled',handle_command(123,'/backup',ADMIN).lower())
    @patch('admin_core.canonical_recommendation_summary')
    def test_review_is_read_only_preview(self,summary):
        summary.return_value={'recommendations':[{
            'recommendation_key':'canonical:telegram:chat:0123456789abcdef01234567',
            'status':'PROPOSED','priority':0.8,'confidence':0.9,
            'action':'review relationship','rationale':'Recent canonical evidence.'}], 'counts':{'PROPOSED':1}}
        text=handle_command(123,'/review',ADMIN)
        self.assertIn('Operator approval is required',text)
        self.assertIn('canonical:telegram:chat:',text)
        self.assertIn('No Telegram action is executed',text)
        summary.assert_called_once_with(root=ROOT,limit=50)

    @patch('admin_core.transition_canonical_review')
    def test_review_accept_is_explicit_and_metadata_only(self,transition):
        transition.return_value=type('Decision',(),{
            'status':'ACCEPTED','recommendation_key':'canonical:telegram:chat:key',
            'previous_status':'PROPOSED','actor':'telegram:123','event_id':7})()
        text=handle_command(123,'/review_accept canonical:telegram:chat:key approve for pilot',ADMIN)
        self.assertIn('REVIEW ACCEPTED',text)
        self.assertIn('No Telegram action was executed',text)
        transition.assert_called_once_with('canonical:telegram:chat:key','ACCEPTED',actor='telegram:123',note='approve for pilot',root=ROOT)
    @patch('admin_core.format_all_progress')
    def test_platform_progress_uses_registered_surfaces(self,formatter):
        formatter.return_value='UNIVERSAL PROGRESS ENGINE\nSurfaces: 1'
        text=handle_command(123,'/progress',ADMIN)
        self.assertIn('UNIVERSAL PROGRESS ENGINE',text)
        formatter.assert_called_once_with(ROOT)
    def test_poster_help_is_owned_by_admin_command_centre(self):
        text=handle_command(123,'/poster',ADMIN)
        self.assertIn('SMART AUTO POSTER CONTROL',text)
        self.assertIn('/poster_status',text)
        self.assertIn('/poster_progress',text)
        self.assertIn('/poster_restart',text)
    def test_poster_mutations_are_guarded(self):
        self.assertIn('disabled',handle_command(123,'/poster_restart',ADMIN).lower())
    @patch('admin_core.format_progress')
    @patch('admin_core.smart_auto_poster_progress')
    def test_poster_progress_uses_universal_progress_engine(self,progress,formatter):
        progress.return_value={'headline':'SMART AUTO POSTER - UNIVERSAL PROGRESS'}
        formatter.return_value='SMART AUTO POSTER - UNIVERSAL PROGRESS\nOVERALL 50%'
        text=handle_command(123,'/poster_progress',ADMIN)
        self.assertIn('UNIVERSAL PROGRESS',text)
        progress.assert_called_once_with(ROOT)
        formatter.assert_called_once_with(progress.return_value)
    @patch('admin_core.run_service_cli')
    def test_poster_health_uses_vm_core_cli_bridge(self,run_cli):
        run_cli.return_value={'ok':True,'stdout':'HEALTH OK','stderr':''}
        self.assertEqual(handle_command(123,'/poster_health',ADMIN),'HEALTH OK')
        run_cli.assert_called_once()
        self.assertEqual(run_cli.call_args.args[0],'Smart_Auto_Poster_V2')
        self.assertEqual(run_cli.call_args.args[1],['health'])
    @patch('admin_core.restart_service')
    def test_poster_restart_targets_only_poster_service(self,restart):
        restart.return_value={'ok':True,'service':'Smart_Auto_Poster_V2'}
        text=handle_command(123,'/poster_restart',ADMIN_MUTATING)
        self.assertIn('Smart_Auto_Poster_V2',text)
        restart.assert_called_once()
        self.assertEqual(restart.call_args.args[0],'Smart_Auto_Poster_V2')
    @patch('admin_core.format_intelligence_summary')
    @patch('admin_core.intelligence_summary')
    def test_brain_is_read_only_intelligence_surface(self,summary,formatter):
        summary.return_value={'platform_health':{},'open_incidents':[],'active_signals':[]}
        formatter.return_value='VM INTELLIGENCE\nServices healthy: 5/5'
        text=handle_command(123,'/brain',ADMIN)
        self.assertIn('VM INTELLIGENCE',text)
        summary.assert_called_once_with(ROOT,refresh=True)
        formatter.assert_called_once()
    def test_local_claim_persistence_helper(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'.env'; set_local_env('VM_ADMIN_USER_IDS','123',p); self.assertEqual(load_local_env(p)['VM_ADMIN_USER_IDS'],'123')
if __name__=='__main__': unittest.main()
