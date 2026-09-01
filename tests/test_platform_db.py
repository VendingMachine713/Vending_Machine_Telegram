import tempfile, unittest
from pathlib import Path
from shared.vm_core.db import PlatformDB

class DBTests(unittest.TestCase):
    def test_schema_jobs_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"state"/"p.sqlite3"
            db=PlatformDB(path=path,root=Path(tmp)); db.init()
            self.assertEqual(db.integrity(),"ok")
            j=db.add_job("HEALTH_CHECK",{})
            e=db.add_event("test.event","unit",{})
            self.assertGreater(j,0); self.assertGreater(e,0)
            self.assertEqual(db.jobs()[0]["status"],"QUEUED")
