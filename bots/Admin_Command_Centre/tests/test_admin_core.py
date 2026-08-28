import sys,tempfile,unittest
from pathlib import Path
BOT=Path(__file__).resolve().parents[1]; ROOT=BOT.parents[1]
for p in (str(BOT),str(ROOT)):
    if p not in sys.path: sys.path.insert(0,p)
from admin_core import parse_command,is_admin,handle_command,set_local_env,load_local_env
class AdminCoreTests(unittest.TestCase):
    def test_parse(self): self.assertEqual(parse_command('/start@vm_bot autoposter'),('start',['autoposter']))
    def test_allowlist(self): self.assertTrue(is_admin(123,{'admin_ids':{123}}))
    def test_access_denied(self): self.assertEqual(handle_command(456,'/status',{'admin_ids':{123},'allow_mutations':False,'token':'x'}),'Access denied.')
    def test_mutations_disabled(self): self.assertIn('disabled',handle_command(123,'/backup',{'admin_ids':{123},'allow_mutations':False,'token':'x'}).lower())
    def test_local_claim_persistence_helper(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'.env'; set_local_env('VM_ADMIN_USER_IDS','123',p); self.assertEqual(load_local_env(p)['VM_ADMIN_USER_IDS'],'123')
if __name__=='__main__': unittest.main()
