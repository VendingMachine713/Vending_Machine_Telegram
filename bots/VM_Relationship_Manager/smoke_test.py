from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from backup_manager import BackupManager
from database import Database
from maintenance_engine import MaintenanceEngine
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

        # Core v1-v4 regression contact.
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

        # v6 regression: high-confidence structured evidence is auto-applied in SAFE mode.
        auto_tid = 444
        engine.upsert_identity(auto_tid, "autocustomer", "Auto Customer", now - timedelta(days=5))
        engine.add_tag(auto_tid, "customer")
        auto_cls = engine.classification.compute(auto_tid, auto_apply=True)
        auto_contact = db.one("SELECT * FROM contacts WHERE telegram_id=?", (auto_tid,))
        assert auto_cls["predicted_type"] == "customer"
        assert int(auto_cls["confidence"] or 0) >= 90
        assert auto_contact["relationship_type"] == "customer"
        assert auto_cls["decision_state"] == "applied" and auto_cls["auto_applied"] == 1

        # Manual type changes lock classifier ownership and cannot be overwritten.
        locked_tid = 555
        engine.upsert_identity(locked_tid, "locked", "Locked Contact", now - timedelta(days=5))
        engine.add_tag(locked_tid, "supplier")
        engine.set_relationship_type(locked_tid, "partner", 1)
        locked_cls = engine.classification.compute(locked_tid, auto_apply=True)
        locked_contact = db.one("SELECT relationship_type FROM contacts WHERE telegram_id=?", (locked_tid,))
        assert locked_contact["relationship_type"] == "partner"
        assert locked_cls["admin_locked"] == 1 and locked_cls["decision_state"] == "locked"

        # Assist mode calculates but does not auto-apply.
        assist_tid = 666
        engine.upsert_identity(assist_tid, "assist", "Assist Contact", now)
        engine.add_tag(assist_tid, "vendor")
        engine.autonomy.set_mode("assist", 1)
        assist_cls = engine.classification.compute(assist_tid, auto_apply=True)
        assert db.one("SELECT relationship_type FROM contacts WHERE telegram_id=?", (assist_tid,))["relationship_type"] == "unknown"
        assert assist_cls["decision_state"] == "suggested"
        engine.autonomy.set_mode("safe", 1)

        # v6 action queue: due work becomes a deduplicated exception action.
        action_goal = engine.goals.create(
            auto_tid, "Follow up smoke customer", 1, priority=90,
            target_at=(now - timedelta(minutes=5)).isoformat(), next_step="Review next step",
        )
        engine.recalculate_contact(auto_tid)
        engine.priority.compute(auto_tid)
        engine.actions.compute(auto_tid)
        contact_actions = engine.actions.for_contact(auto_tid)
        assert any(a["action_key"] == "goal_due" for a in contact_actions)
        top_actions = engine.actions.top(20, 50)
        assert any(a["telegram_id"] == auto_tid for a in top_actions)

        # Action resolution + re-compute stays deterministic.
        goal_action = next(a for a in contact_actions if a["action_key"] == "goal_due")
        assert engine.actions.resolve(goal_action["id"], "done")
        engine.goals.complete(action_goal["id"])
        engine.actions.compute(auto_tid)
        assert not any(a["action_key"] == "goal_due" for a in engine.actions.for_contact(auto_tid))

        # v6: dismissed actions stay suppressed while the underlying signal remains present.
        dismiss_goal = engine.goals.create(
            assist_tid, "Dismissible smoke goal", 1, priority=90,
            target_at=(now - timedelta(minutes=10)).isoformat(), next_step="Test fatigue suppression",
        )
        engine.priority.compute(assist_tid)
        engine.actions.compute(assist_tid)
        dismiss_action = next(a for a in engine.actions.for_contact(assist_tid) if a["action_key"] == "goal_due")
        assert engine.actions.resolve(dismiss_action["id"], "dismissed")
        engine.actions.compute(assist_tid)
        assert not any(a["action_key"] == "goal_due" for a in engine.actions.for_contact(assist_tid))
        fb = db.one("SELECT outcome FROM action_feedback WHERE action_id=? ORDER BY id DESC LIMIT 1", (dismiss_action["id"],))
        assert fb and fb["outcome"] == "dismissed"
        engine.goals.complete(dismiss_goal["id"])

        # v6: classifier calibration is conservative and can quarantine repeatedly disputed types.
        for idx in range(5):
            db.execute(
                "INSERT INTO classification_feedback(telegram_id,predicted_type,confidence,final_type,outcome,source,details,created_at) VALUES (?,?,?,?,?,?,?,?)",
                (assist_tid, "vendor", 90, "partner", "overridden", "admin", f"smoke disagreement {idx}", now.isoformat()),
            )
        cal_rows = engine.calibration.refresh()
        vendor_policy = engine.calibration.policy_for("vendor")
        assert vendor_policy["auto_enabled"] is False and vendor_policy["threshold"] == 99
        assert any(r["relationship_type"] == "vendor" for r in cal_rows)

        # v6: integration emissions are idempotent within the hourly contract bucket.
        first_event = engine.integration.emit("maintenance_warning", None, {"code": "smoke"})
        second_event = engine.integration.emit("maintenance_warning", None, {"code": "smoke"})
        assert first_event == second_event
        deduped = db.one("SELECT COUNT(*) n FROM integration_events WHERE event_type='maintenance_warning' AND payload_json LIKE '%smoke%'")["n"]
        assert deduped == 1

        # v6: exception policy caps routine work but never hides critical work.
        policy = engine.exception_policy.summary()
        assert policy["limit"] >= 1 and policy["critical_threshold"] >= policy["threshold"]

        # v6: operational SLO snapshot is persisted.
        ops = engine.operations.capture(run_integrity=True)
        assert 0 <= ops["health_score"] <= 100 and ops["status"] in {"pass", "warn", "critical"}
        assert engine.operations.latest() is not None

        brief = engine.briefing.build()
        assert "top_priorities" in brief and "high_disengagement_risk" in brief
        assert "unknown_contacts" in brief and "exception_actions" in brief
        assert "policy_selected_exceptions" in brief and "top_exception_actions" in brief

        engine.query.save_view(1, "priority", "priority>=0 type:regular")
        rows = engine.query.search("priority>=0 type:regular")
        assert any(r["telegram_id"] == tid for r in rows)
        rows = engine.query.search("predicted:customer classconfidence>=90")
        assert any(r["telegram_id"] == auto_tid for r in rows)

        engine.recalculate_behavior_all()
        engine.recalculate_network_all()
        engine.sessions.compute_all()
        engine.quality.compute_all()
        engine.forecast.compute_all()
        engine.calibration.refresh()
        cls_stats = engine.classification.compute_all(auto_apply=True)
        engine.priority.refresh_all()
        action_stats = engine.actions.compute_all()
        engine.segments.compute_all()
        engine.automation.evaluate_all()
        exported = engine.integration.export_all()
        assert exported["contacts"] >= 5
        assert cls_stats["computed"] >= 5 and action_stats["contacts"] >= 5

        report = engine.reporting.build("weekly")
        assert report["total_contacts"] >= 5

        backups = BackupManager(db, root / "backups")
        backup = backups.create("smoke")
        assert backup["status"] == "verified" and Path(backup["path"]).exists()

        maintenance = MaintenanceEngine(db, root / "backups", engine.integration)
        maintained = maintenance.run_safe(allow_backup=True)
        assert maintained["status"] in {"pass", "warn"}
        assert any(a["action"] == "sqlite_optimize_checkpoint" for a in maintained["actions"])

        before = profile["interaction_count"]
        engine.privacy.set_excluded(tid, True, "smoke")
        engine.upsert_interaction(tid, "testuser", "Test User", -1001, "Smoke Group", now)
        after = db.one("SELECT interaction_count FROM contacts WHERE telegram_id=?", (tid,))["interaction_count"]
        assert before == after
        engine.privacy.set_excluded(tid, False, "smoke")

        assert db.meta("schema_version") == "6.0.0"
        assert db.integrity_check() == ["ok"]
        print("SMOKE TEST PASSED â€” VM Relationship Manager 6.0")
        print({
            "telegram_id": tid,
            "relationship_score": db.one("SELECT relationship_score FROM contacts WHERE telegram_id=?", (tid,))["relationship_score"],
            "reciprocity_score": behavior["reciprocity_score"],
            "network_reach": network["reach_score"],
            "priority_score": priority["priority_score"],
            "outlook_risk": outlook["disengagement_risk"],
            "data_confidence": quality["confidence_score"],
            "sessions_30": sessions["sessions_30"],
            "auto_classification": auto_contact["relationship_type"],
            "classifier_confidence": auto_cls["confidence"],
            "exception_actions": engine.actions.stats()["exceptions"],
            "policy_selected": engine.exception_policy.summary()["selected"],
            "calibration_quarantined": engine.calibration.summary()["quarantined"],
            "ops_health": engine.operations.latest()["health_score"],
            "autonomy": engine.autonomy.mode(),
            "backup": backup["status"],
            "schema": db.meta("schema_version"),
        })


if __name__ == "__main__":
    run()
