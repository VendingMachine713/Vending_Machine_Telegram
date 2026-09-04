import unittest

from smart_autoposter.cli import _console_text


class WindowsConsoleSafetyTests(unittest.TestCase):
    def test_cp1252_replaces_unencodable_destination_symbols_without_crashing(self):
        text = "Mission 〄 | Group ♧ | normal café"
        safe = _console_text(text, encoding="cp1252")
        safe.encode("cp1252")
        self.assertIn("Mission ?", safe)
        self.assertIn("Group ?", safe)
        self.assertIn("café", safe)

    def test_ascii_console_is_also_fail_safe(self):
        safe = _console_text("〄 ♧ → ✅", encoding="ascii")
        safe.encode("ascii")
        self.assertEqual(safe, "? ? ? ?")

    def test_utf8_console_preserves_unicode(self):
        text = "〄 ♧ → ✅"
        self.assertEqual(_console_text(text, encoding="utf-8"), text)


if __name__ == "__main__":
    unittest.main()
