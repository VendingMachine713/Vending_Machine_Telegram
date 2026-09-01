from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from shared.vm_core.activity_adapter import collect_search_activity
from shared.vm_core.adapters import collect_autoposter_evidence
from shared.vm_core.db import PlatformDB
from shared.vm_core.intelligence import materialize_intelligence
from shared.vm_core.relationship_adapter import collect_relationship_presence


class VMIntelligenceAdapterTests(unittest.TestCase):
    def _root(self, tmp: str) -> Path:
        root = Path(tmp)
        (root / "bots" / "Smart_Auto_Poster_V2" / "data").mkdir(parents=True)
        (root / "bots" / "Universal_Search" / "data").mkdir(parents=True)
        (root / "bots" / "VM_Relationship_Manager").mkdir(parents=True)
        (root / "shared" / "exports" / "VM_Relationship_Manager").mkdir(parents=True)
        return root

    def _autoposter_db(self, root: Path) -> Path:
        path = root / "bots" / "Smart_Auto_Poster_V2" / "data" / "smart_autoposter.sqlite3"
        con = sqlite3.connect(path)
        con.executescript("""
            CREATE TABLE campaigns(campaign_id TEXT PRIMARY KEY, enabled INTEGER, lifecycle_state TEXT);
            CREATE TABLE destinations(
                group_id INTEGER PRIMARY KEY,group_name TEXT,enabled INTEGER,needs_review INTEGER,
                quarantine_until TEXT,primary_access INTEGER,secondary_access INTEGER,
                last_post_at TEXT,next_eligible_at TEXT
            );
            CREATE TABLE accounts(
                account_key TEXT PRIMARY KEY,enabled INTEGER,authorized INTEGER,telegram_user_id INTEGER,
                health_score INTEGER,cooldown_until TEXT,last_success_at TEXT,last_failure_at TEXT
            );
            CREATE TABLE queue(
                id INTEGER PRIMARY KEY,campaign_id TEXT,group_id INTEGER,account_key TEXT,status TEXT,
                error_kind TEXT,last_error TEXT,updated_at TEXT
            );
        """)
        now = datetime.now(timezone.utc).isoformat()
        con.execute("INSERT INTO campaigns VALUES('main',1,'active')")
        con.execute("INSERT INTO destinations VALUES(123,'Test Group',1,0,NULL,1,1,NULL,NULL)")
        con.execute("INSERT INTO accounts VALUES('primary',1,1,42,98,NULL,NULL,NULL)")
        con.execute("INSERT INTO queue VALUES(7,'main',123,'primary','uncertain','timeout','do not retry',?)", (now,))
        con.commit(); con.close()
        return path

    def _relationship_db(self, root: Path, chat_id: int = 123) -> Path:
        path = root / "shared" / "exports" / "VM_Relationship_Manager" / "vm_relationships.db"
        con = sqlite3.connect(path)
        con.executescript("""
            CREATE TABLE contacts(
                telegram_id INTEGER PRIMARY KEY,relationship_type TEXT,activity_status TEXT,
                verification_status TEXT,relationship_score INTEGER,trust_score INTEGER,last_seen TEXT
            );
            CREATE TABLE contact_intelligence(
                telegram_id INTEGER PRIMARY KEY,health_score INTEGER,momentum_label TEXT,momentum_score INTEGER,
                lifecycle_stage TEXT,days_overdue INTEGER,suggested_action TEXT,computed_at TEXT
            );
            CREATE TABLE contact_groups(
                telegram_id INTEGER,chat_id INTEGER,interaction_count INTEGER,last_seen TEXT
            );
            CREATE TABLE attention_queue(
                id INTEGER PRIMARY KEY,telegram_id INTEGER,priority TEXT,category TEXT,title TEXT,
                created_at TEXT,status TEXT
            );
        """)
        now = datetime.now(timezone.utc).isoformat()
        con.execute("INSERT INTO contacts VALUES(999,'supplier','dormant','verified',55,80,?)", (now,))
        con.execute("INSERT INTO contact_intelligence VALUES(999,30,'fading',-50,'dormant',20,'Review contact',?)", (now,))
        con.execute("INSERT INTO contact_groups VALUES(999,?,12,?)", (chat_id, now))
        con.commit(); con.close()
        return path

    def _search_db(self, root: Path, chat_id: int = 123) -> Path:
        path = root / "bots" / "Universal_Search" / "data" / "universal_search.db"
        con = sqlite3.connect(path)
        con.executescript("""
            CREATE TABLE chats(chat_id INTEGER PRIMARY KEY,title TEXT,username TEXT);
            CREATE TABLE indexed_messages(
                chat_id INTEGER,message_id INTEGER,sender_id INTEGER,date_utc TEXT,text TEXT,
                has_media INTEGER,is_ad INTEGER,is_available INTEGER,
                PRIMARY KEY(chat_id,message_id)
            );
        """)
        con.execute("INSERT INTO chats VALUES(?, 'Test Group', NULL)", (chat_id,))
        now = datetime.now(timezone.utc)
        message_id = 1
        for day in range(2, 8):
            con.execute("INSERT INTO indexed_messages VALUES(?,?,?,?, '',0,0,1)", (chat_id,message_id,1,(now-timedelta(days=day)).isoformat()))
            message_id += 1
        for hour in range(10):
            con.execute("INSERT INTO indexed_messages VALUES(?,?,?,?, '',0,?,1)", (chat_id,message_id,1,(now-timedelta(hours=hour)).isoformat(),int(hour < 3)))
            message_id += 1
        con.commit(); con.close()
        return path

    def test_autoposter_adapter_preserves_uncertain_source_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            source = self._autoposter_db(root)
            result = collect_autoposter_evidence(root)
            self.assertEqual(result["uncertain"], 1)
            source_con = sqlite3.connect(source)
            try:
                self.assertEqual(source_con.execute("SELECT status FROM queue WHERE id=7").fetchone()[0], "uncertain")
            finally:
                source_con.close()
            db = PlatformDB(root=root)
            incident = db.incidents(5, "OPEN")[0]
            self.assertIn("UNCERTAIN", incident["summary"])
            self.assertFalse(json.loads(incident["evidence_json"])["automatic_retry"])

    def test_search_adapter_detects_activity_spike_without_copying_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            self._search_db(root)
            result = collect_search_activity(root)
            self.assertEqual(result["spikes"], 1)
            signal = PlatformDB(root=root).signals(5)[0]
            self.assertEqual(signal["signal_type"], "search_activity_spike")
            evidence = json.loads(signal["evidence_json"])
            self.assertNotIn("text", evidence)
            self.assertGreaterEqual(evidence["recent_24h_messages"], 10)

    def test_relationship_presence_maps_dormant_contact_to_chat(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            self._relationship_db(root)
            result = collect_relationship_presence(root)
            self.assertEqual(result["dormant_memberships"], 1)
            signal = PlatformDB(root=root).signals(5)[0]
            self.assertEqual(signal["subject_type"], "chat")
            self.assertEqual(signal["subject_id"], "123")
            self.assertEqual(signal["signal_type"], "relationship_dormant_presence")

    def test_cross_bot_reasoning_requires_same_chat_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            self._autoposter_db(root)
            self._relationship_db(root, chat_id=123)
            self._search_db(root, chat_id=123)
            materialize_intelligence(root)
            opportunities = [s for s in PlatformDB(root=root).signals(100) if s["signal_type"] == "relationship_activity_opportunity"]
            self.assertEqual(len(opportunities), 1)
            self.assertEqual(opportunities[0]["subject_id"], "123")
            evidence = json.loads(opportunities[0]["evidence_json"])
            self.assertEqual(evidence["contact_ids"], ["999"])


if __name__ == "__main__":
    unittest.main()
