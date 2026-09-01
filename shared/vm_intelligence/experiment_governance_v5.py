from __future__ import annotations
from datetime import datetime, timezone
import json
from .v5_schema import ensure_v5_schema

CERTIFIED_EXPERIMENT_DOMAINS={
    "cache_ttl":{"risk":"low","bounds":[60,3600]},
    "polling_interval":{"risk":"low","bounds":[30,900]},
    "log_retention_days":{"risk":"low","bounds":[30,90]},
    "maintenance_window":{"risk":"low","bounds":None},
}
FORBIDDEN_DOMAINS={"credentials","telegram_identity","permissions","uncertain_delivery_policy","irreversible_migration"}

class ExperimentGovernance:
    def __init__(self,store):self.store=store;ensure_v5_schema(store)

    def evaluate(self,domain,reliability,requested_level):
        if domain in FORBIDDEN_DOMAINS:
            return {"allowed":False,"domain":domain,"reason":"forbidden domain","required_level":99}
        spec=CERTIFIED_EXPERIMENT_DOMAINS.get(domain)
        if not spec:
            return {"allowed":False,"domain":domain,"reason":"domain not certified","required_level":5}
        if requested_level<5:
            return {"allowed":False,"domain":domain,"reason":"L5 Experiment required","required_level":5}
        if reliability.get("experiment_freeze_recommended"):
            return {"allowed":False,"domain":domain,"reason":"reliability freeze active","required_level":5}
        return {"allowed":True,"domain":domain,"reason":"certified experiment domain","required_level":5,
                "risk":spec["risk"],"bounds":spec["bounds"],"automatic_production_promotion":False}

    def collision_check(self,active_domains,new_domain):
        conflict_groups=[
            {"worker_concurrency","account_balancing","delivery_retry"},
            {"search_index_interval","search_cache_ttl"},
        ]
        conflicts=[]
        for group in conflict_groups:
            if new_domain in group:
                conflicts.extend(sorted(group.intersection(set(active_domains))))
        return {"allowed":not conflicts,"conflicts":conflicts}
