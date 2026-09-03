import tempfile
import unittest
from pathlib import Path

from shared.vm_core.paths import bot_root, log_path, state_path
from shared.vm_core.telegram_helpers import normalize_numeric_id, numeric_id_set, redact_bot_tokens, safe_peer_label


class SharedHelpersTests(unittest.TestCase):
    def test_numeric_ids_fail_closed_for_usernames(self):
        self.assertEqual(normalize_numeric_id("-100123"), -100123)
        self.assertEqual(normalize_numeric_id("123"), 123)
        self.assertIsNone(normalize_numeric_id("@someone"))
        self.assertIsNone(normalize_numeric_id("someone"))
        self.assertEqual(numeric_id_set(["1", 2, "@bad"]), {1, 2})

    def test_bot_token_redaction(self):
        token = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef"
        self.assertNotIn(token, redact_bot_tokens(f"url/{token}/getMe"))
        self.assertIn("[REDACTED_TELEGRAM_BOT_TOKEN]", redact_bot_tokens(token))

    def test_safe_peer_label_does_not_use_username_as_authority(self):
        self.assertEqual(safe_peer_label(peer_id="-1001", username="group"), "@group (-1001)")

    def test_standard_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(bot_root("Demo", root), root / "bots" / "Demo")
            self.assertEqual(state_path("x.json", root=root), root / "state" / "x.json")
            self.assertEqual(log_path("Demo Bot", root), root / "logs" / "Demo_Bot.jsonl")
            with self.assertRaises(ValueError):
                bot_root("../Demo", root)


if __name__ == "__main__":
    unittest.main()
