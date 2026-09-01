from __future__ import annotations

class CTOBrain:
    def prioritize(self,inbox,scoreboard,techdebt,efficiency):
        rows=[]
        for x in inbox:
            base={"P0":100,"P1":85,"P2":65,"P3":40,"P4":20}.get(x["priority"],40)
            base += {"incident":8,"security":7,"prediction":4,"goal":0,"config_drift":2}.get(x["type"],0)
            rows.append({"priority_score":min(100,base),"source":x["source"],"title":x["title"],
                         "reason":x["type"],"estimated_effort":"low" if x["type"] in {"incident","goal"} else "medium"})
        for x in scoreboard[:2]:
            if x["score"]<90:
                rows.append({"priority_score":round(90-x["score"]+.0,1),"source":x["source"],
                             "title":"Improve lowest bot operational score",
                             "reason":f"Current score {x['score']}/100","estimated_effort":"medium"})
        for x in efficiency[:5]:
            rows.append({"priority_score":round(x["score"]*.65,1),"source":x["source"],
                         "title":x["title"],"reason":"efficiency","estimated_effort":"medium"})
        if techdebt.get("debt_score",100)<60:
            rows.append({"priority_score":55,"source":"VM_Core","title":"Reduce structural technical debt",
                         "reason":f"Technical-debt score {techdebt.get('debt_score')}","estimated_effort":"medium"})
        rows.sort(key=lambda x:-float(x["priority_score"]))
        return rows[:15]
