from __future__ import annotations

class IntelligenceInbox:
    def build(self,incidents,recommendations,goals,opportunities,predictive,security=None,config_drift=None):
        rows=[]
        for x in incidents:
            p={"critical":"P0","high":"P1","medium":"P2","low":"P3"}.get(x["severity"],"P2")
            rows.append({"priority":p,"source":x["source"],"type":"incident","title":x["title"]})
        for x in (security or {}).get("findings",[]):
            p="P0" if x["severity"]=="critical" else "P1" if x["severity"]=="high" else "P2"
            rows.append({"priority":p,"source":"VM_Security","type":"security","title":x["title"]})
        if (config_drift or {}).get("changes"):
            rows.append({"priority":"P2","source":"VM_Configuration","type":"config_drift",
                         "title":f"{len(config_drift['changes'])} configuration item(s) changed"})
        for x in goals:
            if x["status"]=="missed":
                rows.append({"priority":"P1","source":"VM_Intelligence","type":"goal","title":x["title"]})
        for x in predictive:
            p="P1" if x["severity"]=="high" and x["estimated_periods_to_threshold"]==0 else "P2"
            rows.append({"priority":p,"source":x["source"],"type":"prediction",
                         "title":f"{x['metric']} approaching threshold"})
        for x in recommendations[:10]:
            p="P1" if x["severity"] in {"critical","high"} else "P3"
            rows.append({"priority":p,"source":x["source"],"type":"recommendation","title":x["title"]})
        for x in opportunities[:10]:
            rows.append({"priority":"P3","source":x["source"],"type":"automation","title":x["title"]})
        rank={"P0":0,"P1":1,"P2":2,"P3":3,"P4":4}
        rows.sort(key=lambda x:(rank[x["priority"]],x["source"],x["title"]))
        return rows[:50]
