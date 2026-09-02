from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "main.py").read_text(encoding="utf-8")


class VMGuardSecurityContractTests(unittest.TestCase):
    def test_private_admin_requires_private_chat_and_numeric_owner(self):
        self.assertIn('update.effective_chat.type=="private"', SOURCE)
        self.assertIn('update.effective_user.id==admin_id()', SOURCE)

    def test_claim_is_private_only(self):
        start = SOURCE.index("async def claim")
        following = SOURCE.index("\nasync def guard", start)
        claim_source = SOURCE[start:following]
        self.assertIn('update.effective_chat.type!="private"', claim_source)

    def test_control_commands_use_private_admin(self):
        for name in ("guard", "enable", "disable", "health"):
            start = SOURCE.index(f"async def {name}")
            following = SOURCE.find("\nasync def ", start + 1)
            block = SOURCE[start: following if following != -1 else len(SOURCE)]
            self.assertIn("private_admin(update)", block, name)

    def test_passive_group_monitoring_remains_enabled(self):
        self.assertIn("async def inspect", SOURCE)
        self.assertIn("MessageHandler(filters.ALL & ~filters.COMMAND,inspect)", SOURCE)


if __name__ == "__main__":
    unittest.main()
