from __future__ import annotations
from datetime import datetime,timezone
import json
from .v6_schema import ensure_v6_schema

def _now():return datetime.now(timezone.utc).isoformat()
class RunbookFactory:
    def __init__(self,store):self.store=store;ensure_v6_schema(store)
    def record_validation(self,runbook_key,version,*,simulation_status=None,shadow_status=None,evidence=None):
        allowed={'pending','passed','failed','not_run'}
        if simulation_status is not None and simulation_status not in allowed:raise ValueError('invalid simulation_status')
        if shadow_status is not None and shadow_status not in allowed:raise ValueError('invalid shadow_status')
        sets=[];args=[]
        if simulation_status is not None:sets.append('simulation_status=?');args.append(simulation_status)
        if shadow_status is not None:sets.append('shadow_status=?');args.append(shadow_status)
        if evidence is not None:sets.append('evidence_json=?');args.append(json.dumps(evidence,sort_keys=True,default=str))
        if not sets:return False
        args.extend([runbook_key,version])
        with self.store.connect() as con:
            cur=con.execute(f"UPDATE runbook_revisions SET {','.join(sets)} WHERE runbook_key=? AND version=?",args)
        return cur.rowcount>0
    @staticmethod
    def _derive_status(row,trust):
        if row.get('simulation_status')=='failed' or row.get('shadow_status')=='failed':return 'REVOKED'
        if row.get('simulation_status')!='passed':return 'DRAFT'
        if row.get('shadow_status')!='passed':return 'SIMULATED'
        if not trust or trust.get('attempts',0)<5:return 'SHADOW'
        if trust.get('certification')=='certified' and float(trust.get('trust_score') or 0)>=95:return 'CERTIFIED_L4'
        if trust.get('certification') in {'provisional','certified'}:return 'PROVISIONAL'
        return 'SHADOW'
    def refresh(self,automation_candidates,runbook_trust):
        created=[];trust_by={x.get('runbook_key'):x for x in (runbook_trust or [])}
        with self.store.connect() as con:
            for c in automation_candidates or []:
                key='auto_'+c['candidate_key']
                if con.execute('SELECT 1 FROM runbook_revisions WHERE runbook_key=? LIMIT 1',(key,)).fetchone():continue
                definition=c.get('runbook') or {}
                con.execute('INSERT INTO runbook_revisions(runbook_key,version,status,generated_at_utc,parent_revision_id,trust_score,simulation_status,shadow_status,definition_json,evidence_json) VALUES(?,?,?,?,?,?,?,?,?,?)',
                    (key,1,'DRAFT',_now(),None,0,'pending','pending',json.dumps(definition,sort_keys=True),json.dumps({'candidate':c['candidate_key']},sort_keys=True)))
                created.append({'runbook_key':key,'version':1,'status':'DRAFT'})
            rows=[dict(r) for r in con.execute('SELECT * FROM runbook_revisions ORDER BY runbook_key,version DESC').fetchall()]
            for r in rows:
                trust=trust_by.get(r['runbook_key']) or trust_by.get(r['runbook_key'].removeprefix('auto_'))
                status=self._derive_status(r,trust)
                trust_score=float((trust or {}).get('trust_score') or 0)
                if status!=r.get('status') or trust_score!=float(r.get('trust_score') or 0):
                    con.execute('UPDATE runbook_revisions SET status=?,trust_score=? WHERE revision_id=?',(status,trust_score,r['revision_id']))
                    r['status']=status;r['trust_score']=trust_score
        for r in rows:
            try:r['definition']=json.loads(r.pop('definition_json'))
            except Exception:r['definition']={}
            r['certification_ready']=bool(r['status'] in {'PROVISIONAL','CERTIFIED_L4','CERTIFIED_L5'})
        return {'created':created,'revisions':rows,'automatic_certification':False,
                'certification_rule':'simulation passed + shadow passed + measured trust; higher authority remains capability-governed',
                'states':['DRAFT','SIMULATED','SHADOW','PROVISIONAL','CERTIFIED_L4','CERTIFIED_L5','REVOKED']}
