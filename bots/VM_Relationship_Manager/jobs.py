from __future__ import annotations

import asyncio
import shutil
from datetime import datetime, timezone
from pathlib import Path

from config import Settings
from database import Database, utcnow
from relationship_engine import RelationshipEngine


class BackgroundJobs:
    def __init__(self, settings: Settings, db: Database, engine: RelationshipEngine):
        self.settings = settings
        self.db = db
        self.engine = engine
        self._stop = asyncio.Event()

    async def run(self):
        while not self._stop.is_set():
            try:
                self.engine.process_due_followups()

                now = datetime.now(timezone.utc)

                last_intel = self.db.one(
                    "SELECT created_at FROM bot_health WHERE component='intelligence_maintenance' ORDER BY id DESC LIMIT 1"
                )
                should_intel = not last_intel or (now - datetime.fromisoformat(last_intel["created_at"])).total_seconds() >= 21600
                if should_intel:
                    self.engine.recalculate_all()
                    self._health(
                        "intelligence_maintenance",
                        "ok",
                        "Relationship health, momentum, lifecycle and smart attention refreshed.",
                    )

                last_daily = self.db.one(
                    "SELECT created_at FROM bot_health WHERE component='daily_backup' ORDER BY id DESC LIMIT 1"
                )
                should_daily = not last_daily or (now - datetime.fromisoformat(last_daily["created_at"])).total_seconds() >= 86400
                if should_daily:
                    self._backup()
                    self._health("daily_backup", "ok", "Relationship database backup attempted.")

                self._health("scheduler", "ok", "Background cycle completed.")
            except Exception as e:
                self._health("scheduler", "error", repr(e))

            try:
                await asyncio.wait_for(self._stop.wait(), timeout=900)  # 15 minutes
            except asyncio.TimeoutError:
                pass

    def _backup(self):
        if not self.settings.database_path.exists():
            return
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        target = self.settings.backup_dir / f"vm_relationships_{stamp}.db"
        shutil.copy2(self.settings.database_path, target)

        backups = sorted(self.settings.backup_dir.glob("vm_relationships_*.db"), reverse=True)
        for old in backups[14:]:
            old.unlink(missing_ok=True)

    def _health(self, component: str, status: str, details: str):
        self.db.execute(
            "INSERT INTO bot_health (component, status, details, created_at) VALUES (?, ?, ?, ?)",
            (component, status, details, utcnow()),
        )

    async def stop(self):
        self._stop.set()
