import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from smart_autoposter.admin_bot import TelegramAdminController


class _DB:
    def __init__(self):
        self.events = []

    def event(self, *args, **kwargs):
        self.events.append((args, kwargs))


class V602LiveProgressTests(unittest.IsolatedAsyncioTestCase):
    async def test_live_feed_edits_same_message_then_stops_at_terminal_state(self):
        controller = TelegramAdminController.__new__(TelegramAdminController)
        controller.db = _DB()
        controller.settings = SimpleNamespace(timezone="Australia/Adelaide")
        controller.stop_requested = False
        controller._progress_tasks = {}
        message = SimpleNamespace(edit=AsyncMock())
        button = SimpleNamespace(inline=lambda *args, **kwargs: (args, kwargs))

        with patch("smart_autoposter.admin_bot.progress_text", return_value="25%"), \
             patch("smart_autoposter.admin_bot.progress_snapshot", return_value={"found": True, "active": 0}), \
             patch("smart_autoposter.admin_bot.render_progress_text", return_value="100%"), \
             patch("smart_autoposter.admin_bot.asyncio.sleep", new=AsyncMock()):
            await controller._live_progress_loop(1, message, button)

        message.edit.assert_awaited_once()
        self.assertEqual(message.edit.await_args.args[0], "100%")
        self.assertEqual(controller.db.events, [])


if __name__ == "__main__":
    unittest.main()
