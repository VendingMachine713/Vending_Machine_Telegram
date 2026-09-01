from __future__ import annotations
from pathlib import Path
from datetime import datetime,timezone
from .v6_schema import ensure_v6_schema

def _parse(v):
    try:return datetime.fromisoformat(str(v).replace('Z','+00:00'))
    except Exception:return None
class DisasterRecoveryController:
    def __init__(self,store,root):self.store=store;self.root=Path(root);ensure_v6_schema(store)
    def snapshot(self):
        backups=[];root=self.root/'backups';now=datetime.now(timezone.utc)
        if root.is_dir():
            for p in root.glob('*'):
                try:backups.append((p.stat().st_mtime,p))
                except Exception:pass
        backups.sort(reverse=True);latest=backups[0][1] if backups else None
        age=max(0,(now.timestamp()-latest.stat().st_mtime)/60) if latest else None
        with self.store.connect() as con:drills=[dict(r) for r in con.execute('SELECT * FROM disaster_recovery_drills ORDER BY drill_id DESC LIMIT 20').fetchall()]
        verified=[x for x in drills if x.get('restore_verified')]
        last=verified[0] if verified else None
        completed=_parse((last or {}).get('completed_at_utc') or (last or {}).get('started_at_utc'))
        drill_age_days=(now-completed).total_seconds()/86400 if completed else None
        raw=float((last or {}).get('confidence') or 0)
        decay=1.0 if drill_age_days is None else max(.25,1.0-drill_age_days/120.0)
        effective=raw*decay if last else 0.0
        due=(not bool(last)) or (drill_age_days is not None and drill_age_days>30)
        backup_state='missing' if latest is None else 'stale' if age is not None and age>24*60 else 'fresh'
        return {'latest_backup':str(latest) if latest else None,'latest_backup_age_minutes':round(age,1) if age is not None else None,
                'backup_state':backup_state,'last_verified_restore':last,'last_verified_restore_age_days':round(drill_age_days,1) if drill_age_days is not None else None,
                'restore_confidence_pct':round(effective*100,1),'raw_drill_confidence_pct':round(raw*100,1),
                'rpo_minutes':last.get('rpo_minutes') if last else None,'rto_seconds':last.get('rto_seconds') if last else None,
                'drill_due':due,'automatic_destructive_restore':False}
