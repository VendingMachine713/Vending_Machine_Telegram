
import tempfile, unittest
from pathlib import Path
from core import Store, parse_query, looks_like_ad

class T(unittest.TestCase):
    def test_parse(self):
        q=parse_query("iphone --user @bob --days 7 --limit 5 --ads")
        self.assertEqual(q.text,"iphone"); self.assertEqual(q.user,"bob"); self.assertEqual(q.days,7); self.assertEqual(q.limit,5); self.assertTrue(q.ads)
    def test_ad(self):
        self.assertTrue(looks_like_ad("Selling phone $200 available, DM me"))
    def test_store(self):
        with tempfile.TemporaryDirectory() as d:
            s=Store(Path(d)/"x.db")
            s.upsert(1,"Group",None,2,"bob","Bob",3,"2026-08-29T00:00:00+00:00","hello iphone",False)
            rows=s.search(parse_query("iphone"),1)
            self.assertEqual(len(rows),1)
if __name__=="__main__": unittest.main()
