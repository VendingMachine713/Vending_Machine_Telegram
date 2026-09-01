from __future__ import annotations

class CausalIntelligence:
    def __init__(self,store):self.store=store

    def evidence(self):
        with self.store.connect() as con:
            experiments=[dict(r) for r in con.execute("""SELECT * FROM experiments
                WHERE result IN ('win','loss','neutral','invalid') ORDER BY updated_at_utc DESC LIMIT 50""").fetchall()]
            releases=[dict(r) for r in con.execute("""SELECT * FROM release_events
                ORDER BY detected_at_utc DESC LIMIT 50""").fetchall()]
        rows=[]
        for e in experiments:
            rows.append({"source":e["source"],"kind":"controlled_experiment","name":e["name"],
                         "result":e["result"],"confidence":"higher",
                         "interpretation":"This is stronger causal evidence than an observational trend because a candidate was explicitly evaluated against a baseline."})
        for r in releases:
            rows.append({"source":r["source"],"kind":"release_observation",
                         "name":f"{r.get('previous_version')} -> {r.get('version')}",
                         "result":r.get("status"),"confidence":"observational",
                         "interpretation":"Post-release score movement is correlation unless isolated by a controlled experiment."})
        return rows
