from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from backup_manager import BackupManager
from config import Settings
from database import Database, utcnow
from relationship_engine import RelationshipEngine


class BackgroundJobs:
    """Periodic maintenance. Safe to restart; cadence is persisted in app_meta."""
    def __init__(self, settings: Settings, db: Database, engine: RelationshipEngine):
        self.settings = settings
        self.db = db
        self.engine = engine
        self.backups = BackupManager(db, settings.backup_dir)
        self._stop = asyncio.Event()

    @staticmethod
    def _due(last_value: str | None, seconds: int) -> bool:
        if not last_value:
            return True
        try:
            return (datetime.now(timezone.utc) - datetime.fromisoformat(last_value)).total_seconds() >= seconds
        except Exception:
            return True

    async def run(self):
        self._stop.clear()
        while not self._stop.is_set():
            cycle_started = datetime.now(timezone.utc)
            try:
                self.engine.process_due_followups()
                self.engine.automation.process_opportunity_due()
                self.engine.opportunities.evaluate_all()

                if self._due(self.db.meta("last_intelligence_maintenance"), 21600):  # 6h
                    contacts = self.engine.recalculate_all()
                    self.engine.recalculate_behavior_all()
                    self.engine.recalculate_network_all()
                    sessions = self.engine.sessions.compute_all()
                    quality = self.engine.quality.compute_all()
                    forecasts = self.engine.forecast.compute_all()
                    groups = self.engine.groups.compute_all()
                    self.engine.automation.evaluate_all()
                    priorities = self.engine.priority.refresh_all()
                    segments = self.engine.segments.compute_all()
                    export_result = self.engine.integration.export_all()
                    self.engine.behavior.prune()
                    self.db.set_meta("last_intelligence_maintenance", utcnow())
                    backlog = self.engine.integration.backlog()
                    self._health(
                        "intelligence_maintenance", "ok",
                        f"contacts={contacts}; sessions={sessions}; quality={quality}; forecasts={forecasts}; "
                        f"segments={segments}; groups={groups}; priorities={priorities}; "
                        f"exported_contacts={export_result['contacts']}; exported_events={export_result['events']}; "
                        f"outbox_backlog={backlog['total'] or 0}",
                    )

                if self._due(self.db.meta("last_daily_backup"), 86400):
                    result = self.backups.create("scheduled")
                    self.db.set_meta("last_daily_backup", utcnow())
                    self._health("daily_backup", "ok" if result["status"] == "verified" else "error",
                                 f"{result['status']} · {result['bytes']} bytes · {result['path']}")
                    integrity = self.db.integrity_check()
                    self._health("database_integrity", "ok" if integrity == ["ok"] else "error", ", ".join(integrity[:3]))
                    self.db.optimize()
                    self.db.checkpoint(truncate=False)

                if self._due(self.db.meta("last_daily_brief"), 86400):
                    import json
                    brief = self.engine.briefing.build()
                    self.db.execute(
                        "INSERT INTO brief_snapshots(brief_type,payload_json,created_at) VALUES ('daily',?,?)",
                        (json.dumps({k:v for k,v in brief.items() if k not in {'top_priorities','overdue_goals'}}, default=str, sort_keys=True), utcnow()),
                    )
                    self.db.set_meta("last_daily_brief", utcnow())
                    self._health("daily_brief", "ok", f"priorities={len(brief['top_priorities'])}; overdue_goals={len(brief['overdue_goals'])}")

                if self._due(self.db.meta("last_weekly_report"), 7 * 86400):
                    report = self.engine.reporting.build("weekly")
                    self.db.set_meta("last_weekly_report", utcnow())
                    self._health("weekly_report", "ok", f"report_id={report['id']}; active={report['active_contacts']}; avg_health={report['average_health']}")

                if self._due(self.db.meta("last_monthly_report"), 30 * 86400):
                    report = self.engine.reporting.build("monthly")
                    self.db.set_meta("last_monthly_report", utcnow())
                    self._health("monthly_report", "ok", f"report_id={report['id']}; active={report['active_contacts']}; avg_health={report['average_health']}")

                # Keep operational tables bounded.
                self.db.execute("DELETE FROM bot_health WHERE id NOT IN (SELECT id FROM bot_health ORDER BY id DESC LIMIT 2500)")
                self.db.execute("DELETE FROM report_snapshots WHERE id NOT IN (SELECT id FROM report_snapshots ORDER BY id DESC LIMIT 120)")
                self.db.execute("DELETE FROM brief_snapshots WHERE id NOT IN (SELECT id FROM brief_snapshots ORDER BY id DESC LIMIT 120)")
                self.db.execute("DELETE FROM integration_events WHERE status='exported' AND id NOT IN (SELECT id FROM integration_events WHERE status='exported' ORDER BY id DESC LIMIT 10000)")
                self._health("scheduler", "ok", f"Background cycle completed in {(datetime.now(timezone.utc)-cycle_started).total_seconds():.1f}s")
            except Exception as exc:
                self._health("scheduler", "error", repr(exc)[:1000])
                raise

            try:
                await asyncio.wait_for(self._stop.wait(), timeout=900)
            except asyncio.TimeoutError:
                pass

    def _health(self, component: str, status: str, details: str):
        self.db.execute(
            "INSERT INTO bot_health (component, status, details, created_at) VALUES (?, ?, ?, ?)",
            (component, status, details, utcnow()),
        )

    async def stop(self):
        self._stop.set()
