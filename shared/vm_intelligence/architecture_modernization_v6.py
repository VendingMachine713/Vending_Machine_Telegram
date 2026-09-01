from __future__ import annotations
from datetime import datetime,timezone
import hashlib,json
from .v6_schema import ensure_v6_schema

def _now():return datetime.now(timezone.utc).isoformat()
class ArchitectureModernizer:
    def __init__(self,store):self.store=store;ensure_v6_schema(store)
    def propose(self,normalization,platform_registry):
        proposals=[];by={}
        for v in normalization.get('violations',[]):by.setdefault(v['service'],set()).add(v['category'])
        with self.store.connect() as con:
            for service,cats in sorted(by.items()):
                if not ({'compatibility_bridge_active','compatibility_bridge','deep_nested_runtime','deep_topology'} & set(cats)):continue
                title=f'Modernize {service} native runtime topology and retire compatibility bridge after proof';key=hashlib.sha256(title.encode()).hexdigest()[:20]
                plan=['create isolated worktree','upgrade native runtime registry resolution','run exact impacted tests','simulate bridge disabled','run full canonical regression','prepare reversible migration']
                row={'candidate_key':key,'service':service,'title':title,'impact':8,'risk':4,'confidence':.85,'isolated_only':True,'production_mutation':False,'plan':plan};proposals.append(row)
                con.execute('INSERT OR REPLACE INTO architecture_modernization_candidates(candidate_key,title,created_at_utc,status,impact,risk,confidence,isolated_only,production_mutation,plan_json,evidence_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                    (key,title,_now(),'proposal',8,4,.85,1,0,json.dumps(plan),json.dumps({'categories':sorted(cats)})))
        return {'candidates':proposals,'automatic_migration':False}
