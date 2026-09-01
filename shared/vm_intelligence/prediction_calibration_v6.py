from __future__ import annotations
from datetime import datetime,timezone
from .v6_schema import ensure_v6_schema

def _now():return datetime.now(timezone.utc).isoformat()
class PredictionCalibration:
    def __init__(self,store):self.store=store;ensure_v6_schema(store)
    def evaluate_due(self):
        now=_now();resolved=[]
        with self.store.connect() as con:
            rows=[dict(r) for r in con.execute("SELECT * FROM predictions WHERE due_at_utc IS NOT NULL AND due_at_utc<=? AND prediction_id NOT IN (SELECT prediction_id FROM prediction_outcomes)",(now,)).fetchall()]
            for r in rows:
                if r.get('outcome') is None and r.get('actual_value') is None:continue
                actual=1 if str(r.get('outcome','')).lower() in {'true_positive','occurred','failure','breach'} else 0
                p=float(r.get('probability') or 0);cls=('TRUE_POSITIVE' if actual and p>=.5 else 'FALSE_NEGATIVE' if actual else 'FALSE_POSITIVE' if p>=.5 else 'TRUE_NEGATIVE')
                brier=(p-actual)**2
                con.execute('INSERT OR REPLACE INTO prediction_outcomes(prediction_id,evaluated_at_utc,classification,calibrated_probability,actual_event,brier_score,metadata_json) VALUES(?,?,?,?,?,?,?)',
                            (r['prediction_id'],now,cls,p,actual,brier,'{}'))
                resolved.append({'prediction_id':r['prediction_id'],'classification':cls,'brier_score':round(brier,4)})
            hist=[dict(x) for x in con.execute('SELECT * FROM prediction_outcomes').fetchall()]
        briers=[float(x['brier_score']) for x in hist if x.get('brier_score') is not None]
        accuracy=round(100*sum(1 for x in hist if x['classification'] in {'TRUE_POSITIVE','TRUE_NEGATIVE'})/len(hist),1) if hist else None
        bins=[]
        for low in (0.0,.2,.4,.6,.8):
            high=low+.2
            group=[x for x in hist if x.get('calibrated_probability') is not None and low<=float(x['calibrated_probability'])<(high if high<1 else 1.00001)]
            if group:
                observed=round(sum(int(x.get('actual_event') or 0) for x in group)/len(group),3)
                bins.append({'range':[round(low,1),round(high,1)],'samples':len(group),'mean_predicted':round(sum(float(x['calibrated_probability']) for x in group)/len(group),3),'observed_rate':observed})
        n=len(hist)
        maturity='calibrated' if n>=50 else 'provisional' if n>=20 else 'learning' if n>=5 else 'insufficient_evidence'
        return {'resolved_now':resolved,'resolved_total':n,'accuracy_pct':accuracy,
                'mean_brier_score':round(sum(briers)/len(briers),4) if briers else None,
                'maturity':maturity,'calibration_bins':bins,'automatic_authority_from_prediction_accuracy':False}
