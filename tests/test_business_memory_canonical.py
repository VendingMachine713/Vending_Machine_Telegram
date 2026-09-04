from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from shared.vm_core.business_memory_adapter import collect_business_memory_signals
from shared.vm_core.canonical_bridge import bridge_legacy_signals
from shared.vm_core.db import PlatformDB


class BusinessMemoryCanonicalTests(unittest.TestCase):
    def _seed_relationship_db(self, root: Path) -> Path:
        db_path = root / "shared" / "exports" / "VM_Relationship_Manager" / "vm_relationships.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(db_path)
        try:
            con.executescript(
                """
                CREATE TABLE business_products (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    normalized_name TEXT NOT NULL,
                    active INTEGER NOT NULL
                );
                CREATE TABLE business_transactions (
                    id INTEGER PRIMARY KEY,
                    telegram_id INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    product_id INTEGER NOT NULL,
                    quantity REAL NOT NULL,
                    occurred_at TEXT NOT NULL
                );
                CREATE TABLE business_product_availability (
                    product_id INTEGER PRIMARY KEY,
                    is_available INTEGER NOT NULL,
                    available_at TEXT,
                    updated_at TEXT
                );
                CREATE TABLE contact_groups (
                    telegram_id INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL
                );
                """
            )
            old = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
            now = datetime.now(timezone.utc).isoformat()
            con.execute(
                "INSERT INTO business_products(id,name,normalized_name,active) VALUES(1,?,?,1)",
                ("Sensitive Product Name", "sensitive product name"),
            )
            con.execute(
                "INSERT INTO business_transactions VALUES(1,999,'client',1,2,?)",
                (old,),
            )
            con.execute(
                "INSERT INTO business_transactions VALUES(2,999,'client',1,3,?)",
                (old,),
            )
            con.execute(
                "INSERT INTO business_product_availability VALUES(1,1,?,?)",
                (now, now),
            )
            con.execute("INSERT INTO contact_groups VALUES(999,123)")
            con.commit()
        finally:
            con.close()
        return db_path

    def test_adapter_emits_aggregate_chat_signals_without_raw_business_identity(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            self._seed_relationship_db(root)

            result = collect_business_memory_signals(root=root, inactive_days=30)
            self.assertTrue(result["available"])
            self.assertEqual(result["reload_signals"], 1)
            self.assertEqual(result["dormant_signals"], 1)

            rows = PlatformDB(root=root).signals(20, "ACTIVE")
            types = {row["signal_type"] for row in rows}
            self.assertIn("business_reload_opportunity", types)
            self.assertIn("business_dormant_client_opportunity", types)
            for row in rows:
                self.assertEqual(row["subject_type"], "chat")
                self.assertEqual(row["subject_id"], "123")
                serialized = row["evidence_json"]
                self.assertNotIn("Sensitive Product Name", serialized)
                self.assertNotIn('"999"', serialized)
                evidence = json.loads(serialized)
                self.assertNotIn("contact_id", evidence)
                self.assertNotIn("product_name", evidence)

    def test_canonical_bridge_publishes_business_signals_without_action_authority(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            self._seed_relationship_db(root)
            collect_business_memory_signals(root=root, inactive_days=30)

            result = bridge_legacy_signals(root=root)
            self.assertEqual(result["eligible"], 2)
            self.assertEqual(result["published"], 2)

            events = PlatformDB(root=root).events(20)
            business = [
                row for row in events
                if str(row.get("event_type") or "").startswith("intelligence.signal.business_")
            ]
            self.assertEqual(len(business), 2)
            payloads = [json.loads(row["payload_json"]) for row in business]
            for payload in payloads:
                text = json.dumps(payload, sort_keys=True)
                self.assertNotIn("Sensitive Product Name", text)
                self.assertNotIn('"999"', text)
                self.assertNotIn("automatic_execution", text)


if __name__ == "__main__":
    unittest.main()
