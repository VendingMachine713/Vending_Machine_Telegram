from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "main.py").read_text(encoding="utf-8")
WATCH_SOURCE = (ROOT / "watches.py").read_text(encoding="utf-8")


class UniversalSearchSecurityContractTests(unittest.TestCase):
    def _async_block(self, name):
        start = SOURCE.index(f"async def {name}")
        following = SOURCE.find("\n\nasync def ", start + 1)
        return SOURCE[start: following if following != -1 else len(SOURCE)]

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
            "watch_cmd",
            "watches_cmd",
            "_watch_state_cmd",
            "delete_watch_cmd",
            "alert_status_cmd",
            "search_help_cmd",
            "health",
            "backfill_status_cmd",
        )
        for name in guarded_functions:
            self.assertIn("private_admin(update)", self._async_block(name), name)

    def test_callbacks_recheck_private_owner(self):
        callback_source = self._async_block("search_page_callback")
        self.assertIn("private_admin(update)", callback_source)
        self.assertIn('session["user_id"]', callback_source)

    def test_group_indexing_remains_passive(self):
        self.assertIn("async def index_message", SOURCE)
        self.assertIn("MessageHandler(filters.ALL & ~filters.COMMAND, index_message)", SOURCE)
        index_source = self._async_block("index_message")
        self.assertNotIn("private_admin(update)", index_source)

    def test_alert_worker_rechecks_current_owner_before_delivery(self):
        worker_source = self._async_block("alert_worker")
        self.assertIn("owner = admin_id()", worker_source)
        self.assertIn("watch_store.reconcile_owner(owner)", worker_source)
        self.assertIn('alert["owner_user_id"] != owner', worker_source)
        self.assertIn("chat_id=owner", worker_source)

    def test_watch_store_has_fail_closed_owner_reconciliation(self):
        self.assertIn("def reconcile_owner", WATCH_SOURCE)
        self.assertIn("owner superseded", WATCH_SOURCE)
        self.assertIn("status='cancelled'", WATCH_SOURCE)


if __name__ == "__main__":
    unittest.main()
