from __future__ import annotations
from pathlib import Path
from datetime import datetime,timezone,timedelta
import zipfile

class MaintenanceEngine:
    def __init__(self,store,root): self.store=store; self.root=Path(root)

    def run(self,event_retention_days=90,historical_retention_days=180):
        now=datetime.now(timezone.utc)
        event_cutoff=(now-timedelta(days=event_retention_days)).isoformat()
        history_cutoff=(now-timedelta(days=historical_retention_days)).isoformat()
        pruned=self.store.prune_events(event_cutoff)
        history_pruned={}
        with self.store.connect() as con:
            for table,column in (
                ("bot_metrics","observed_at_utc"),("snapshots","created_at_utc"),
                ("goal_evaluations","observed_at_utc"),("intelligence_cycles","completed_at_utc")
            ):
                try:history_pruned[table]=con.execute(f"DELETE FROM {table} WHERE {column}<?",(history_cutoff,)).rowcount
                except Exception:history_pruned[table]=0
            try:
                integrity_rows=con.execute("PRAGMA quick_check").fetchall()
                db_integrity=all(str(r[0]).lower()=="ok" for r in integrity_rows)
            except Exception:
                db_integrity=False
        backups=self.root/"backups";latest=None;integrity=None
        if backups.exists():
            zips=sorted(backups.glob("*.zip"),key=lambda p:p.stat().st_mtime,reverse=True)
            if zips:
                latest=zips[0]
                try:
                    with zipfile.ZipFile(latest) as z:integrity=(z.testzip() is None)
                except Exception:integrity=False
        return {"events_pruned":pruned,"history_pruned":history_pruned,
                "intelligence_db_integrity":db_integrity,
                "latest_backup":str(latest) if latest else None,
                "latest_backup_integrity":integrity}
