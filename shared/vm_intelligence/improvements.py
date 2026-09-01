from __future__ import annotations
import hashlib

class ImprovementLedger:
    def __init__(self,store): self.store=store

    def sync_experiments(self):
        with self.store.connect() as con:
            rows=con.execute("SELECT * FROM experiments WHERE result IN ('win','loss','neutral')").fetchall()
        for r in rows:
            fp=hashlib.sha256(f"experiment:{r['experiment_id']}".encode()).hexdigest()[:24]
            self.store.add_improvement(source=r["source"],title=r["name"],metric=r["metric"],
                before_value=r["baseline"],after_value=r["candidate"],status=r["result"],
                evidence={"experiment_id":r["experiment_id"],"hypothesis":r["hypothesis"]},fingerprint=fp)
        return self.store.improvements()
