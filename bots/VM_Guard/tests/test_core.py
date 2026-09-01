
import unittest
from core import score_message, extract_domains, FloodTracker
class T(unittest.TestCase):
    def test_domain(self): self.assertEqual(extract_domains("go https://bit.ly/x"),["bit.ly"])
    def test_scam(self):
        s,r=score_message("Guaranteed profit! Double your money, send crypto now")
        self.assertGreaterEqual(s,50)
    def test_flood(self):
        f=FloodTracker(window=10,limit=2)
        self.assertFalse(f.hit(1,2,0)[0]); self.assertFalse(f.hit(1,2,1)[0]); self.assertTrue(f.hit(1,2,2)[0])
if __name__=="__main__": unittest.main()
