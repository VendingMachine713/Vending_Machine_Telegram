from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from .db import Database, utcnow
from .queue_hygiene import queue_hygiene_plan
from .v5_controller import production_gate as v5_production_gate

ACTIVE = {"pending", "retry", "deferred", "processing", "sending", "uncertain"}


def _dt(value):
    if not value:
        return None
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def refresh_delivery_confidence(db: Database, *, campaign_id: str | None = None) -> list[dict]:
    """Materialise explainable delivery confidence without changing queue outcomes."""
    where = ""; params = []
    if campaign_id:
        where = "WHERE q.campaign_id=?"; params.append(campaign_id)
    out=[]; now=utcnow()
    with db.connect() as con:
        rows=con.execute(f"""SELECT q.id,q.status,q.error_kind,q.telegram_message_ids,q.account_key,
                           (SELECT COUNT(*) FROM delivery_attempts da WHERE da.queue_id=q.id) attempt_rows,
                           (SELECT COUNT(*) FROM delivery_attempts da WHERE da.queue_id=q.id AND da.telegram_message_ids IS NOT NULL) attempt_with_ids
                           FROM queue q {where}""",params).fetchall()
        for r in rows:
            status=str(r['status'] or '')
            ids=[]
            try: ids=json.loads(r['telegram_message_ids'] or '[]')
            except Exception: ids=[]
            if status=='sent' and ids:
                confidence,verdict,kind=100,'confirmed_sent','telegram_message_ids'
            elif status=='sent':
                confidence,verdict,kind=95,'confirmed_sent','queue_sent'
            elif status=='uncertain':
                confidence,verdict,kind=50,'uncertain',str(r['error_kind'] or 'ambiguous_delivery')
            elif status in {'pending','retry','deferred','processing'}:
                confidence,verdict,kind=0,'not_delivered_yet','pre_send_state'
            elif status in {'failed','cancelled','expired','quarantined'}:
                confidence,verdict,kind=5,'not_confirmed_sent','terminal_without_send_confirmation'
            elif status=='sending':
                confidence,verdict,kind=40,'in_flight','telegram_request_started'
            else:
                confidence,verdict,kind=0,'unknown','unknown'
            evidence={'queue_status':status,'telegram_message_ids':ids,'attempt_rows':int(r['attempt_rows'] or 0),'account_key':r['account_key']}
            con.execute("""INSERT INTO delivery_confidence(queue_id,confidence,verdict,evidence_kind,evidence_json,updated_at)
                         VALUES(?,?,?,?,?,?) ON CONFLICT(queue_id) DO UPDATE SET confidence=excluded.confidence,
                         verdict=excluded.verdict,evidence_kind=excluded.evidence_kind,evidence_json=excluded.evidence_json,updated_at=excluded.updated_at""",
                        (r['id'],confidence,verdict,kind,json.dumps(evidence,sort_keys=True),now))
            out.append({'queue_id':r['id'],'confidence':confidence,'verdict':verdict,'evidence_kind':kind})
    return out


def refresh_destination_intelligence(db: Database) -> list[dict]:
    """Build conservative per-destination reliability, timing and format intelligence."""
    now=utcnow(); out=[]
    with db.connect() as con:
        dests=con.execute("SELECT * FROM destinations WHERE enabled=1").fetchall()
        for d in dests:
            counts={r['status']:int(r['n']) for r in con.execute("SELECT status,COUNT(*) n FROM queue WHERE group_id=? GROUP BY status",(d['group_id'],)).fetchall()}
            sent=counts.get('sent',0); uncertain=counts.get('uncertain',0); failed=counts.get('failed',0)+counts.get('quarantined',0)
            deferred=counts.get('deferred',0)+counts.get('retry',0)
            total=max(1,sent+uncertain+failed)
            delivery_risk=min(100,round((uncertain*35+failed*25)/total))
            reliability=max(0,min(100,100-delivery_risk))
            timing=con.execute("SELECT * FROM destination_timing_profiles WHERE group_id=?",(d['group_id'],)).fetchone()
            timing_events=int((timing['slow_mode_events'] if timing else 0) or 0)+int((timing['flood_wait_events'] if timing else 0) or 0)
            timing_risk=min(100,timing_events*12 + min(40,int((timing['max_wait_seconds'] if timing else 0) or 0)//900*10))
            caps=con.execute("SELECT account_key,text_allowed,photo_allowed FROM destination_account_capabilities WHERE group_id=?",(d['group_id'],)).fetchall()
            known=sum(1 for c in caps if c['text_allowed'] is not None or c['photo_allowed'] is not None)
            format_conf=min(100,50*known)
            mode=str(d['mode'] or 'review')
            candidates=[]
            for key in ('primary','secondary'):
                access=bool(d[f'{key}_access'])
                if not access: continue
                a=con.execute("SELECT authorized,enabled,health_score,cooldown_until FROM accounts WHERE account_key=?",(key,)).fetchone()
                if not a or not int(a['authorized'] or 0) or not int(a['enabled'] or 0): continue
                cap=next((c for c in caps if c['account_key']==key),None)
                allowed=True
                if cap and mode=='photo' and cap['photo_allowed']==0: allowed=False
                if cap and mode=='text' and cap['text_allowed']==0: allowed=False
                if allowed: candidates.append((int(a['health_score'] or 0),key))
            preferred=max(candidates)[1] if candidates else None
            predicted=(timing['next_safe_at'] if timing else None) or d['next_eligible_at']
            con.execute("""INSERT INTO destination_intelligence(group_id,reliability_score,delivery_risk_score,timing_risk_score,format_confidence,
                         preferred_account,preferred_mode,predicted_next_safe_at,sent_count,uncertain_count,failed_count,deferred_count,evaluated_at)
                         VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(group_id) DO UPDATE SET
                         reliability_score=excluded.reliability_score,delivery_risk_score=excluded.delivery_risk_score,
                         timing_risk_score=excluded.timing_risk_score,format_confidence=excluded.format_confidence,
                         preferred_account=excluded.preferred_account,preferred_mode=excluded.preferred_mode,
                         predicted_next_safe_at=excluded.predicted_next_safe_at,sent_count=excluded.sent_count,
                         uncertain_count=excluded.uncertain_count,failed_count=excluded.failed_count,deferred_count=excluded.deferred_count,evaluated_at=excluded.evaluated_at""",
                        (d['group_id'],reliability,delivery_risk,timing_risk,format_conf,preferred,mode,predicted,sent,uncertain,failed,deferred,now))
            out.append({'group_id':d['group_id'],'group_name':d['group_name'],'reliability':reliability,'delivery_risk':delivery_risk,
                        'timing_risk':timing_risk,'format_confidence':format_conf,'preferred_account':preferred,'mode':mode,'predicted_next_safe_at':predicted})
    return out


def predictive_plan(db: Database, *, campaign_id: str='main_production_01') -> dict:
    intel=refresh_destination_intelligence(db)
    now=datetime.now(timezone.utc); ready=[]; wait=[]; review=[]
    with db.connect() as con:
        target={r['group_id'] for r in con.execute("""SELECT DISTINCT d.group_id FROM destinations d
                 LEFT JOIN destination_tags t ON t.group_id=d.group_id
                 JOIN campaigns c ON c.campaign_id=?
                 WHERE d.enabled=1 AND d.needs_review=0""",(campaign_id,)).fetchall()}
        active={r['group_id'] for r in con.execute("SELECT DISTINCT group_id FROM queue WHERE status IN ('pending','retry','deferred','processing','sending','uncertain')").fetchall()}
    for x in intel:
        if x['group_id'] not in target: continue
        if x['group_id'] in active:
            review.append({**x,'reason':'existing_unresolved_obligation'}); continue
        safe=_dt(x['predicted_next_safe_at'])
        if safe and safe>now:
            wait.append({**x,'reason':'predicted_timing_window','seconds_until_safe':int((safe-now).total_seconds())})
        elif not x['preferred_account']:
            review.append({**x,'reason':'no_healthy_compatible_account'})
        else:
            ready.append(x)
    return {'campaign_id':campaign_id,'ready_now':ready,'timing_wait':wait,'review':review,'counts':{'ready_now':len(ready),'timing_wait':len(wait),'review':len(review)}}


def recovery_snapshot(db: Database) -> dict:
    now=datetime.now(timezone.utc); actions=[]
    with db.connect() as con:
        rows=con.execute("SELECT component,last_seen_at,status,details FROM heartbeats").fetchall()
        in_flight=int(con.execute("SELECT COUNT(*) FROM queue WHERE status IN ('processing','sending')").fetchone()[0])
    thresholds={'service':60,'scheduler':90,'worker':90,'admin_bot':180,'telegram_auth':900,'network':900}
    for r in rows:
        limit=thresholds.get(r['component'])
        if not limit: continue
        ts=_dt(r['last_seen_at']); age=int((now-ts).total_seconds()) if ts else 10**9
        if age>limit:
            kind='restart_managed_runtime' if r['component'] in {'service','scheduler','worker'} else ('reconnect_telegram' if r['component']=='telegram_auth' else 'refresh_component')
            actions.append({'component':r['component'],'age_seconds':age,'recommended_action':kind,'automatic_safe': kind in {'restart_managed_runtime','refresh_component'} and in_flight==0})
    return {'generated_at':utcnow(),'in_flight':in_flight,'recommended_actions':actions,'requires_attention':any(not a['automatic_safe'] for a in actions)}


def production_health(db: Database, *, campaign_id='main_production_01') -> dict:
    intel=refresh_destination_intelligence(db); conf=refresh_delivery_confidence(db,campaign_id=campaign_id); gate=v5_production_gate(db,campaign_id=campaign_id)
    relevant=[x for x in intel]
    avg_rel=round(sum(x['reliability'] for x in relevant)/max(1,len(relevant)))
    avg_timing=round(sum(x['timing_risk'] for x in relevant)/max(1,len(relevant)))
    score=100
    score-=min(35,gate['uncertain']*5)
    score-=min(20,gate['queue_hygiene']['review_count']*5)
    score-=min(15,avg_timing//5)
    score-=max(0,(85-avg_rel)//2)
    score=max(0,min(100,score))
    return {'campaign_id':campaign_id,'health_score':score,'average_reliability':avg_rel,'average_timing_risk':avg_timing,
            'gate_ready':gate['ready'],'uncertain':gate['uncertain'],'overlap_review':gate['queue_hygiene']['review_count'],
            'delivery_confidence_rows':len(conf),'destination_intelligence_rows':len(intel)}


def v6_readiness(db: Database, *, campaign_id='main_production_01') -> dict:
    base=v5_production_gate(db,campaign_id=campaign_id); health=production_health(db,campaign_id=campaign_id); plan=predictive_plan(db,campaign_id=campaign_id); recovery=recovery_snapshot(db)
    blockers=list(base['blockers']); warnings=list(base['warnings'])
    with db.connect() as con:
        accounts=[dict(r) for r in con.execute("SELECT account_key,authorized,enabled,health_score,cooldown_until FROM accounts ORDER BY account_key").fetchall()]
        objective=con.execute("SELECT * FROM production_objectives WHERE campaign_id=?",(campaign_id,)).fetchone()
        guard=con.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='uq_queue_one_unresolved_per_group'").fetchone() is not None
        campaign_exists=con.execute("SELECT 1 FROM campaigns WHERE campaign_id=?",(campaign_id,)).fetchone() is not None
        if not objective and campaign_exists:
            con.execute("INSERT INTO production_objectives(campaign_id,updated_at) VALUES(?,?)",(campaign_id,utcnow()))
            objective=con.execute("SELECT * FROM production_objectives WHERE campaign_id=?",(campaign_id,)).fetchone()
    objective_dict=dict(objective) if objective else {'campaign_id':campaign_id,'objective':'one_safe_delivery_per_group_per_cycle','max_uncertain':0,'max_in_flight':1,'min_account_health':50,'require_database_guard':0,'admin_by_exception':1}
    healthy=[a for a in accounts if int(a.get('authorized') or 0) and int(a.get('enabled') or 0) and int(a.get('health_score') or 0)>=int(objective_dict['min_account_health'])]
    if not healthy: blockers.append('no authorized account meets V6 minimum health objective')
    if int(objective_dict['require_database_guard'] or 0) and not guard: blockers.append('database one-unresolved-group guard required by objective but not installed')
    elif not guard: warnings.append('database anti-spam UNIQUE guard deferred; application guards remain active')
    if recovery['requires_attention']: warnings.append('recovery controller sees component attention')
    return {**base,'ready':not blockers,'blockers':blockers,'warnings':warnings,'v6':True,'health':health,'predictive_plan':plan,'recovery':recovery,
            'database_guard_installed':guard,'accounts':accounts,'objective':objective_dict}


def render_v6_control(snapshot: dict) -> str:
    h=snapshot['health']; p=snapshot['predictive_plan']; r=snapshot['recovery']
    lines=['SMART AUTO POSTER V6 CONTROL PLANE','='*72,
           f"Campaign: {snapshot['campaign_id']}",
           f"Production readiness: {'READY' if snapshot['ready'] else 'BLOCKED'}",
           f"Production health: {h['health_score']}/100 | reliability {h['average_reliability']} | timing risk {h['average_timing_risk']}",
           f"Queue evidence: UNCERTAIN {snapshot['uncertain']} | in-flight {snapshot['in_flight']} | overlap review {snapshot['queue_hygiene']['review_count']}",
           f"Predictive routing: ready {p['counts']['ready_now']} | timing-wait {p['counts']['timing_wait']} | review {p['counts']['review']}",
           f"DB anti-spam guard: {'INSTALLED' if snapshot['database_guard_installed'] else 'DEGRADED/APP GUARDS'}",
           f"Recovery actions: {len(r['recommended_actions'])}"]
    if snapshot['blockers']:
        lines.append('BLOCKERS:'); lines += [f" - {x}" for x in snapshot['blockers']]
    if snapshot['warnings']:
        lines.append('WARNINGS:'); lines += [f" - {x}" for x in snapshot['warnings']]
    return '\n'.join(lines)
