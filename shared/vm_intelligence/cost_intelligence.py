from __future__ import annotations
from pathlib import Path
import json

class CostIntelligence:
    """Only calculates configured costs; never invents provider prices."""
    def __init__(self,root):self.root=Path(root)

    def analyze(self,integrated):
        cfg=self.root/"config"/"vm_intelligence_costs.json"
        if not cfg.is_file():
            return {"configured":False,"total_estimated_cost":None,
                    "note":"No cost rates configured; VM Intelligence will not invent API/service prices."}
        try:data=json.loads(cfg.read_text(encoding="utf-8-sig"))
        except Exception:return {"configured":False,"total_estimated_cost":None,"note":"Cost configuration could not be read."}
        total=0.0;lines=[]
        for item in data.get("rates",[]):
            source=item.get("source");metric=item.get("metric");rate=item.get("cost_per_unit")
            if not isinstance(rate,(int,float)):continue
            value=integrated.get(source,{}).get("metrics",{}).get(metric)
            if not isinstance(value,(int,float)):continue
            cost=float(value)*float(rate);total+=cost
            lines.append({"source":source,"metric":metric,"units":value,"rate":rate,"estimated_cost":round(cost,4)})
        return {"configured":True,"total_estimated_cost":round(total,4),"lines":lines,
                "note":"Estimates use only user-configured rates."}
