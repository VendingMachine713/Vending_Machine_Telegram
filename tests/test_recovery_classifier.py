import unittest
from shared.vm_core.recovery_classifier import classify_finding


class RecoveryClassifierTests(unittest.TestCase):
    def policy(self, **kw):
        base = {
            "auto_start": False,
            "auto_restart": False,
            "blocked_failure_classes": {
                "AUTHENTICATION","CREDENTIALS","SESSION","DELIVERY_AMBIGUITY","DATABASE_CORRUPTION"
            },
        }
        base.update(kw)
        return base

    def test_process_down_can_be_auto_recoverable_only_by_policy(self):
        d = classify_finding("A", "PROCESS", "runtime stopped", process_alive=False,
                             policy=self.policy(auto_restart=True))
        self.assertEqual(d.classification, "AUTO_RECOVER")
        self.assertEqual(d.action, "RESTART_SERVICE")

    def test_delivery_ambiguity_is_blocked(self):
        d = classify_finding("Poster", "SEND", "delivery uncertain after timeout",
                             process_alive=False, policy=self.policy(auto_restart=True))
        self.assertEqual(d.classification, "BLOCKED")
        self.assertFalse(d.automatic)

    def test_live_process_with_expired_heartbeat_requires_review(self):
        d = classify_finding("A", "HEARTBEAT_EXPIRED", "age 400s",
                             process_alive=True, policy=self.policy(auto_restart=True))
        self.assertEqual(d.classification, "REVIEW_REQUIRED")

    def test_telegram_pressure_waits_instead_of_restart(self):
        d = classify_finding("A", "TELEGRAM", "flood wait 60 seconds",
                             process_alive=False, policy=self.policy(auto_restart=True))
        self.assertEqual(d.classification, "WAIT_AND_RETRY")
        self.assertEqual(d.action, "WAIT")


if __name__ == "__main__":
    unittest.main()
