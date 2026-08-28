import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import smart_autoposter.settings as settings_mod


class AdminCredentialLoadingTests(unittest.TestCase):
    def test_project_env_overrides_stale_inherited_admin_token(self):
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, {}, clear=False):
            env_path = Path(td) / '.env'
            fresh = 'SYNTHETIC_FRESH_ADMIN_TOKEN'
            stale = 'SYNTHETIC_STALE_ADMIN_TOKEN'
            env_path.write_text(
                '\n'.join([
                    'TELEGRAM_API_ID=12345',
                    'TELEGRAM_API_HASH=synthetic_hash_for_test_only',
                    f'ADMIN_BOT_TOKEN={fresh}',
                    'ADMIN_USER_IDS=111111',
                ]) + '\n',
                encoding='utf-8',
            )
            os.environ['ADMIN_BOT_TOKEN'] = stale
            original = settings_mod.PROJECT_ENV_PATH
            try:
                settings_mod.PROJECT_ENV_PATH = env_path
                loaded = settings_mod.Settings.load(False)
            finally:
                settings_mod.PROJECT_ENV_PATH = original
            self.assertEqual(loaded.admin_bot_token, fresh)
            self.assertEqual(loaded.admin_user_ids, (111111,))

    def test_settings_reload_reflects_saved_env_change(self):
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, {}, clear=False):
            env_path = Path(td) / '.env'
            original = settings_mod.PROJECT_ENV_PATH
            try:
                settings_mod.PROJECT_ENV_PATH = env_path
                env_path.write_text('ADMIN_BOT_TOKEN=SYNTHETIC_FIRST_ADMIN_TOKEN\nADMIN_USER_IDS=1\n', encoding='utf-8')
                first = settings_mod.Settings.load(False)
                env_path.write_text('ADMIN_BOT_TOKEN=SYNTHETIC_SECOND_ADMIN_TOKEN\nADMIN_USER_IDS=2\n', encoding='utf-8')
                second = settings_mod.Settings.load(False)
            finally:
                settings_mod.PROJECT_ENV_PATH = original
            self.assertNotEqual(first.admin_bot_token, second.admin_bot_token)
            self.assertEqual(second.admin_user_ids, (2,))


class AdminBotInvalidTokenTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_bot_token_becomes_operator_friendly_runtime_error(self):
        import sys, types
        from types import SimpleNamespace
        from smart_autoposter.admin_bot import TelegramAdminController

        class AccessTokenInvalidError(Exception):
            pass

        class FakeClient:
            def __init__(self, *args, **kwargs):
                self.disconnected = False
            async def start(self, **kwargs):
                raise AccessTokenInvalidError('synthetic invalid token')
            async def disconnect(self):
                self.disconnected = True

        telethon = types.ModuleType('telethon')
        telethon.Button = object()
        telethon.TelegramClient = FakeClient
        telethon.events = types.SimpleNamespace()
        telethon_errors = types.ModuleType('telethon.errors')
        telethon_errors.AccessTokenInvalidError = AccessTokenInvalidError
        old_t = sys.modules.get('telethon')
        old_e = sys.modules.get('telethon.errors')
        sys.modules['telethon'] = telethon
        sys.modules['telethon.errors'] = telethon_errors
        try:
            settings = SimpleNamespace(
                admin_user_ids=(1,), admin_readonly_user_ids=(), admin_bot_session='runtime/admin_bot',
                api_id=123, api_hash='synthetic', admin_bot_token='123:synthetic',
                max_queue_size=100, max_pending_per_campaign=50, max_pending_per_destination=10,
            )
            controller = TelegramAdminController(None, settings, None)
            with self.assertRaisesRegex(RuntimeError, 'rejected by Telegram'):
                await controller._build_client()
        finally:
            if old_t is None: sys.modules.pop('telethon', None)
            else: sys.modules['telethon'] = old_t
            if old_e is None: sys.modules.pop('telethon.errors', None)
            else: sys.modules['telethon.errors'] = old_e


if __name__ == '__main__':
    unittest.main()
