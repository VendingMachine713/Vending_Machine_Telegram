from __future__ import annotations
from datetime import datetime,timezone
import json
from .v6_schema import ensure_v6_schema
HORIZONS={'NOW':1,'24H':24,'7D':168,'30D':720,'QUARTER':2160}
class StrategicOperator:
    def __init__(self,store):self.store=store;ensure_v6_schema(store)
    def build(self,planner,policy_context,policy_previews=None):
        backlog=planner.get('backlog',[]);plans={};preview_by={}
        for x in policy_previews or []:preview_by.setdefault(x.get('action_key'),x)
        enriched=[]
        for item in backlog:
            policy=preview_by.get(item.get('action_key'))
            row={**item,'policy_decision':(policy or {}).get('decision','NOT_EVALUATED'),
                 'policy_reasons':(policy or {}).get('reasons',[]),
                 'execution_allowed':bool((policy or {}).get('decision')=='ALLOW')}
            enriched.append(row)
        for name,hours in HORIZONS.items():
            if name=='NOW':rows=[x for x in enriched if x.get('priority')=='P0'][:3]
            elif name=='24H':rows=[x for x in enriched if x.get('priority') in {'P0','P1'}][:6]
            elif name=='7D':rows=enriched[:10]
            else:rows=enriched[:20]
            plans[name]=rows
        now=datetime.now(timezone.utc).isoformat()
        with self.store.connect() as con:
            for name,hours in HORIZONS.items():con.execute('INSERT OR REPLACE INTO strategic_horizons(horizon_key,generated_at_utc,hours,plan_json) VALUES(?,?,?,?)',(name,now,hours,json.dumps(plans[name],sort_keys=True,default=str)))
        executable=sum(1 for x in enriched if x['execution_allowed']);blocked=sum(1 for x in enriched if x['policy_decision'] in {'DENY','DEFER','REQUIRE_APPROVAL','ALLOW_SHADOW'})
        return {'horizons':plans,'objective_portfolio':{'reliability':40,'user_attention':25,'security':20,'efficiency':10,'performance':5},
                'execution_authority':'policy_kernel_and_capability_specific','planner_level':7,
                'executable_items':executable,'blocked_or_deferred_items':blocked,
                'evidence_quality':policy_context.get('evidence_quality'),'security_score':policy_context.get('security_score'),
                'reliability_freeze':bool(policy_context.get('reliability_freeze'))}
