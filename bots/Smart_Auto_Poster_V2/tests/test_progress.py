import unittest

from smart_autoposter.progress import clamp_percent, plain_stage, text_bar


class ProgressTests(unittest.TestCase):
    def test_clamp(self):
        self.assertEqual(clamp_percent(-1), 0)
        self.assertEqual(clamp_percent(49.6), 50)
        self.assertEqual(clamp_percent(101), 100)

    def test_half_bar(self):
        bar = text_bar(50, 10)
        self.assertEqual(bar.count("🟩"), 5)
        self.assertEqual(bar.count("⬜"), 5)
        self.assertIn("50%", bar)

    def test_plain_language(self):
        self.assertEqual(plain_stage("uploading"), "Uploading media")
        self.assertIn("other groups", plain_stage("deferred"))


if __name__ == "__main__":
    unittest.main()
