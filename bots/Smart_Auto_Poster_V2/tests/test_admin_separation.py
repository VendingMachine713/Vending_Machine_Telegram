from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from smart_autoposter.settings import Settings


class AdminSeparationTests(unittest.TestCase):
    def test_embedded_admin_bot_stays_disabled_even_with_legacy_credentials(self):
        legacy = {
            "TELEGRAM_API_ID": "12345",
            "TELEGRAM_API_HASH": "test-hash",
            "ADMIN_BOT_TOKEN": "legacy-token",
            "ADMIN_USER_IDS": "123456789",
        }
        with patch.dict(os.environ, legacy, clear=False):
            settings = Settings.load(False)

        self.assertFalse(settings.admin_bot_enabled)


if __name__ == "__main__":
    unittest.main()
