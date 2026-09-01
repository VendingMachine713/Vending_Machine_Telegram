import unittest

from smart_autoposter.cli import _console_text


class WindowsConsoleSafetyTests(unittest.TestCase):
    def test_cp1252_replaces_unencodable_destination_symbols_without_crashing(self):
        text = "Mission ã€„ | Group â™§ | normal cafÃ©"
        safe = _console_text(text, encoding="cp1252")
        safe.encode("cp1252")
        self.assertIn("Mission ?", safe)
        self.assertIn("Group ?", safe)
        self.assertIn("cafÃ©", safe)

    def test_ascii_console_is_also_fail_safe(self):
        safe = _console_text("ã€„ â™§ â†’ âœ…", encoding="ascii")
        safe.encode("ascii")
        self.assertEqual(safe, "? ? ? ?")

    def test_utf8_console_preserves_unicode(self):
        text = "ã€„ â™§ â†’ âœ…"
        self.assertEqual(_console_text(text, encoding="utf-8"), text)


if __name__ == "__main__":
    unittest.main()
