from __future__ import annotations

from datetime import datetime, timezone

from .v4_schema import ensure_v4_schema


class AttentionBudget:
    def __init__(self,store):self.store=store;ensure_v4_schema(store)
    def snapshot(self):
        with self.store.connect() as con:
            feedback=con.execute("SELECT verdict,COUNT(*) n FROM intelligence_feedback GROUP BY verdict").fetchall()
            decisions=con.execute("SELECT outcome,COUNT(*) n FROM decisions WHERE authority='automatic' GROUP BY outcome").fetchall()
        fb={r["verdict"]:int(r["n"]) for r in feedback};dc={r["outcome"]:int(r["n"]) for r in decisions}
        useful=fb.get("useful",0);noise=fb.get("noise",0);total=useful+noise
        noise_ratio=round(noise/total,3) if total else 0.0
        autonomous=sum(dc.values())
        estimated_minutes_saved=round(autonomous*3.0,1)
        return {"feedback_total":total,"useful":useful,"noise":noise,"noise_ratio":noise_ratio,
                "automatic_decisions":autonomous,"estimated_minutes_saved":estimated_minutes_saved,
                "north_star":"useful autonomous outcomes per unit user attention"}
