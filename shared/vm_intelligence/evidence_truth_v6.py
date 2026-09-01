from __future__ import annotations
from datetime import datetime,timezone
from .v6_schema import ensure_v6_schema

def _now():return datetime.now(timezone.utc)
def _parse(v):
    try:return datetime.fromisoformat(str(v).replace('Z','+00:00'))
    except Exception:return None
QUALITY_WEIGHT={'direct':1.0,'verified':.95,'derived':.8,'predicted':.65,'inferred':.55,'unknown':.35}
class EvidenceTruthLayer:
    def __init__(self,store):self.store=store;ensure_v6_schema(store)
    @staticmethod
    def classify_freshness(seconds):
        if seconds is None:return 'INVALID'
        if seconds<=30:return 'LIVE'
        if seconds<=300:return 'FRESH'
        if seconds<=3600:return 'AGING'
        return 'STALE'
    def assess(self,integrated,generated_at_utc=None):
        now=_parse(generated_at_utc) or _now();rows=[]
        for source,data in sorted(integrated.items()):
            evidence=data.get('evidence') or []
            for metric,value in sorted((data.get('metrics') or {}).items()):
                observed=data.get('observed_at_utc') or now.isoformat()
                t=_parse(observed);age=max(0,(now-t).total_seconds()) if t else None
                quality='direct' if evidence else 'verified';fresh=self.classify_freshness(age)
                conf=QUALITY_WEIGHT[quality]*(1.0 if fresh in {'LIVE','FRESH'} else .8 if fresh=='AGING' else .45)
                rows.append({'source':source,'claim_key':f'{source}.{metric}','observed_at_utc':observed,
                    'freshness_seconds':age,'freshness':fresh,'quality':quality,'confidence':round(conf,3),
                    'provenance':'adapter_evidence' if evidence else 'current_cycle_metric','value':value})
        if rows:
            import json
            with self.store.connect() as con:
                for row in rows:
                    con.execute('''INSERT INTO evidence_records(source,claim_key,observed_at_utc,freshness_seconds,quality,
                      confidence,provenance,value_json,metadata_json) VALUES(?,?,?,?,?,?,?,?,?)''',
                      (row['source'],row['claim_key'],row['observed_at_utc'],row['freshness_seconds'],row['quality'],
                       row['confidence'],row['provenance'],json.dumps(row.get('value'),default=str),
                       json.dumps({'freshness':row['freshness']},sort_keys=True)))
        score=round(100*sum(x['confidence'] for x in rows)/len(rows),1) if rows else 0.0
        stale=sum(1 for x in rows if x['freshness'] in {'STALE','INVALID'})
        direct=sum(1 for x in rows if x['quality']=='direct')
        live=sum(1 for x in rows if x['freshness'] in {'LIVE','FRESH'})
        coverage=round(100*live/len(rows),1) if rows else 0.0
        direct_pct=round(100*direct/len(rows),1) if rows else 0.0
        grade='A' if score>=90 and coverage>=90 else 'B' if score>=80 and coverage>=75 else 'C' if score>=70 else 'D' if score>=60 else 'F'
        authority_cap='normal' if score>=80 and coverage>=75 else 'recommend_only' if score>=60 else 'observe_only'
        return {'score':score,'grade':grade,'coverage_pct':coverage,'direct_evidence_pct':direct_pct,'records':rows,
                'stale_or_invalid':stale,'authority_cap':authority_cap,
                'authority_note':'Low-quality/stale evidence can reduce authority but never increase it.'}
