from __future__ import annotations

class InsightsEngine:
    def build(self, *, scorecard, incidents, recommendations, opportunities, goals, integrated, techdebt):
        rows=[]
        for i in incidents:
            weight={"critical":100,"high":80,"medium":55,"low":25}.get(i["severity"],40)
            rows.append({"priority":weight,"type":"incident","source":i["source"],
                         "title":i["title"],"detail":i["category"]})
        for r in recommendations[:10]:
            weight={"critical":95,"high":75,"medium":50,"low":20}.get(r["severity"],35)
            rows.append({"priority":weight,"type":"recommendation","source":r["source"],
                         "title":r["title"],"detail":r["rationale"]})
        for o in opportunities[:10]:
            rows.append({"priority":int(float(o["confidence"])*60),"type":"automation",
                         "source":o["source"],"title":o["title"],"detail":o["rationale"]})
        for g in goals:
            if g["status"]=="missed":
                rows.append({"priority":70,"type":"goal","source":"VM_Intelligence",
                             "title":"Goal missed: "+g["title"],
                             "detail":f"actual={g['actual']} target {g['operator']} {g['target']}"})
        sap=integrated.get("Smart_Auto_Poster_V2",{}).get("metrics",{})
        if sap.get("success_rate_24h") is not None:
            rows.append({"priority":30,"type":"performance","source":"Smart_Auto_Poster_V2",
                         "title":f"SAP 24h success rate: {sap['success_rate_24h']:.1f}%",
                         "detail":f"sent={int(sap.get('sent_24h',0))} failed={int(sap.get('failed_24h',0))}"})
        rows.sort(key=lambda x:(-x["priority"],x["source"],x["title"]))
        return rows[:12]
