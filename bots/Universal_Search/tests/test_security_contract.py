from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "main.py").read_text(encoding="utf-8")


class UniversalSearchSecurityContractTests(unittest.TestCase):
    def test_private_admin_requires_private_chat_and_numeric_owner(self):
        self.assertIn('update.effective_chat.type == "private"', SOURCE)
        self.assertIn('update.effective_user.id == a', SOURCE)

    def test_claim_is_private_only(self):
        claim_start = SOURCE.index("async def claim")
        next_def = SOURCE.index("\ndef _short", claim_start)
        claim_source = SOURCE[claim_start:next_def]
        self.assertIn('update.effective_chat.type != "private"', claim_source)

    def test_all_user_control_commands_use_private_admin(self):
        guarded_functions = (
            "search_cmd",
            "recent_searches_cmd",
            "search_help_cmd",
            "health",
            "backfill_status_cmd",
        )
        for name in guarded_functions:
            start = SOURCE.index(f"async def {name}")
            following = SOURCE.find("\n\nasync def ", start + 1)
            block = SOURCE[start: following if following != -1 else len(SOURCE)]
            self.assertIn("private_admin(update)", block, name)

    def test_callbacks_recheck_private_owner(self):
        start = SOURCE.index("async def search_page_callback")
        following = SOURCE.index("\n\nasync def recent_searches_cmd", start)
        callback_source = SOURCE[start:following]
        self.assertIn("private_admin(update)", callback_source)
        self.assertIn('session["user_id"]', callback_source)

    def test_group_indexing_remains_passive(self):
        self.assertIn("async def index_message", SOURCE)
        self.assertIn("MessageHandler(filters.ALL & ~filters.COMMAND, index_message)", SOURCE)


if __name__ == "__main__":
    unittest.main()
