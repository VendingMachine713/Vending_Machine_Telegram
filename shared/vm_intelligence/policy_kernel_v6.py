from __future__ import annotations
from datetime import datetime,timezone
import json
from .v6_schema import ensure_v6_schema

def _now():return datetime.now(timezone.utc).isoformat()
FORBIDDEN={'blind_uncertain_retry','direct_production_source_rewrite','credential_change','permission_change','irreversible_migration','irreversible_migration_without_recovery','bypass_security_gate','bypass_regression_gate','automatic_unverified_release_promotion'}
RISK_LEVEL={'low':1,'medium':2,'high':3,'critical':4}
class PolicyKernel:
    def __init__(self,store):self.store=store;ensure_v6_schema(store)
    def evaluate(self,*,action_key,capability,requested_level,effective_level,capability_record=None,risk='low',
                 evidence_quality=0,rollback_ready=False,backup_ready=False,security_score=100,reliability_freeze=False,mode='production',record=True):
        reasons=[]
        if action_key in FORBIDDEN or capability in FORBIDDEN:decision='DENY';reasons=['permanent_forbidden_capability']
        elif security_score is not None and security_score<70:decision='DEFER';reasons=['security_score_below_70']
        elif evidence_quality<60:decision='DEFER';reasons=['insufficient_evidence_quality']
        elif RISK_LEVEL.get(risk,3)>=3 and not rollback_ready:decision='REQUIRE_APPROVAL';reasons=['high_risk_without_verified_rollback']
        elif mode=='shadow':decision='ALLOW_SHADOW';reasons=['shadow_has_no_production_authority']
        elif mode=='experiment':
            if reliability_freeze:decision='DEFER';reasons=['reliability_freeze']
            elif effective_level<5:decision='DENY';reasons=['L5_required']
            elif not capability_record or capability_record.get('certification')!='certified':decision='ALLOW_SHADOW';reasons=['capability_not_certified']
            else:decision='ALLOW_EXPERIMENT';reasons=['certified_experiment_capability']
        else:
            required=int((capability_record or {}).get('minimum_level',4));certified=(capability_record or {}).get('certification')=='certified'
            if effective_level<required:decision='DENY';reasons=[f'L{required}_required']
            elif required>=5 and not certified:decision='REQUIRE_APPROVAL';reasons=['higher_authority_not_certified']
            elif risk in {'medium','high','critical'} and not backup_ready and action_key not in {'managed_restart','log_rotation'}:
                decision='REQUIRE_APPROVAL';reasons=['backup_not_ready']
            else:decision='ALLOW';reasons=['policy_gates_satisfied']
        row={'action_key':action_key,'capability':capability,'requested_level':requested_level,'effective_level':effective_level,
             'decision':decision,'risk':risk,'evidence_quality':evidence_quality,'rollback_ready':bool(rollback_ready),
             'backup_ready':bool(backup_ready),'security_score':security_score,'reliability_freeze':bool(reliability_freeze),'reasons':reasons,'global_authority_granted':False}
        if record:
            with self.store.connect() as con:
                con.execute('''INSERT INTO policy_decisions(created_at_utc,action_key,capability,requested_level,effective_level,decision,risk,
                  evidence_quality,rollback_ready,backup_ready,security_score,reliability_freeze,reasons_json,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                  (_now(),action_key,capability,requested_level,effective_level,decision,risk,evidence_quality,1 if rollback_ready else 0,
                   1 if backup_ready else 0,security_score,1 if reliability_freeze else 0,json.dumps(reasons),'{}'))
        row['recorded']=bool(record)
        return row
