from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from shared.vm_core.relationship_progress import relationship_manager_progress


class RelationshipProgressTests(unittest.TestCase):
    def _root_with_db(self):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        data = root / "shared" / "exports" / "VM_Relationship_Manager"
        data.mkdir(parents=True)
        db = data / "vm_relationships.db"
        con = sqlite3.connect(db)
        con.executescript(
            """
            CREATE TABLE contacts(
                telegram_id INTEGER PRIMARY KEY,
                relationship_type TEXT,
                activity_status TEXT
            );
            CREATE TABLE contact_intelligence(
                telegram_id INTEGER PRIMARY KEY,
                health_score INTEGER,
                momentum_label TEXT,
                lifecycle_stage TEXT,
                days_overdue INTEGER,
                suggested_action TEXT,
                computed_at TEXT
            );
            INSERT INTO contacts VALUES(101,'supplier','active');
            INSERT INTO contacts VALUES(102,'customer','dormant');
            INSERT INTO contact_intelligence VALUES(101,80,'growing','active',0,NULL,'2026-09-03T00:00:00Z');
            INSERT INTO contact_intelligence VALUES(102,30,'declining','dormant',5,'Review relationship manually','2026-09-03T00:00:00Z');
            """
        )
        con.commit(); con.close()
        return tmp, root, db

    def test_relationship_attention_and_coverage_are_visible(self):
        tmp, root, _ = self._root_with_db(); self.addCleanup(tmp.cleanup)
        snapshot = relationship_manager_progress(root)
        self.assertEqual(snapshot["headline"], "VM RELATIONSHIP MANAGER - UNIVERSAL PROGRESS")
        self.assertEqual(snapshot["overall"]["percent"], 100)
        self.assertEqual(snapshot["overall"]["status"], "ATTENTION")
        self.assertEqual(snapshot["metrics"]["contacts"], 2)
        self.assertEqual(snapshot["metrics"]["overdue"], 1)
        self.assertEqual(snapshot["metrics"]["dormant"], 1)
        self.assertEqual(snapshot["metrics"]["growing_or_surging"], 1)
        self.assertEqual(snapshot["group"]["label"], "Contact 102")
        self.assertIn("Review relationship manually", snapshot["task"]["detail"])

    def test_healthy_relationships_report_ready(self):
        tmp, root, db = self._root_with_db(); self.addCleanup(tmp.cleanup)
        con = sqlite3.connect(db)
        con.execute("DELETE FROM contacts WHERE telegram_id=102")
        con.execute("DELETE FROM contact_intelligence WHERE telegram_id=102")
        con.commit(); con.close()
        snapshot = relationship_manager_progress(root)
        self.assertEqual(snapshot["overall"]["status"], "READY")
        self.assertEqual(snapshot["metrics"]["low_health"], 0)
        self.assertFalse(snapshot["recovery_messages"])

    def test_missing_database_degrades_safely(self):
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = relationship_manager_progress(Path(tmp))
        self.assertEqual(snapshot["overall"]["status"], "DEGRADED")
        self.assertTrue(snapshot["recovery_messages"])


if __name__ == "__main__":
    unittest.main()
