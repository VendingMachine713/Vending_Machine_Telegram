import unittest
from ops_core import parse_status,status_summary,offline_names

S="""Bot                     State   Processes Launcher
Admin_Command_Centre    RUNNING         2 main.py
Smart_Auto_Poster_V2    STOPPED           RUN_SERVICE.ps1
VM_Guard                RUNNING         3 START.ps1
"""
class T(unittest.TestCase):
    def test_parse(self):
        rows=parse_status(S); self.assertEqual(len(rows),3); self.assertEqual(rows[1]["state"],"STOPPED")
    def test_offline(self): self.assertEqual(offline_names(S),["Smart_Auto_Poster_V2"])
    def test_summary(self): self.assertIn("âŒ Smart_Auto_Poster_V2",status_summary(S))
if __name__=="__main__":unittest.main()
