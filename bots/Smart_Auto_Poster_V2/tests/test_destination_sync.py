import asyncio
import tempfile
import unittest
from pathlib import Path

from smart_autoposter.db import Database, utcnow
from smart_autoposter.destination_sync import sync_destinations


class FakePool:
    async def dialogs(self, account):
        if account == "primary":
            return [{"group_id":-1001,"group_name":"Primary Group","chat_type":"supergroup","username":None,"forum":False}]
        return [{"group_id":-1002,"group_name":"Secondary Group","chat_type":"supergroup","username":None,"forum":True}]


class DestinationSyncTests(unittest.TestCase):
    def test_sync_is_fail_closed_and_builds_system_tags(self):
        with tempfile.TemporaryDirectory() as td:
            db = Database(Path(td)/"db.sqlite3"); db.init()
            with db.connect() as con:
                con.execute("INSERT INTO destinations(group_id,group_name,primary_access,secondary_access,preferred_account,mode,enabled,needs_review,updated_at) VALUES(-9999,'Gone',1,1,'primary','text',1,0,?)",(utcnow(),))
            auth={"primary":{"authorized":True},"secondary":{"authorized":True}}
            result=asyncio.run(sync_destinations(db,FakePool(),auth))
            self.assertEqual(result["counts"]["primary"],1)
            self.assertEqual(result["counts"]["secondary"],1)
            with db.connect() as con:
                gone=con.execute("SELECT enabled,needs_review FROM destinations WHERE group_id=-9999").fetchone()
                p_tags={r[0] for r in con.execute("SELECT tag FROM destination_tags WHERE group_id=-1001")}
                s_tags={r[0] for r in con.execute("SELECT tag FROM destination_tags WHERE group_id=-1002")}
            self.assertEqual(tuple(gone),(0,1))
            self.assertIn("auto_primary_only",p_tags)
            self.assertIn("auto_secondary_only",s_tags)
            self.assertIn("auto_forum",s_tags)


if __name__ == '__main__': unittest.main()
