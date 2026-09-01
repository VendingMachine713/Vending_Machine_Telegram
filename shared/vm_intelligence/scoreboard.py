from __future__ import annotations

class BotScoreboard:
    def build(self,integrated):
        rows=[]
        for source,data in integrated.items():
            if source=="VM_Platform":continue
            m=data.get("metrics",{});score=100.0;reasons=[]
            if not data.get("available"):
                score-=20;reasons.append("limited telemetry")
            if m.get("process_alive") == 0 and m.get("auto_restart")==1:
                score-=60;reasons.append("managed process down")
            if source=="Smart_Auto_Poster_V2":
                sr=m.get("success_rate_24h")
                if sr is not None:score-=max(0,(95-sr)*1.5)
                ah=m.get("account_health_avg")
                if ah is not None:score-=max(0,(80-ah)*.5)
                if m.get("uncertain_queue",0):score-=min(25,m["uncertain_queue"]*5);reasons.append("uncertain deliveries")
            if source=="VM_Relationship_Manager":
                score-=min(30,(m.get("health_errors_24h") or 0)*10)
            if source=="VM_Guard" and m.get("legacy_alive")==0:
                score-=20;reasons.append("legacy component offline")
            rows.append({"source":source,"score":round(max(0,min(100,score)),1),"reasons":reasons})
        return sorted(rows,key=lambda x:(x["score"],x["source"]))
