from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from shared.vm_core.autoposter_recovery import smart_auto_poster_recovery_gate
from shared.vm_core.recovery import recovery_plan


class AutoPosterRecoveryGateTests(unittest.TestCase):
    def _root_with_db(self):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        data = root / "bots" / "Smart_Auto_Poster_V2" / "data"
        data.mkdir(parents=True)
        db = data / "smart_autoposter.sqlite3"
        con = sqlite3.connect(db)
        con.executescript(
            """
            CREATE TABLE queue(id INTEGER PRIMARY KEY,status TEXT NOT NULL);
            CREATE TABLE delivery_attempts(
                id INTEGER PRIMARY KEY,
                queue_job_id INTEGER NOT NULL,
                outcome TEXT NOT NULL
            );
            """
        )
        con.commit()
        con.close()
        return tmp, root, db

    def test_clear_queue_is_safe_for_lifecycle_restart_preflight(self):
        tmp, root, _ = self._root_with_db()
        try:
            gate = smart_auto_poster_recovery_gate(root)
            self.assertTrue(gate["safe"])
            self.assertEqual(gate["classification"], "CLEAR")
            self.assertEqual(gate["metrics"]["uncertain_queue"], 0)
            self.assertEqual(gate["metrics"]["open_delivery_attempts"], 0)
        finally:
            tmp.cleanup()

    def test_uncertain_queue_blocks_recovery(self):
        tmp, root, db = self._root_with_db()
        try:
            con = sqlite3.connect(db)
            con.execute("INSERT INTO queue(id,status) VALUES(1,'uncertain')")
            con.commit(); con.close()
            gate = smart_auto_poster_recovery_gate(root)
            self.assertFalse(gate["safe"])
            self.assertIn("UNCERTAIN", gate["reason"])
            self.assertEqual(gate["metrics"]["uncertain_queue"], 1)
        finally:
            tmp.cleanup()

    def test_acknowledged_open_attempt_blocks_recovery(self):
        tmp, root, db = self._root_with_db()
        try:
            con = sqlite3.connect(db)
            con.execute("INSERT INTO queue(id,status) VALUES(1,'sending')")
            con.execute("INSERT INTO delivery_attempts(id,queue_job_id,outcome) VALUES(1,1,'acknowledged')")
            con.commit(); con.close()
            gate = smart_auto_poster_recovery_gate(root)
            self.assertFalse(gate["safe"])
            self.assertEqual(gate["metrics"]["acknowledged_open_attempts"], 1)
            self.assertIn("acknowledged", gate["reason"].lower())
        finally:
            tmp.cleanup()

    def test_missing_database_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            gate = smart_auto_poster_recovery_gate(Path(tmp))
            self.assertFalse(gate["safe"])
            self.assertEqual(gate["classification"], "BLOCKED")

    @patch("shared.vm_core.recovery.smart_auto_poster_recovery_gate")
    @patch("shared.vm_core.recovery.runtime_configuration_status")
    @patch("shared.vm_core.recovery._manifest_policy")
    @patch("shared.vm_core.recovery.discover_bots")
    @patch("shared.vm_core.recovery.service_status")
    def test_recovery_plan_uses_poster_gate_before_lifecycle_action(self, status, discover, policy, runtime, poster_gate):
        status.return_value = [{"name": "Smart_Auto_Poster_V2", "process_alive": False, "runtime_status": "STOPPED"}]
        discover.return_value = [SimpleNamespace(folder="Smart_Auto_Poster_V2", classification="CANONICAL", path="/tmp/poster")]
        runtime.return_value = {"configured": True, "missing_env_names": []}
        policy.return_value = {"auto_start": True, "auto_restart": True}
        poster_gate.return_value = {"safe": False, "reason": "1 UNCERTAIN queue item requires reconciliation"}

        plan = recovery_plan(Path("/tmp/project"))
        decision = plan["decisions"][0]
        self.assertEqual(decision["classification"], "BLOCKED")
        self.assertEqual(decision["action"], "RECONCILE")
        self.assertFalse(decision["automatic"])
        self.assertEqual(plan["summary"]["automatic_candidates"], 0)
        self.assertTrue(plan["safety"]["autoposter_delivery_certainty_required"])


if __name__ == "__main__":
    unittest.main()
