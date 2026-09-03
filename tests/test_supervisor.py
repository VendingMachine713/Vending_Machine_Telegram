import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from shared.vm_core.manifests import create_missing_bot_manifests
from shared.vm_core.supervisor import supervise_once

class SupervisorTests(unittest.TestCase):
    def test_supervisor_defaults_to_no_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); bot=root/'bots'/'Demo'; bot.mkdir(parents=True)
            (bot/'main.py').write_text("print('ok')\n")
            create_missing_bot_manifests(root,write=True)
            actions=supervise_once(root,apply=False)
            self.assertEqual(actions[0]['action'],'none')

    @patch('shared.vm_core.supervisor.materialize_intelligence', create=True)
    @patch('shared.vm_core.supervisor.execute_recovery_plan')
    @patch('shared.vm_core.supervisor.recovery_plan')
    def test_supervisor_routes_recovery_through_guarded_executor(self, planner, executor, intelligence):
        planner.return_value={
            'decisions':[
                {'service':'A','classification':'SAFE_RECOVERY','action':'RESTART_SERVICE','reason':'policy permits'},
                {'service':'B','classification':'BLOCKED','action':'INVESTIGATE','reason':'auth evidence'},
            ]
        }
        executor.return_value={
            'actions':[{'service':'A','action':'RESTART_SERVICE','result':{'ok':True,'dry_run':True},'verified':None,'escalation':None}],
            'skipped':[],
        }
        with patch('shared.vm_core.intelligence.materialize_intelligence', return_value={}):
            actions=supervise_once(Path('/tmp/project'),apply=False)
        executor.assert_called_once()
        self.assertEqual(actions[0]['action'],'restart')
        self.assertEqual(actions[1]['action'],'none')
        self.assertEqual(actions[1]['classification'],'BLOCKED')

    @patch('shared.vm_core.supervisor.execute_recovery_plan')
    @patch('shared.vm_core.supervisor.recovery_plan')
    def test_supervisor_exposes_cooldown_without_bypassing_it(self, planner, executor):
        planner.return_value={'decisions':[{'service':'A','classification':'SAFE_RECOVERY','action':'RESTART_SERVICE','reason':'policy permits'}]}
        executor.return_value={'actions':[],'skipped':[{'service':'A','reason':'cooldown','history':{'cooling_down':True}}]}
        with patch('shared.vm_core.intelligence.materialize_intelligence', return_value={}):
            actions=supervise_once(Path('/tmp/project'),apply=True)
        self.assertEqual(actions[0]['action'],'none')
        self.assertEqual(actions[0]['reason'],'cooldown')
        self.assertTrue(actions[0]['recovery_gate']['cooling_down'])
