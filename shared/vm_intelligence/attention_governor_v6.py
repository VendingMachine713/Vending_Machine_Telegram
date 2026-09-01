from __future__ import annotations
from .v6_schema import ensure_v6_schema
class AttentionGovernor:
    def __init__(self,store):self.store=store;ensure_v6_schema(store)
    def snapshot(self,base_attention):
        with self.store.connect() as con:rows=[dict(r) for r in con.execute('SELECT * FROM attention_events ORDER BY attention_event_id DESC LIMIT 500').fetchall()]
        spent=round(sum(float(x['cost_units']) for x in rows if not x.get('avoided')),1);avoided=round(sum(float(x['cost_units']) for x in rows if x.get('avoided')),1)
        useful=[x for x in rows if x.get('useful') is not None];usefulness=round(100*sum(int(x['useful']) for x in useful)/len(useful),1) if useful else None
        estimated=float(base_attention.get('estimated_minutes_saved',0) or 0)
        outcomes=float(base_attention.get('automatic_decisions',0) or 0)
        north_star=round((outcomes+estimated/10.0)/max(1.0,spent),3)
        return {'attention_units_spent':spent,'attention_units_avoided':avoided,'usefulness_pct':usefulness,
                'estimated_minutes_saved':estimated,'useful_autonomy_per_attention_unit':north_star,
                'notification_policy':'exception-first; recovered/no-action events should aggregate unless severity requires interruption',
                'north_star':'useful autonomous outcomes per unit user attention'}
