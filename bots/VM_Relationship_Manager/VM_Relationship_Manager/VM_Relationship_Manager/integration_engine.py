from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from database import Database, utcnow


class IntegrationEngine:
    SAFE_EVENT_TYPES={
        'relationship_milestone','health_declined','health_recovered','momentum_changed',
        'cycle_learned','activity_milestone','network_milestone','behavior_pattern_changed',
        'verification_changed','relationship_type_changed','opportunity_created','opportunity_stage',
        'risk_signal','contact_archived','contact_restored','contact_excluded','contact_included',
        'priority_changed','memory_changed','group_intelligence_changed','risk_reviewed',
        'goal_created','goal_updated','goal_completed','segment_changed','forecast_changed',
    }

    def __init__(self,db:Database,export_dir:Path|None=None):
        self.db=db
        self.export_dir=Path(export_dir or db.path.parent)/'integration'
        self.export_dir.mkdir(parents=True,exist_ok=True)

    def emit(self,event_type:str,telegram_id:int|None,payload:dict|None=None,source:str='relationship_manager'):
        if event_type not in self.SAFE_EVENT_TYPES and source=='relationship_manager':
            return None
        return self.db.execute(
            '''INSERT INTO integration_events
               (source,event_type,telegram_id,payload_json,status,created_at,attempt_count)
               VALUES (?,?,?,?,?,?,0)''',
            (source,event_type,telegram_id,json.dumps(payload or {},ensure_ascii=False,sort_keys=True),'pending',utcnow()))

    def ingest_external_signal(self,source:str,event_type:str,telegram_id:int,severity:int=1,details:str=''):
        severity=max(1,min(5,int(severity)))
        self.db.execute(
            """INSERT INTO risk_flags(telegram_id,source,severity,reason,review_status,created_at)
               VALUES (?,?,?,?, 'pending', ?)""",
            (telegram_id,source,severity,details or event_type,utcnow()))
        self.db.execute(
            'INSERT INTO relationship_events(telegram_id,event_type,details,created_at) VALUES (?,?,?,?)',
            (telegram_id,'external_risk_signal',f'{source}: {event_type} — {details}',utcnow()))
        self.emit('risk_signal',telegram_id,{'source':source,'event_type':event_type,'severity':severity,'details':details},source=source)

    def export_contacts_index(self):
        rows=self.db.all(
            """SELECT c.*, i.health_score,i.momentum_label,i.lifecycle_stage,
                      b.reciprocity_score,b.behavior_label,
                      n.reach_score,n.bridge_score,n.network_label,
                      p.priority_score,p.priority_band,p.next_action,
                      f.disengagement_risk,f.reengagement_priority,f.outlook_label,f.confidence AS outlook_confidence,
                      q.completeness_score,q.confidence_score,
                      s.sessions_30,s.session_label
               FROM contacts c
               LEFT JOIN contact_intelligence i ON i.telegram_id=c.telegram_id
               LEFT JOIN behavior_metrics b ON b.telegram_id=c.telegram_id
               LEFT JOIN network_metrics n ON n.telegram_id=c.telegram_id
               LEFT JOIN contact_priorities p ON p.telegram_id=c.telegram_id
               LEFT JOIN contact_forecasts f ON f.telegram_id=c.telegram_id
               LEFT JOIN data_quality_metrics q ON q.telegram_id=c.telegram_id
               LEFT JOIN conversation_session_metrics s ON s.telegram_id=c.telegram_id
               LEFT JOIN contact_controls cc ON cc.telegram_id=c.telegram_id
               WHERE COALESCE(cc.excluded,0)=0
               ORDER BY COALESCE(p.priority_score,0) DESC,c.relationship_score DESC,c.last_seen DESC""")
        data=[]
        for r in rows:
            tid=r['telegram_id']
            tags=[x['tag'] for x in self.db.all('SELECT tag FROM tags WHERE telegram_id=? ORDER BY tag',(tid,))]
            groups=[{'chat_id':x['chat_id'],'chat_title':x['chat_title']} for x in self.db.all('SELECT chat_id,chat_title FROM contact_groups WHERE telegram_id=? ORDER BY last_seen DESC',(tid,))]
            data.append({
                'telegram_id':tid,'username':r['username'],'display_name':r['display_name'],
                'relationship_type':r['relationship_type'],'activity_status':r['activity_status'],
                'verification_status':r['verification_status'],'relationship_score':r['relationship_score'],
                'trust_score':r['trust_score'],'health_score':r['health_score'],
                'momentum':r['momentum_label'],'lifecycle':r['lifecycle_stage'],
                'reciprocity_score':r['reciprocity_score'],'behavior':r['behavior_label'],
                'network_reach':r['reach_score'],'bridge_score':r['bridge_score'],'network_role':r['network_label'],
                'priority_score':r['priority_score'],'priority_band':r['priority_band'],'next_action':r['next_action'],
                'outlook_risk':r['disengagement_risk'],'reengagement_priority':r['reengagement_priority'],
                'outlook':r['outlook_label'],'outlook_confidence':r['outlook_confidence'],
                'data_completeness':r['completeness_score'],'data_confidence':r['confidence_score'],
                'sessions_30':r['sessions_30'],'session_pattern':r['session_label'],
                'segments':[x['segment_key'] for x in self.db.all('SELECT segment_key FROM contact_segments WHERE telegram_id=? ORDER BY confidence DESC,segment_key',(tid,))],
                'active_goals':[{'id':x['id'],'type':x['goal_type'],'title':x['title'],'priority':x['priority'],'target_at':x['target_at'],'progress_pct':x['progress_pct']} for x in self.db.all("SELECT id,goal_type,title,priority,target_at,progress_pct FROM relationship_goals WHERE telegram_id=? AND status='active' ORDER BY priority DESC,target_at",(tid,))],
                'first_seen':r['first_seen'],'last_seen':r['last_seen'],'tags':tags,'groups':groups,
            })
        path=self.export_dir/'relationship_contacts_index.json'
        tmp=path.with_suffix('.json.tmp')
        tmp.write_text(json.dumps({'generated_at':utcnow(),'schema_version':'4.0.0','contacts':data},ensure_ascii=False,indent=2),encoding='utf-8')
        tmp.replace(path)
        return path,len(data)

    def export_events(self,limit:int=1000):
        now=utcnow()
        rows=self.db.all(
            """SELECT * FROM integration_events
               WHERE status IN ('pending','retry') AND (next_attempt_at IS NULL OR next_attempt_at<=?)
               ORDER BY id ASC LIMIT ?""",(now,limit))
        if not rows: return self.export_dir/'relationship_events_outbox.jsonl',0
        path=self.export_dir/'relationship_events_outbox.jsonl'
        exported=[]
        try:
            fh=path.open('a',encoding='utf-8')
        except Exception as exc:
            for r in rows:
                attempts=int(r['attempt_count'] or 0)+1
                delay=min(3600,60*(2**min(attempts,5)))
                nxt=(datetime.now(timezone.utc)+timedelta(seconds=delay)).isoformat()
                self.db.execute(
                    "UPDATE integration_events SET status='retry',attempt_count=?,last_error=?,next_attempt_at=? WHERE id=?",
                    (attempts,repr(exc)[:500],nxt,r['id']))
            return path,0
        with fh:
            for r in rows:
                try:
                    obj={'id':r['id'],'source':r['source'],'event_type':r['event_type'],'telegram_id':r['telegram_id'],
                         'payload':json.loads(r['payload_json'] or '{}'),'created_at':r['created_at']}
                    fh.write(json.dumps(obj,ensure_ascii=False,sort_keys=True)+'\n')
                    exported.append(r['id'])
                except Exception as exc:
                    attempts=int(r['attempt_count'] or 0)+1
                    delay=min(3600,60*(2**min(attempts,5)))
                    nxt=(datetime.now(timezone.utc)+timedelta(seconds=delay)).isoformat()
                    self.db.execute(
                        "UPDATE integration_events SET status='retry',attempt_count=?,last_error=?,next_attempt_at=? WHERE id=?",
                        (attempts,repr(exc)[:500],nxt,r['id']))
        if exported:
            marks=','.join('?' for _ in exported)
            self.db.execute(f"UPDATE integration_events SET status='exported',exported_at=?,last_error=NULL,next_attempt_at=NULL WHERE id IN ({marks})",(utcnow(),*exported))
        return path,len(exported)

    def backlog(self):
        return self.db.one(
            """SELECT COUNT(*) total,
                      SUM(CASE WHEN status='retry' THEN 1 ELSE 0 END) retrying,
                      COALESCE(MAX(attempt_count),0) max_attempts
               FROM integration_events WHERE status IN ('pending','retry')""")

    def export_all(self):
        contact_path,count=self.export_contacts_index()
        event_path,event_count=self.export_events()
        return {'contacts_path':str(contact_path),'contacts':count,'events_path':str(event_path),'events':event_count}
