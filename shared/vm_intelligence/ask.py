from __future__ import annotations

class AskEngine:
    def __init__(self,brain):self.brain=brain

    def answer(self,question):
        q=(question or "").strip().lower();s=self.brain.executive_snapshot(24)
        if any(x in q for x in ("why didn't you act","why did not you act","why didn't you restart","why did you not","why not act")):
            with self.brain.store.connect() as con:
                rows=[dict(r) for r in con.execute("""SELECT action,authority,risk,confidence,reason,outcome,created_at_utc
                    FROM decisions ORDER BY decision_id DESC LIMIT 10""").fetchall()]
            blocked=next((x for x in rows if x.get("authority") in {"blocked","approval_required","recommend_only"} or x.get("outcome") in {"blocked","not_executed"}),None)
            if blocked:
                return {"answer":f"The most recent constrained action was {blocked['action']}: {blocked['reason']}.","data":blocked}
            st=s.get("autonomy",{})
            return {"answer":f"No recent blocked action is recorded. Current autonomy is L{st.get('level')} {st.get('level_name')}; actions outside the registered boundary are not executed.","data":rows[:5]}
        if any(x in q for x in ("why","cause","root cause")):
            rows=s.get("root_causes",[])
            if not rows:return {"answer":"No active incident currently has a root-cause report.","data":[]}
            r=rows[0]
            return {"answer":f"{r['source']}: {r['probable_cause']} (confidence {r['confidence']:.0%}).","data":rows[:5]}
        if any(x in q for x in ("what changed","changed","release")):
            with self.brain.store.connect() as con:
                rows=[dict(r) for r in con.execute("SELECT * FROM release_events ORDER BY detected_at_utc DESC LIMIT 10").fetchall()]
            return {"answer":f"{len(rows)} recent source-change records.","data":rows}
        if any(x in q for x in ("automate","automation","manual work")):
            rows=s.get("automation_opportunities",[])
            return {"answer":f"{len(rows)} open automation opportunities.","data":rows[:10]}
        if any(x in q for x in ("goal","objective")):
            objectives=s.get("objectives",[])
            if objectives:
                at_risk=sum(1 for x in objectives if x["status"]!="healthy")
                return {"answer":f"{len(objectives)} objectives evaluated; {at_risk} currently at risk.","data":objectives}
            rows=s.get("goals",[]);missed=sum(1 for x in rows if x["status"]=="missed")
            return {"answer":f"{len(rows)} operational goals evaluated; {missed} missed.","data":rows}
        if any(x in q for x in ("worst","needs work","priority","next")):
            rows=s.get("insights",[])
            return {"answer":rows[0]["title"] if rows else "No priority issue identified.","data":rows[:8]}
        if any(x in q for x in ("status","health","how is")):
            return {"answer":f"Overall {s['scorecard']['overall']}/100; {len(s['incidents'])} open incidents; {len(s['automation_opportunities'])} automation opportunities.","data":s["scorecard"]}
        if any(x in q for x in ("incident","failure","wrong","broken")):
            return {"answer":f"{len(s['incidents'])} open incidents and {s['summary']['failures']} failure events in the last 24h.","data":s["incidents"]}
        if any(x in q for x in ("recommend","improve")):
            return {"answer":f"{len(s['recommendations'])} recommendations and {len(s['automation_opportunities'])} automation opportunities.","data":{"recommendations":s["recommendations"][:5],"automation":s["automation_opportunities"][:5]}}
        if any(x in q for x in ("learn","experiment")):
            return {"answer":f"{len(s['lessons'])} completed experiment lessons.","data":s["lessons"][:10]}
        return {"answer":"Ask about status, why/root cause, incidents, priorities, automation, goals, changes/releases, recommendations, or learning.","data":{}}
