from __future__ import annotations

import hashlib
import json
import uuid
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
        'classification_changed','recommended_action_changed','autonomy_exception','maintenance_warning',
        'classifier_calibration_changed','operations_health_changed',
    }
    CONTRACT_VERSION='6.0'

    def __init__(self,db:Database,export_dir:Path|None=None):
        self.db=db
        self.export_dir=Path(export_dir or db.path.parent)/'integration'
        self.export_dir.mkdir(parents=True,exist_ok=True)

    @staticmethod
    def _priority(event_type:str)->int:
        if event_type in {'risk_signal','maintenance_warning','autonomy_exception'}: return 90
        if event_type in {'recommended_action_changed','health_declined','operations_health_changed'}: return 75
        if event_type in {'classification_changed','opportunity_stage','verification_changed'}: return 65
        return 50

    @staticmethod
    def _dedupe_key(source:str,event_type:str,telegram_id:int|None,payload:dict)->str:
        # One-hour bucket suppresses repeated maintenance/scheduler emissions while
        # still allowing the same state transition to be emitted again later.
        bucket=datetime.now(timezone.utc).strftime('%Y%m%d%H')
        canonical=json.dumps(payload or {},ensure_ascii=False,sort_keys=True,separators=(',',':'))
        raw=f'{source}|{event_type}|{telegram_id}|{bucket}|{canonical}'.encode('utf-8')
        return hashlib.sha256(raw).hexdigest()

    def emit(self,event_type:str,telegram_id:int|None,payload:dict|None=None,source:str='relationship_manager'):
        if event_type not in self.SAFE_EVENT_TYPES and source=='relationship_manager':
            return None
        payload=payload or {}
        dedupe=self._dedupe_key(source,event_type,telegram_id,payload)
        existing=self.db.one('SELECT id FROM integration_events WHERE dedupe_key=?',(dedupe,))
        if existing:
            return existing['id']
        event_uuid=str(uuid.uuid4())
        try:
            return self.db.execute(
                '''INSERT INTO integration_events
                   (source,event_type,telegram_id,payload_json,status,created_at,attempt_count,
                    event_uuid,event_version,dedupe_key,priority)
                   VALUES (?,?,?,?,?,?,0,?,?,?,?)''',
                (source,event_type,telegram_id,json.dumps(payload,ensure_ascii=False,sort_keys=True),'pending',utcnow(),
                 event_uuid,'1',dedupe,self._priority(event_type)))
        except Exception:
            # A concurrent scheduler/admin path may have inserted the same unique
            # dedupe key between the select and insert.
            row=self.db.one('SELECT id FROM integration_events WHERE dedupe_key=?',(dedupe,))
            return row['id'] if row else None

    def ingest_external_signal(self,source:str,event_type:str,telegram_id:int,severity:int=1,details:str=''):
        severity=max(1,min(5,int(severity)))
        self.db.execute(
            """INSERT INTO risk_flags(telegram_id,source,severity,reason,review_status,created_at)
               VALUES (?,?,?,?, 'pending', ?)""",
            (telegram_id,source,severity,details or event_type,utcnow()))
        self.db.execute(
            'INSERT INTO relationship_events(telegram_id,event_type,details,created_at) VALUES (?,?,?,?)',
            (telegram_id,'external_risk_signal',f'{source}: {event_type} â€” {details}',utcnow()))
        self.emit('risk_signal',telegram_id,{'source':source,'event_type':event_type,'severity':severity,'details':details},source=source)

    def export_contacts_index(self):
        rows=self.db.all(
            """SELECT c.*, i.health_score,i.momentum_label,i.lifecycle_stage,
                      b.reciprocity_score,b.behavior_label,
                      n.reach_score,n.bridge_score,n.network_label,
                      p.priority_score,p.priority_band,p.next_action,
                      f.disengagement_risk,f.reengagement_priority,f.outlook_label,f.confidence AS outlook_confidence,
                      q.completeness_score,q.confidence_score,
                      s.sessions_30,s.session_label,
                      x.predicted_type,x.confidence AS classification_confidence,x.decision_state AS classification_state,
                      (SELECT COUNT(*) FROM recommended_actions ra WHERE ra.telegram_id=c.telegram_id AND ra.status IN ('open','snoozed') AND (ra.cooldown_until IS NULL OR ra.cooldown_until<=?)) AS open_actions,
                      (SELECT COALESCE(MAX(action_score),0) FROM recommended_actions ra WHERE ra.telegram_id=c.telegram_id AND ra.status IN ('open','snoozed') AND (ra.cooldown_until IS NULL OR ra.cooldown_until<=?)) AS max_action_score
               FROM contacts c
               LEFT JOIN contact_intelligence i ON i.telegram_id=c.telegram_id
               LEFT JOIN behavior_metrics b ON b.telegram_id=c.telegram_id
               LEFT JOIN network_metrics n ON n.telegram_id=c.telegram_id
               LEFT JOIN contact_priorities p ON p.telegram_id=c.telegram_id
               LEFT JOIN contact_forecasts f ON f.telegram_id=c.telegram_id
               LEFT JOIN data_quality_metrics q ON q.telegram_id=c.telegram_id
               LEFT JOIN conversation_session_metrics s ON s.telegram_id=c.telegram_id
               LEFT JOIN contact_classifications x ON x.telegram_id=c.telegram_id
               LEFT JOIN contact_controls cc ON cc.telegram_id=c.telegram_id
               WHERE COALESCE(cc.excluded,0)=0
               ORDER BY COALESCE(p.priority_score,0) DESC,c.relationship_score DESC,c.last_seen DESC""",(utcnow(),utcnow()))
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
                'predicted_relationship_type':r['predicted_type'],'classification_confidence':r['classification_confidence'],
                'classification_state':r['classification_state'],'open_actions':r['open_actions'],'max_action_score':r['max_action_score'],
                'segments':[x['segment_key'] for x in self.db.all('SELECT segment_key FROM contact_segments WHERE telegram_id=? ORDER BY confidence DESC,segment_key',(tid,))],
                'active_goals':[{'id':x['id'],'type':x['goal_type'],'title':x['title'],'priority':x['priority'],'target_at':x['target_at'],'progress_pct':x['progress_pct']} for x in self.db.all("SELECT id,goal_type,title,priority,target_at,progress_pct FROM relationship_goals WHERE telegram_id=? AND status='active' ORDER BY priority DESC,target_at",(tid,))],
                'first_seen':r['first_seen'],'last_seen':r['last_seen'],'tags':tags,'groups':groups,
            })
        path=self.export_dir/'relationship_contacts_index.json'
        tmp=path.with_suffix('.json.tmp')
        tmp.write_text(json.dumps({'generated_at':utcnow(),'schema_version':'6.0.0','contract_version':self.CONTRACT_VERSION,'contacts':data},ensure_ascii=False,indent=2),encoding='utf-8')
        tmp.replace(path)
        return path,len(data)

    def _rotate_outbox(self,path:Path,max_bytes:int=5_000_000,keep:int=5):
        try:
            if not path.exists() or path.stat().st_size < max_bytes:
                return
            stamp=datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
            rotated=path.with_name(f'{path.stem}_{stamp}{path.suffix}')
            path.replace(rotated)
            old=sorted(path.parent.glob(f'{path.stem}_*{path.suffix}'),key=lambda p:p.stat().st_mtime,reverse=True)
            for p in old[keep:]:
                p.unlink(missing_ok=True)
        except Exception:
            pass

    def export_events(self,limit:int=1000):
        now=utcnow()
        rows=self.db.all(
            """SELECT * FROM integration_events
               WHERE status IN ('pending','retry') AND (next_attempt_at IS NULL OR next_attempt_at<=?)
               ORDER BY priority DESC,id ASC LIMIT ?""",(now,limit))
        path=self.export_dir/'relationship_events_outbox.jsonl'
        if not rows: return path,0
        self._rotate_outbox(path)
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
                    event_uuid=r['event_uuid'] or str(uuid.uuid4())
                    if not r['event_uuid']:
                        self.db.execute('UPDATE integration_events SET event_uuid=? WHERE id=?',(event_uuid,r['id']))
                    obj={
                        'contract_version':self.CONTRACT_VERSION,'event_uuid':event_uuid,
                        'event_version':r['event_version'] or '1','dedupe_key':r['dedupe_key'],'priority':int(r['priority'] or 50),
                        'id':r['id'],'source':r['source'],'event_type':r['event_type'],'telegram_id':r['telegram_id'],
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
