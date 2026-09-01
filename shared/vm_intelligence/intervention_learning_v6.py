from __future__ import annotations
from datetime import datetime,timezone,timedelta
from .v6_schema import ensure_v6_schema

def _now(): return datetime.now(timezone.utc)
def _parse(v):
    try:return datetime.fromisoformat(str(v).replace('Z','+00:00'))
    except Exception:return None

class InterventionLearning:
    def __init__(self,store):self.store=store;ensure_v6_schema(store)
    def evaluate_pending(self):
        now=_now();updated=[]
        with self.store.connect() as con:
            rows=[dict(r) for r in con.execute("SELECT * FROM intervention_outcomes WHERE completed_at_utc IS NOT NULL ORDER BY intervention_id").fetchall()]
            for r in rows:
                completed=_parse(r.get('completed_at_utc'))
                if not completed:continue
                source=r.get('source')
                recur24=r.get('recurrence_24h');recur7=r.get('recurrence_7d');root=r.get('root_cause_success')
                if recur24 is None and now>=completed+timedelta(hours=24):
                    end=(completed+timedelta(hours=24)).isoformat()
                    hit=con.execute("SELECT 1 FROM incidents WHERE source=? AND first_seen_utc>? AND first_seen_utc<=? LIMIT 1",(source,completed.isoformat(),end)).fetchone()
                    recur24=1 if hit else 0
                if recur7 is None and now>=completed+timedelta(days=7):
                    end=(completed+timedelta(days=7)).isoformat()
                    hit=con.execute("SELECT 1 FROM incidents WHERE source=? AND first_seen_utc>? AND first_seen_utc<=? LIMIT 1",(source,completed.isoformat(),end)).fetchone()
                    recur7=1 if hit else 0
                    if root is None:
                        root=1 if bool(r.get('immediate_success')) and not recur7 else 0
                if recur24!=r.get('recurrence_24h') or recur7!=r.get('recurrence_7d') or root!=r.get('root_cause_success'):
                    con.execute("UPDATE intervention_outcomes SET recurrence_24h=?,recurrence_7d=?,root_cause_success=? WHERE intervention_id=?",(recur24,recur7,root,r['intervention_id']))
                    updated.append(r['intervention_id'])
        return updated
    def summarize(self):
        self.evaluate_pending()
        with self.store.connect() as con:rows=[dict(r) for r in con.execute('SELECT * FROM intervention_outcomes ORDER BY intervention_id DESC LIMIT 500').fetchall()]
        by={}
        for r in rows:by.setdefault(r['action_key'],[]).append(r)
        out=[]
        for action,items in by.items():
            immediate=[x for x in items if x.get('immediate_success') is not None];root=[x for x in items if x.get('root_cause_success') is not None];recur=[x for x in items if x.get('recurrence_7d') is not None]
            out.append({'action_key':action,'attempts':len(items),
                'immediate_success_pct':round(100*sum(int(x['immediate_success']) for x in immediate)/len(immediate),1) if immediate else None,
                'root_cause_success_pct':round(100*sum(int(x['root_cause_success']) for x in root)/len(root),1) if root else None,
                'recurrence_7d_pct':round(100*sum(int(x['recurrence_7d']) for x in recur)/len(recur),1) if recur else None,
                'attention_saved_minutes':round(sum(float(x.get('attention_saved_minutes') or 0) for x in items),1),
                'maturity':'long_term' if len(root)>=5 else 'learning' if items else 'empty'})
        return {'actions':sorted(out,key=lambda x:(-x['attempts'],x['action_key'])),'principle':'Recovery success and root-cause success are measured separately.'}
