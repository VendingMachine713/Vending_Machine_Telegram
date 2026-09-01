from __future__ import annotations

from datetime import datetime, timedelta, timezone

from database import Database, utcnow


class AutomationEngine:
    def __init__(self, db: Database):
        self.db=db

    def _marker(self,tid,key):
        r=self.db.one('SELECT marker_value FROM milestone_markers WHERE telegram_id=? AND marker_key=?',(tid,key))
        return r['marker_value'] if r else None

    def _set_marker(self,tid,key,value):
        self.db.execute(
            """INSERT INTO milestone_markers(telegram_id,marker_key,marker_value,updated_at)
               VALUES (?,?,?,?) ON CONFLICT(telegram_id,marker_key) DO UPDATE SET
               marker_value=excluded.marker_value,updated_at=excluded.updated_at""",
            (tid,key,str(value),utcnow()))

    def _event(self,tid,event_type,details):
        self.db.execute('INSERT INTO relationship_events(telegram_id,event_type,details,created_at) VALUES (?,?,?,?)',(tid,event_type,details,utcnow()))
        import json
        self.db.execute('INSERT INTO integration_events(source,event_type,telegram_id,payload_json,status,created_at) VALUES (?,?,?,?,?,?)',('relationship_manager',event_type,tid,json.dumps({'details':details},ensure_ascii=False),'pending',utcnow()))

    def _attention(self,tid,priority,category,title,details):
        r=self.db.one("SELECT id FROM attention_queue WHERE telegram_id=? AND category=? AND status='open'",(tid,category))
        if r:
            self.db.execute('UPDATE attention_queue SET priority=?,title=?,details=? WHERE id=?',(priority,title,details,r['id']))
        else:
            self.db.execute('INSERT INTO attention_queue(telegram_id,priority,category,title,details,created_at) VALUES (?,?,?,?,?,?)',(tid,priority,category,title,details,utcnow()))

    def _resolve(self,tid,category):
        self.db.execute("UPDATE attention_queue SET status='resolved',resolved_at=? WHERE telegram_id=? AND category=? AND status='open'",(utcnow(),tid,category))

    def evaluate_contact(self,tid:int):
        c=self.db.one('SELECT * FROM contacts WHERE telegram_id=?',(tid,))
        i=self.db.one('SELECT * FROM contact_intelligence WHERE telegram_id=?',(tid,))
        b=self.db.one('SELECT * FROM behavior_metrics WHERE telegram_id=?',(tid,))
        n=self.db.one('SELECT * FROM network_metrics WHERE telegram_id=?',(tid,))
        if not c or not i: return

        score=int(c['relationship_score']); health=int(i['health_score'])
        score_band='vip_candidate' if score>=80 else 'strong' if score>=60 else 'developing' if score>=40 else 'early'
        old=self._marker(tid,'score_band')
        order={'early':0,'developing':1,'strong':2,'vip_candidate':3}
        if old and old != score_band and order.get(score_band,0)>order.get(old,0):
            self._event(tid,'relationship_milestone',f'Relationship advanced: {old} -> {score_band} ({score}/100)')
        self._set_marker(tid,'score_band',score_band)

        health_band='healthy' if health>=70 else 'watch' if health>=50 else 'poor' if health>=35 else 'critical'
        old_h=self._marker(tid,'health_band')
        horder={'critical':0,'poor':1,'watch':2,'healthy':3}
        if old_h and old_h != health_band:
            if horder[health_band] < horder.get(old_h,3) and score>=45:
                self._event(tid,'health_declined',f'{old_h} -> {health_band} ({health}/100)')
                self._attention(tid,'red' if health_band=='critical' else 'orange','health_transition','Relationship health declined',f'Health moved {old_h} â†’ {health_band} ({health}/100).')
            elif horder[health_band] > horder.get(old_h,0):
                self._event(tid,'health_recovered',f'{old_h} -> {health_band} ({health}/100)')
                if health>=50: self._resolve(tid,'health_transition')
        self._set_marker(tid,'health_band',health_band)

        momentum=i['momentum_label']
        old_m=self._marker(tid,'momentum')
        if old_m and old_m != momentum and momentum!='learning':
            self._event(tid,'momentum_changed',f'{old_m} -> {momentum}')
        self._set_marker(tid,'momentum',momentum)

        if c['typical_cycle_days'] is not None and self._marker(tid,'cycle_learned') is None:
            self._event(tid,'cycle_learned',f"Typical contact cycle learned: {c['typical_cycle_days']:g} days")
            self._set_marker(tid,'cycle_learned',c['typical_cycle_days'])

        days=int(c['active_days'])
        achieved=max([x for x in (5,10,30,50,100,250) if days>=x],default=0)
        old_days=int(self._marker(tid,'active_days_milestone') or 0)
        if achieved>old_days:
            self._event(tid,'activity_milestone',f'{achieved} active days observed')
            self._set_marker(tid,'active_days_milestone',achieved)

        if n and n['bridge_score']>=70 and self._marker(tid,'bridge_contact')!='yes':
            self._event(tid,'network_milestone',f"Bridge contact estimate reached {n['bridge_score']}/100")
            self._set_marker(tid,'bridge_contact','yes')

        if b and b['behavior_label'] in {'mutual','they_initiate','you_initiate'}:
            old_b=self._marker(tid,'behavior_pattern')
            if old_b and old_b != b['behavior_label']:
                self._event(tid,'behavior_pattern_changed',f"{old_b} -> {b['behavior_label']}")
            self._set_marker(tid,'behavior_pattern',b['behavior_label'])

    def evaluate_all(self):
        for r in self.db.all('SELECT telegram_id FROM contacts'):
            self.evaluate_contact(r['telegram_id'])
        self.process_opportunity_due()
        self.process_goal_due()

    def process_opportunity_due(self):
        now=utcnow()
        rows=self.db.all(
            """SELECT o.*,c.relationship_score FROM opportunities o JOIN contacts c ON c.telegram_id=o.telegram_id
               WHERE o.status IN ('open','paused')""")
        due_contacts=set(); unhealthy_contacts=set()
        for o in rows:
            if o['due_at'] is not None and o['due_at']<=now and o['status']=='open':
                due_contacts.add(o['telegram_id'])
                self._attention(o['telegram_id'],'orange','opportunity_due','Opportunity next action due',f"#{o['id']} {o['title']}: {o['next_action'] or 'Next action due'}")
            if int(o['health_score'] or 100)<55:
                unhealthy_contacts.add(o['telegram_id'])
                self._attention(o['telegram_id'],'yellow' if int(o['health_score'])>=35 else 'orange','opportunity_health','Opportunity is stagnating',f"#{o['id']} {o['title']} health {o['health_score']}/100 Â· stale {o['stale_days']}d")
        for r in self.db.all("SELECT DISTINCT telegram_id FROM attention_queue WHERE category='opportunity_due' AND status='open'"):
            if r['telegram_id'] not in due_contacts: self._resolve(r['telegram_id'],'opportunity_due')
        for r in self.db.all("SELECT DISTINCT telegram_id FROM attention_queue WHERE category='opportunity_health' AND status='open'"):
            if r['telegram_id'] not in unhealthy_contacts: self._resolve(r['telegram_id'],'opportunity_health')

    def process_goal_due(self):
        now=utcnow()
        rows=self.db.all(
            """SELECT g.*,c.relationship_score FROM relationship_goals g
               JOIN contacts c ON c.telegram_id=g.telegram_id
               WHERE g.status='active' AND g.target_at IS NOT NULL AND g.target_at<=?""",
            (now,))
        due_contacts=set()
        for g in rows:
            due_contacts.add(g['telegram_id'])
            priority='orange' if int(g['priority'] or 50)>=70 else 'yellow'
            self._attention(g['telegram_id'],priority,'goal_due','Relationship goal due',f"#{g['id']} {g['title']} Â· {g['progress_pct']}% Â· {g['next_step'] or 'Next step not set'}")
        for r in self.db.all("SELECT DISTINCT telegram_id FROM attention_queue WHERE category='goal_due' AND status='open'"):
            if r['telegram_id'] not in due_contacts:
                self._resolve(r['telegram_id'],'goal_due')

    def recent_changes(self,days:int=7,limit:int=30):
        cutoff=(datetime.now(timezone.utc)-timedelta(days=days)).isoformat()
        return self.db.all(
            """SELECT e.*,c.display_name,c.username FROM relationship_events e
               LEFT JOIN contacts c ON c.telegram_id=e.telegram_id
               WHERE e.created_at>=? AND e.event_type IN
               ('relationship_milestone','health_declined','health_recovered','momentum_changed','cycle_learned','activity_milestone','network_milestone','behavior_pattern_changed')
               ORDER BY e.created_at DESC LIMIT ?""",(cutoff,limit))
