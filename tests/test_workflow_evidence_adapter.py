import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from shared.vm_core.db import PlatformDB
from shared.vm_core.workflow_evidence_adapter import collect_product_workflow_evidence


class WorkflowEvidenceAdapterTests(unittest.TestCase):
    def test_projects_bounded_aggregate_counts_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            search = root / "bots" / "Universal_Search" / "data"; search.mkdir(parents=True)
            con = sqlite3.connect(search / "universal_search.db")
            con.executescript("CREATE TABLE marketplace_listings(kind TEXT,status TEXT); CREATE TABLE marketplace_matches(status TEXT); CREATE TABLE marketplace_match_feedback(outcome TEXT);")
            con.execute("INSERT INTO marketplace_listings VALUES('sale','active')"); con.execute("INSERT INTO marketplace_matches VALUES('new')"); con.execute("INSERT INTO marketplace_match_feedback VALUES('positive')"); con.commit(); con.close()
            rm = root / "shared" / "exports" / "VM_Relationship_Manager"; rm.mkdir(parents=True)
            con = sqlite3.connect(rm / "vm_relationships.db")
            con.executescript("CREATE TABLE business_import_runs(valid_rows INTEGER,duplicate_rows INTEGER,problem_rows INTEGER); CREATE TABLE admin_audit(action TEXT);")
            con.execute("INSERT INTO business_import_runs VALUES(2,1,0)"); con.execute("INSERT INTO admin_audit VALUES('business_transaction_corrected')"); con.commit(); con.close()
            result = collect_product_workflow_evidence(root)
            self.assertEqual(result["universal_search"]["new_match_count"], 1)
            self.assertEqual(result["relationship_manager"]["correction_count"], 1)
            shared = PlatformDB(root=root); rows = shared.signals(20)
            self.assertTrue(any(r["signal_key"] == "workflow:universal_search:marketplace" for r in rows))
            self.assertNotIn("1001", json.dumps(rows))


if __name__ == "__main__":
    unittest.main()
