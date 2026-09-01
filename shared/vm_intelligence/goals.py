from __future__ import annotations
from datetime import datetime, timezone

DEFAULT_GOALS=[
    ("ecosystem_score","VM_Intelligence","overall_score",">=",90.0,"Keep ecosystem intelligence score at or above 90"),
    ("critical_incidents","VM_Intelligence","critical_incidents","<=",0.0,"Keep critical incidents at zero"),
    ("managed_services_down","VM_Platform","managed_services_down","<=",0.0,"Keep VM-managed services online"),
    ("backup_integrity","VM_Intelligence","latest_backup_integrity",">=",1.0,"Keep latest VM backup integrity verified"),
    ("intelligence_db_integrity","VM_Intelligence","intelligence_db_integrity",">=",1.0,"Keep VM Intelligence database integrity verified"),
]

class GoalEngine:
    def __init__(self,store):
        self.store=store

    def seed(self):
        now=datetime.now(timezone.utc).isoformat()
        with self.store.connect() as con:
            for key,source,metric,op,target,title in DEFAULT_GOALS:
                con.execute("""INSERT OR IGNORE INTO operational_goals(
                    goal_key,source,metric,operator,target,title,created_at_utc,updated_at_utc)
                    VALUES(?,?,?,?,?,?,?,?)""",(key,source,metric,op,target,title,now,now))

    def set_goal(self,key,source,metric,operator,target,title):
        import re
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}",key):
            raise ValueError("goal key must contain only letters, numbers, dot, underscore or dash")
        if operator not in {">=","<=",">","<","=="}:raise ValueError("unsupported operator")
        now=datetime.now(timezone.utc).isoformat()
        with self.store.connect() as con:
            con.execute("""INSERT INTO operational_goals(
                goal_key,source,metric,operator,target,enabled,title,created_at_utc,updated_at_utc)
                VALUES(?,?,?,?,?,1,?,?,?)
                ON CONFLICT(goal_key) DO UPDATE SET source=excluded.source,metric=excluded.metric,
                  operator=excluded.operator,target=excluded.target,title=excluded.title,
                  enabled=1,updated_at_utc=excluded.updated_at_utc""",
                (key,source,metric,operator,float(target),title,now,now))

    def set_enabled(self,key,enabled):
        now=datetime.now(timezone.utc).isoformat()
        with self.store.connect() as con:
            cur=con.execute("UPDATE operational_goals SET enabled=?,updated_at_utc=? WHERE goal_key=?",
                            (1 if enabled else 0,now,key))
            if cur.rowcount==0:raise KeyError(key)

    @staticmethod
    def _ok(actual,op,target):
        if actual is None:return None
        if op==">=":return actual>=target
        if op=="<=":return actual<=target
        if op==">":return actual>target
        if op=="<":return actual<target
        if op=="==":return actual==target
        return None

    def evaluate(self,context):
        self.seed();now=datetime.now(timezone.utc).isoformat();out=[]
        with self.store.connect() as con:
            rows=con.execute("SELECT * FROM operational_goals WHERE enabled=1 ORDER BY goal_id").fetchall()
            for r in rows:
                actual=context.get(r["metric"])
                if actual is None:
                    metric_row=con.execute("""SELECT value FROM bot_metrics
                        WHERE source=? AND metric=? ORDER BY observed_at_utc DESC LIMIT 1""",
                        (r["source"],r["metric"])).fetchone()
                    actual=metric_row[0] if metric_row else None
                ok=self._ok(actual,r["operator"],r["target"])
                status="unknown" if ok is None else "met" if ok else "missed"
                con.execute("""INSERT INTO goal_evaluations(goal_key,observed_at_utc,actual,target,status,details)
                    VALUES(?,?,?,?,?,?)""",(r["goal_key"],now,actual,r["target"],status,r["title"]))
                out.append({"goal_key":r["goal_key"],"title":r["title"],"actual":actual,
                            "operator":r["operator"],"target":r["target"],"status":status})
        return out
