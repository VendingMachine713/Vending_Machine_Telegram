import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from contextlib import redirect_stdout
from unittest.mock import patch

from smart_autoposter import cli


class FakeTelegramClient:
    def __init__(self, session, api_id, api_hash, flood_sleep_threshold=0):
        self.session = session

    async def start(self):
        return self

    async def get_me(self):
        return SimpleNamespace(username='secondary_test', first_name='Secondary', id=222222)

    async def disconnect(self):
        return None


class LoginAccountRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_reset_secondary_archives_existing_session_without_nameerror(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            session = root / 'runtime' / 'sessions' / 'Auto_Post_Secondary'
            session.parent.mkdir(parents=True)
            session_file = Path(str(session) + '.session')
            session_file.write_bytes(b'existing-session')

            fake_settings = SimpleNamespace(
                sessions={'secondary': session, 'primary': root / 'runtime' / 'sessions' / 'my_account'},
                backup_dir=root / 'backups',
                media_cache_dir=root / 'runtime' / 'cache',
                api_id=12345,
                api_hash='test-hash',
                runtime_lock_path=root / 'runtime' / 'smart_autoposter.lock',
                ensure_dirs=lambda: (root / 'runtime').mkdir(parents=True, exist_ok=True),
            )
            fake_settings.media_cache_dir.mkdir(parents=True, exist_ok=True)

            args = SimpleNamespace(account='secondary', reset=True)
            output = io.StringIO()
            with patch.object(cli.Settings, 'load', return_value=fake_settings), \
                 patch('telethon.TelegramClient', FakeTelegramClient), \
                 redirect_stdout(output):
                await cli.async_login_account(args)

            self.assertIn('[OK] SECONDARY authorized as secondary_test', output.getvalue())
            backups = list((fake_settings.backup_dir / 'session_backups').glob('Auto_Post_Secondary.session.*.bak'))
            self.assertEqual(len(backups), 1)
            self.assertFalse(session_file.exists())


if __name__ == '__main__':
    unittest.main()
