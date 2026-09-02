import unittest
from unittest.mock import patch

import match_daemon


class MatchDaemonSecurityTests(unittest.TestCase):
    def test_authorized_owner_set_combines_central_and_legacy_owner(self):
        with patch.object(match_daemon, "central_owner_ids", return_value={100, 200}), patch.object(
            match_daemon, "admin_id", return_value=300
        ):
            self.assertEqual(match_daemon.authorized_owner_ids(), (100, 200, 300))

    def test_duplicate_owner_is_deduplicated(self):
        with patch.object(match_daemon, "central_owner_ids", return_value={100, 200}), patch.object(
            match_daemon, "admin_id", return_value=200
        ):
            self.assertEqual(match_daemon.authorized_owner_ids(), (100, 200))

    def test_missing_owner_identity_fails_closed(self):
        with patch.object(match_daemon, "central_owner_ids", return_value=set()), patch.object(
            match_daemon, "admin_id", return_value=None
        ):
            self.assertEqual(match_daemon.authorized_owner_ids(), ())

    def test_daemon_source_uses_owner_set_queue_operations(self):
        source = open(match_daemon.__file__, encoding="utf-8").read()
        self.assertIn("engine.reconcile_alert_owners, owners", source)
        self.assertIn("engine.enqueue_new_alerts_for_owners", source)
        self.assertIn("engine.due_alerts_for_owners", source)
        self.assertIn("central_owner_ids(ROOT)", source)


if __name__ == "__main__":
    unittest.main()
