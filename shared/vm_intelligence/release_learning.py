from __future__ import annotations
from datetime import datetime,timezone,timedelta

class ReleaseLearning:
    def __init__(self,store):self.store=store

    def evaluate(self,current_score,min_age_minutes=30):
        cutoff=(datetime.now(timezone.utc)-timedelta(minutes=min_age_minutes)).isoformat()
        changed=[]
        with self.store.connect() as con:
            rows=con.execute("""SELECT * FROM release_events WHERE status='observing'
                AND detected_at_utc<=? ORDER BY release_event_id""",(cutoff,)).fetchall()
            for r in rows:
                base=r["baseline_score"]
                if base is None:status="insufficient_baseline";delta=None
                else:
                    delta=round(float(current_score)-float(base),2)
                    status="improved" if delta>=2 else "regressed" if delta<=-2 else "neutral"
                con.execute("""UPDATE release_events SET status=?,evaluated_score=?,notes=?
                    WHERE release_event_id=?""",
                    (status,current_score,
                     "Ecosystem score comparison; treat as observational unless backed by a controlled experiment.",
                     r["release_event_id"]))
                changed.append({"source":r["source"],"status":status,"delta":delta})
        return changed
