from __future__ import annotations
from datetime import datetime,timezone,timedelta

class MetaIntelligence:
    def __init__(self,store):self.store=store

    def analyze(self):
        cutoff=(datetime.now(timezone.utc)-timedelta(days=7)).isoformat()
        with self.store.connect() as con:
            rows=con.execute("""SELECT status,duration_ms,incident_count,metric_sources FROM intelligence_cycles
                WHERE completed_at_utc>=? ORDER BY cycle_id DESC LIMIT 1000""",(cutoff,)).fetchall()
            resolved=con.execute("SELECT COUNT(*) FROM incidents WHERE status='resolved'").fetchone()[0]
            open_count=con.execute("SELECT COUNT(*) FROM incidents WHERE status='open'").fetchone()[0]
            fb=con.execute("""SELECT verdict,COUNT(*) n FROM intelligence_feedback
                GROUP BY verdict""").fetchall()
        total=len(rows);errors=sum(1 for r in rows if r["status"]!="ok")
        avg=sum(float(r["duration_ms"]) for r in rows)/total if total else None
        sources=max([int(r["metric_sources"]) for r in rows],default=0)
        reliability=(1-errors/total)*100 if total else 100
        feedback={str(r["verdict"]):int(r["n"]) for r in fb}
        useful=feedback.get("useful",0);noise=feedback.get("noise",0)
        precision=round(useful/(useful+noise)*100,1) if useful+noise else None
        return {"cycles_7d":total,"cycle_errors":errors,"cycle_reliability_pct":round(reliability,2),
                "avg_cycle_ms":round(avg,1) if avg is not None else None,
                "max_metric_sources":sources,"incidents_open":open_count,"incidents_resolved":resolved,
                "feedback":feedback,"alert_usefulness_pct":precision,
                "self_health":"healthy" if reliability>=99 else "review"}
