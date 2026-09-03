from __future__ import annotations

from datetime import datetime, timezone

from database import Database, utcnow

STAGES={
    'lead':10,'contacted':20,'interested':40,'negotiating':65,
    'active':85,'won':100,'lost':0,'paused':20,
}

class OpportunityEngine:
    def __init__(self,db:Database): self.db=db

    def create(self,telegram_id:int,title:str,admin_id:int):
        title=title.strip()
        if not title: raise ValueError('Opportunity title cannot be empty.')
        oid=self.db.execute(
            """INSERT INTO opportunities
               (telegram_id,title,stage,status,probability,created_by,created_at,updated_at,health_score,stale_days)
               VALUES (?,?,'lead','open',10,?,?,?,100,0)""",
            (telegram_id,title,admin_id,utcnow(),utcnow()),
        )
        return self.get(oid)

    def get(self,opportunity_id:int):
        return self.db.one('SELECT * FROM opportunities WHERE id=?',(opportunity_id,))

    def set_stage(self,opportunity_id:int,stage:str):
        stage=stage.lower().strip()
        if stage not in STAGES: raise ValueError('Invalid stage.')
        status='open'; closed=None
        if stage in {'won','lost'}: status=stage; closed=utcnow()
        elif stage=='paused': status='paused'
        self.db.execute(
            """UPDATE opportunities SET stage=?,status=?,probability=?,closed_at=?,updated_at=? WHERE id=?""",
            (stage,status,STAGES[stage],closed,utcnow(),opportunity_id),
        )
        self.evaluate_health(opportunity_id)
        return self.get(opportunity_id)

    def set_value(self,opportunity_id:int,amount:float,currency:str='AUD'):
        if amount < 0: raise ValueError('Value must be non-negative.')
        currency=(currency or 'AUD').upper()[:8]
        self.db.execute('UPDATE opportunities SET value_cents=?,currency=?,updated_at=? WHERE id=?',
                        (round(amount*100),currency,utcnow(),opportunity_id))
        self.evaluate_health(opportunity_id)
        return self.get(opportunity_id)

    def set_next(self,opportunity_id:int,next_action:str,due_at:datetime|None=None):
        due=due_at.astimezone(timezone.utc).isoformat() if due_at else None
        self.db.execute('UPDATE opportunities SET next_action=?,due_at=?,updated_at=? WHERE id=?',
                        (next_action.strip() or None,due,utcnow(),opportunity_id))
        self.evaluate_health(opportunity_id)
        return self.get(opportunity_id)

    def evaluate_health(self, opportunity_id:int):
        o=self.get(opportunity_id)
        if not o: return None
        if o['status'] in {'won','lost'}:
            health=100 if o['status']=='won' else 0
            stale=0
        else:
            now=datetime.now(timezone.utc)
            updated=datetime.fromisoformat(o['updated_at'])
            stale=max(0,(now-updated).days)
            health=100
            if stale>7: health-=min(45,(stale-7)*3)
            if o['due_at']:
                due=datetime.fromisoformat(o['due_at'])
                overdue=max(0,(now-due).days)
                if overdue: health-=min(40,10+overdue*5)
            if not o['next_action']: health-=15
            if o['stage']=='paused': health=min(health,55)
            health=max(0,min(100,health))
        self.db.execute('UPDATE opportunities SET health_score=?,stale_days=? WHERE id=?',(health,stale,opportunity_id))
        return self.get(opportunity_id)

    def evaluate_all(self):
        rows=self.db.all("SELECT id FROM opportunities WHERE status IN ('open','paused')")
        for r in rows: self.evaluate_health(r['id'])
        return len(rows)

    def open_for_contact(self,telegram_id:int):
        rows=self.db.all(
            """SELECT * FROM opportunities WHERE telegram_id=? AND status IN ('open','paused')
               ORDER BY health_score ASC,CASE stage WHEN 'negotiating' THEN 1 WHEN 'interested' THEN 2 WHEN 'contacted' THEN 3 WHEN 'active' THEN 4 ELSE 5 END,
                        COALESCE(due_at,'9999') ASC,id DESC""",(telegram_id,))
        return rows

    def pipeline(self,limit:int=30):
        return self.db.all(
            """SELECT o.*,c.display_name,c.username FROM opportunities o
               JOIN contacts c ON c.telegram_id=o.telegram_id
               WHERE o.status IN ('open','paused')
               ORDER BY o.health_score ASC,
                        CASE o.stage WHEN 'negotiating' THEN 1 WHEN 'interested' THEN 2 WHEN 'contacted' THEN 3 WHEN 'active' THEN 4 WHEN 'lead' THEN 5 ELSE 6 END,
                        COALESCE(o.due_at,'9999') ASC,o.updated_at DESC LIMIT ?""",(limit,))

    def summary(self):
        row=self.db.one("SELECT COUNT(*) n FROM opportunities WHERE status IN ('open','paused')")
        values=self.db.all(
            """SELECT currency,
                      COALESCE(SUM(CASE WHEN value_cents IS NOT NULL THEN value_cents*probability/100 ELSE 0 END),0) weighted,
                      COALESCE(SUM(CASE WHEN value_cents IS NOT NULL THEN value_cents ELSE 0 END),0) gross
               FROM opportunities WHERE status IN ('open','paused') GROUP BY currency""")
        by_currency={r['currency']:int(r['weighted'] or 0) for r in values}
        gross_by_currency={r['currency']:int(r['gross'] or 0) for r in values}
        unhealthy=self.db.one("SELECT COUNT(*) n FROM opportunities WHERE status IN ('open','paused') AND health_score<60")['n']
        return {'open':row['n'],'by_currency':by_currency,'gross_by_currency':gross_by_currency,
                'weighted_cents':by_currency.get('AUD',0),'unhealthy':unhealthy}
