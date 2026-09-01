import sqlite3,tempfile,unittest
from pathlib import Path
from shared.vm_core.registry import sync_accounts,sync_destinations,registry_summary
from shared.vm_core.simulate import run_scenario

class RegistrySimulationTests(unittest.TestCase):
    def test_registry_and_simulation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); bot=root/"bots"/"Demo"; bot.mkdir(parents=True)
            (bot/"main.py").write_text("print('x')\n")
            (bot/"primary.session").write_text("opaque")
            dbp=bot/"data.sqlite3"
            con=sqlite3.connect(dbp); con.execute("create table destinations(chat_id text,title text,username text,enabled int)")
            con.execute("insert into destinations values('-1001','Test Group','testgroup',1)"); con.commit(); con.close()
            self.assertEqual(sync_accounts(root),1)
            result=sync_destinations(root); self.assertGreaterEqual(result["rows_imported_or_refreshed"],1)
            summary=registry_summary(root); self.assertEqual(summary["accounts"],1); self.assertEqual(summary["destinations"],1)
            sim=run_scenario("spam",root); self.assertEqual(sim["real_telegram_actions"],0)
