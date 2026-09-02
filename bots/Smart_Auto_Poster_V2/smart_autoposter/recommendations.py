from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

from .db import Database, utcnow


def _rid(category: str, target_type: str | None, target_id: str | None) -> str:
    raw=f'{category}|{target_type or ""}|{target_id or ""}'
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def _upsert(db: Database, *, category: str, severity: str, target_type: str | None, target_id: str | None,
            title: str, message: str, evidence: dict, suggested_action: dict) -> dict:
    rid=_rid(category,target_type,target_id); now=utcnow()
    with db.connect() as con:
        con.execute('''INSERT INTO recommendations(recommendation_id,created_at,updated_at,category,severity,target_type,target_id,title,message,
                       evidence_json,suggested_action_json,status) VALUES(?,?,?,?,?,?,?,?,?,?,?,'open')
                       ON CONFLICT(recommendation_id) DO UPDATE SET updated_at=excluded.updated_at,severity=excluded.severity,title=excluded.title,
                       message=excluded.message,evidence_json=excluded.evidence_json,suggested_action_json=excluded.suggested_action_json,
                       status=CASE WHEN recommendations.status='applied' THEN recommendations.status ELSE 'open' END,
                       dismissed_at=CASE WHEN recommendations.status='applied' THEN recommendations.dismissed_at ELSE NULL END''',
                    (rid,now,now,category,severity,target_type,target_id,title,message,json.dumps(evidence,sort_keys=True),json.dumps(suggested_action,sort_keys=True)))
        row=con.execute('SELECT * FROM recommendations WHERE recommendation_id=?',(rid,)).fetchone()
    return dict(row)


def generate_recommendations(db: Database, hours: int = 168) -> list[dict]:
    hours=max(1,int(hours)); cutoff=(datetime.now(timezone.utc)-timedelta(hours=hours)).isoformat(timespec='seconds')
    generated=[]
    with db.connect() as con:
        # Reliability: enough samples and >=20% permanent failure rate.
        rows=con.execute('''SELECT d.group_id,d.group_name,d.min_interval_seconds,
            SUM(CASE WHEN q.status='sent' THEN 1 ELSE 0 END) sent,
            SUM(CASE WHEN q.status IN ('failed','quarantined') THEN 1 ELSE 0 END) failed,
            COUNT(q.id) total
            FROM destinations d JOIN queue q ON q.group_id=d.group_id
            WHERE q.updated_at>=? GROUP BY d.group_id,d.group_name,d.min_interval_seconds HAVING COUNT(q.id)>=5''',(cutoff,)).fetchall()
        for r in rows:
            sent=int(r['sent'] or 0); failed=int(r['failed'] or 0); denom=sent+failed
            rate=(failed/denom) if denom else 0
            if failed>=2 and rate>=0.20:
                generated.append(_upsert(db,category='destination_reliability',severity='WARNING',target_type='destination',target_id=str(r['group_id']),
                    title=f"Review unreliable destination: {r['group_name']}",
                    message=f"{failed} permanent/terminal failures vs {sent} successful sends in the last {hours}h ({rate*100:.1f}% failure rate).",
                    evidence={'sent':sent,'failed':failed,'failure_rate':round(rate,4),'window_hours':hours},
                    suggested_action={'type':'protect_destination','group_id':int(r['group_id'])}))

        # Repeated slow mode => recommend a conservative interval increase (decision support, not automatic unless applied).
        slow=con.execute('''SELECT group_id,COUNT(*) n FROM events WHERE created_at>=? AND event_type IN ('slow_mode','send_failure')
                            AND lower(message) LIKE '%slow%' AND group_id IS NOT NULL GROUP BY group_id HAVING COUNT(*)>=3''',(cutoff,)).fetchall()
        for r in slow:
            d=con.execute('SELECT group_name,min_interval_seconds FROM destinations WHERE group_id=?',(r['group_id'],)).fetchone()
            if not d: continue
            current=int(d['min_interval_seconds'] or 0); suggested=max(3600,current*2 if current else 3600)
            generated.append(_upsert(db,category='slow_mode_frequency',severity='WARNING',target_type='destination',target_id=str(r['group_id']),
                title=f"Increase spacing for {d['group_name']}",message=f"Slow-mode related failures occurred {r['n']} times in {hours}h.",
                evidence={'events':int(r['n']),'current_min_interval_seconds':current,'window_hours':hours},
                suggested_action={'type':'set_min_interval_seconds','group_id':int(r['group_id']),'seconds':suggested}))

        # Uncertain sends require human review.
        uncertain=con.execute("SELECT COUNT(*) FROM queue WHERE status='uncertain'").fetchone()[0]
        if uncertain:
            generated.append(_upsert(db,category='uncertain_queue',severity='IMPORTANT',target_type='queue',target_id='uncertain',
                title='Uncertain sends need review',message=f'{uncertain} send(s) are marked UNCERTAIN and will not be automatically resent.',
                evidence={'count':int(uncertain)},suggested_action={'type':'review_uncertain_jobs'}))

        review=con.execute('SELECT COUNT(*) FROM destinations WHERE needs_review=1').fetchone()[0]
        if review:
            generated.append(_upsert(db,category='destination_review',severity='INFO',target_type='destinations',target_id='review',
                title='New destinations waiting for review',message=f'{review} destination(s) are REVIEW + disabled.',
                evidence={'count':int(review)},suggested_action={'type':'review_destinations'}))

        # Account load imbalance only if both have been used and sample is significant.
        acct={r['account_key']:int(r['n']) for r in con.execute("SELECT account_key,COUNT(*) n FROM queue WHERE status='sent' AND updated_at>=? AND account_key IN ('primary','secondary') GROUP BY account_key",(cutoff,)).fetchall()}
        p=acct.get('primary',0); s=acct.get('secondary',0); total=p+s
        if total>=20 and p and s:
            share=max(p,s)/total
            if share>=0.85:
                heavy='primary' if p>s else 'secondary'; light='secondary' if heavy=='primary' else 'primary'
                generated.append(_upsert(db,category='account_load_balance',severity='INFO',target_type='accounts',target_id='balance',
                    title='Account load is highly imbalanced',message=f'{heavy} handled {share*100:.1f}% of sends in {hours}h while both accounts were used.',
                    evidence={'primary_sent':p,'secondary_sent':s,'window_hours':hours},
                    suggested_action={'type':'review_account_affinity','heavy':heavy,'light':light}))

        # Variant distribution imbalance in multi-variant campaigns.
        camps=con.execute('''SELECT campaign_id FROM campaign_content WHERE enabled=1 GROUP BY campaign_id HAVING COUNT(*)>=2''').fetchall()
        for c in camps:
            cid=c['campaign_id']; counts=[dict(x) for x in con.execute('''SELECT content_id,COUNT(*) n FROM queue WHERE campaign_id=? AND status='sent' AND updated_at>=? GROUP BY content_id''',(cid,cutoff)).fetchall()]
            total=sum(int(x['n']) for x in counts)
            if total>=20 and counts:
                top=max(counts,key=lambda x:int(x['n']))
                share=int(top['n'])/total
                if share>=0.75:
                    generated.append(_upsert(db,category='variant_distribution',severity='INFO',target_type='campaign',target_id=cid,
                        title=f'Variant distribution is concentrated: {cid}',message=f"Variant {top['content_id']} handled {share*100:.1f}% of {total} sends.",
                        evidence={'total':total,'variants':counts},suggested_action={'type':'review_rotation_weights','campaign_id':cid}))
    return generated


def list_recommendations(db: Database, status: str = 'open', limit: int = 100) -> list[dict]:
    with db.connect() as con:
        rows=con.execute('SELECT * FROM recommendations WHERE status=? ORDER BY CASE severity WHEN \'CRITICAL\' THEN 4 WHEN \'IMPORTANT\' THEN 3 WHEN \'WARNING\' THEN 2 ELSE 1 END DESC,updated_at DESC LIMIT ?', (status,int(limit))).fetchall()
    out=[]
    for r in rows:
        d=dict(r); d['evidence']=json.loads(d.pop('evidence_json') or '{}'); d['suggested_action']=json.loads(d.pop('suggested_action_json') or '{}'); out.append(d)
    return out


def dismiss_recommendation(db: Database, recommendation_id: str) -> None:
    with db.connect() as con:
        cur=con.execute("UPDATE recommendations SET status='dismissed',dismissed_at=?,updated_at=? WHERE recommendation_id=? AND status='open'",(utcnow(),utcnow(),recommendation_id))
        if cur.rowcount!=1: raise RuntimeError('Open recommendation not found')


def apply_recommendation(db: Database, recommendation_id: str, *, actor: str = 'local') -> dict:
    with db.connect() as con:
        r=con.execute("SELECT * FROM recommendations WHERE recommendation_id=? AND status='open'",(recommendation_id,)).fetchone()
        if not r: raise RuntimeError('Open recommendation not found')
        action=json.loads(r['suggested_action_json'] or '{}'); typ=action.get('type')
        if typ=='set_min_interval_seconds':
            gid=int(action['group_id']); seconds=max(0,int(action['seconds']))
            con.execute('UPDATE destinations SET min_interval_seconds=?,updated_at=? WHERE group_id=?',(seconds,utcnow(),gid))
        elif typ=='protect_destination':
            gid=int(action['group_id']); con.execute('UPDATE destinations SET protected=1,updated_at=? WHERE group_id=?',(utcnow(),gid))
        else:
            raise RuntimeError(f'Recommendation action requires manual review: {typ}')
        con.execute("UPDATE recommendations SET status='applied',applied_at=?,updated_at=? WHERE recommendation_id=?",(utcnow(),utcnow(),recommendation_id))
    db.audit(actor,'recommendation_apply',target_type=r['target_type'],target_id=r['target_id'],details=json.dumps(action,sort_keys=True))
    return {'recommendation_id':recommendation_id,'action':action,'status':'applied'}
