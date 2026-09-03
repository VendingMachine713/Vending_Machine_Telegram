from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from backup_manager import BackupManager
from database import Database
from relationship_engine import RelationshipEngine


def run():
    with TemporaryDirectory() as td:
        root = Path(td)
        db = Database(root / "smoke.db")
        engine = RelationshipEngine(db)
        engine.integration.export_dir = root / "integration"
        engine.integration.export_dir.mkdir(parents=True, exist_ok=True)

        now = datetime.now(timezone.utc)
        tid = 123456789

        engine.upsert_identity(tid, "testuser", "Test User", now - timedelta(days=30))
        for day in (28, 21, 14, 7, 0):
            engine.upsert_interaction(tid, "testuser", "Test User", -1001, "Smoke Group", now - timedelta(days=day))
        engine.set_relationship_type(tid, "regular", 1)
        engine.set_verification(tid, "verified", 1, "smoke test")
        engine.recalculate_contact(tid)
        profile = db.one("SELECT * FROM contacts WHERE telegram_id=?", (tid,))
        assert profile["interaction_count"] == 5 and profile["active_days"] == 5

        for idx, day in enumerate((8, 5, 2), start=1):
            base = now - timedelta(days=day)
            engine.record_private_interaction(tid, tid, 100 + idx * 2, "incoming", base)
            engine.record_private_interaction(tid, tid, 101 + idx * 2, "outgoing", base + timedelta(minutes=12))
        behavior = engine.get_behavior(tid, refresh=True)
        assert behavior["incoming_30"] == 3 and behavior["outgoing_30"] == 3

        engine.upsert_identity(tid, "testuser", "Test User", now, -1002, "Second Group", "smoke")
        engine.upsert_identity(222, "other", "Other", now, -1002, "Second Group", "smoke")
        engine.upsert_identity(333, "third", "Third", now, -1001, "Smoke Group", "smoke")
        network = engine.get_network(tid, refresh=True)
        assert network["shared_groups"] >= 2
        assert engine.groups.compute_all() >= 2

        deal = engine.opportunities.create(tid, "Smoke opportunity", 1)
        engine.opportunities.set_value(deal["id"], 1000, "AUD")
        deal = engine.opportunities.set_stage(deal["id"], "interested")
        assert deal["value_cents"] == 100000 and deal["health_score"] >= 0

        memory = engine.memory.add(tid, "commercial", "preferred_contact", "Telegram", 1)
        assert memory["memory_key"] == "preferred_contact" and len(engine.memory.list(tid)) == 1

        engine.recalculate_contact(tid)
        priority = engine.priority.get(tid, refresh=True)
        assert priority is not None and 0 <= priority["priority_score"] <= 100

        engine.integration.ingest_external_signal("vm_guard", "test_signal", tid, 2, "smoke review")
        pending = engine.risk.pending()
        assert pending
        engine.risk.review(pending[0]["id"], "dismissed", 1)


        sessions = engine.sessions.compute(tid)
        assert sessions["sessions_30"] >= 3 and sessions["avg_messages_per_session"] >= 2

        quality = engine.quality.compute(tid)
        assert 0 <= quality["completeness_score"] <= 100 and 0 <= quality["confidence_score"] <= 100

        outlook = engine.forecast.compute(tid)
        assert 0 <= outlook["disengagement_risk"] <= 100 and 0 <= outlook["confidence"] <= 100

        goal = engine.goals.create(
            tid,
            "Confirm smoke-test next step",
            1,
            priority=80,
            target_at=(now - timedelta(hours=1)).isoformat(),
            next_step="Complete validation",
        )
        assert goal["status"] == "active" and engine.goals.due()
        engine.automation.process_goal_due()
        priority = engine.priority.get(tid, refresh=True)
        assert any(r["code"] == "goal_due" for r in engine.priority.reasons(tid))
        completed = engine.goals.complete(goal["id"])
        assert completed["status"] == "completed" and completed["progress_pct"] == 100

        segments = engine.segments.compute(tid)
        assert isinstance(segments, list) and segments
        playbook = engine.playbooks.recommend(tid)
        assert playbook and playbook["steps"]
        brief = engine.briefing.build()
        assert "top_priorities" in brief and "high_disengagement_risk" in brief

        engine.query.save_view(1, "priority", "priority>=0 type:regular")
        rows = engine.query.search("priority>=0 type:regular")
        assert any(r["telegram_id"] == tid for r in rows)

        engine.recalculate_behavior_all(); engine.recalculate_network_all(); engine.sessions.compute_all(); engine.quality.compute_all(); engine.forecast.compute_all(); engine.segments.compute_all(); engine.automation.evaluate_all(); engine.priority.refresh_all()
        exported = engine.integration.export_all()
        assert exported["contacts"] >= 3

        report = engine.reporting.build("weekly")
        assert report["total_contacts"] >= 3

        backups = BackupManager(db, root / "backups")
        backup = backups.create("smoke")
        assert backup["status"] == "verified" and Path(backup["path"]).exists()

        before = profile["interaction_count"]
        engine.privacy.set_excluded(tid, True, "smoke")
        engine.upsert_interaction(tid, "testuser", "Test User", -1001, "Smoke Group", now)
        after = db.one("SELECT interaction_count FROM contacts WHERE telegram_id=?", (tid,))["interaction_count"]
        assert before == after
        engine.privacy.set_excluded(tid, False, "smoke")

        assert db.meta("schema_version") == "4.0.0"
        assert db.integrity_check() == ["ok"]
        print("SMOKE TEST PASSED — VM Relationship Manager 4.0")
        print({
            "telegram_id": tid,
            "relationship_score": db.one("SELECT relationship_score FROM contacts WHERE telegram_id=?", (tid,))["relationship_score"],
            "reciprocity_score": behavior["reciprocity_score"],
            "network_reach": network["reach_score"],
            "priority_score": priority["priority_score"],
            "outlook_risk": outlook["disengagement_risk"],
            "data_confidence": quality["confidence_score"],
            "sessions_30": sessions["sessions_30"],
            "opportunity_health": deal["health_score"],
            "backup": backup["status"],
            "schema": db.meta("schema_version"),
        })


if __name__ == "__main__":
    run()
