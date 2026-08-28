import unittest
from smart_autoposter.account_guard import duplicate_authorized_account_ids, assert_distinct_authorized_accounts


class AccountGuardTests(unittest.TestCase):
    def test_distinct_accounts_pass(self):
        auth = {
            "primary": {"authorized": True, "user_id": 100, "identity": "A"},
            "secondary": {"authorized": True, "user_id": 200, "identity": "B"},
        }
        self.assertEqual([], duplicate_authorized_account_ids(auth))
        assert_distinct_authorized_accounts(auth)

    def test_duplicate_accounts_detected(self):
        auth = {
            "primary": {"authorized": True, "user_id": 100, "identity": "A"},
            "secondary": {"authorized": True, "user_id": 100, "identity": "A2"},
        }
        self.assertEqual([("primary", "secondary", 100)], duplicate_authorized_account_ids(auth))
        with self.assertRaises(RuntimeError):
            assert_distinct_authorized_accounts(auth)

    def test_unauthorized_duplicate_is_ignored(self):
        auth = {
            "primary": {"authorized": True, "user_id": 100},
            "secondary": {"authorized": False, "user_id": 100},
        }
        self.assertEqual([], duplicate_authorized_account_ids(auth))


if __name__ == "__main__":
    unittest.main()
