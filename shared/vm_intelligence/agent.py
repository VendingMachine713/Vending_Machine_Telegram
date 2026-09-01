from __future__ import annotations
from pathlib import Path
from datetime import datetime,timezone
import json,os,time,traceback
from .store import IntelligenceStore
from .integrated_schema import ensure_v3_schema
from .ingest import ingest_vm_diagnostics
from .analytics import IntelligenceAnalyzer
from .recommendations import RecommendationEngine
from .reporting import build_report,write_report
from .maintenance import MaintenanceEngine
from .releases import ReleaseIntelligence
from .release_learning import ReleaseLearning
from .self_heal import SelfHealingController
from .notifications import TelegramNotifier
from .metrics import MetricStore

class FileLock:
    def __init__(self,path):self.path=Path(path);self.f=None
    def acquire(self):
        self.path.parent.mkdir(parents=True,exist_ok=True);self.f=open(self.path,"a+")
        try:
            if os.name=="nt":
                import msvcrt
                self.f.seek(0);self.f.write("0");self.f.flush();self.f.seek(0)
                msvcrt.locking(self.f.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl;fcntl.flock(self.f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            return True
        except Exception:return False
    def close(self):
        if self.f:
            try:self.f.close()
            except Exception:pass

class IntelligenceAgent:
    def __init__(self,root,interval=60):
        self.root=Path(root);self.interval=max(15,int(interval))
        self.store=IntelligenceStore(self.root/"state"/"vm_intelligence.sqlite3")
        ensure_v3_schema(self.store)
        self.log=self.root/"logs"/"vm_intelligence_agent.log";self.log.parent.mkdir(parents=True,exist_ok=True)
        self.pid_path=self.root/"state"/"vm_intelligence_agent.pid"

    def _log(self,msg):
        with self.log.open("a",encoding="utf-8") as f:
            f.write(f"{datetime.now(timezone.utc).isoformat()} {msg}\n")

    def cycle(self):
        start=time.perf_counter();started=datetime.now(timezone.utc).isoformat()
        status="ok";details={};ingested=0;report={};actions=[]
        try:
            ingested=ingest_vm_diagnostics(self.store,self.root)
            maintenance=MaintenanceEngine(self.store,self.root).run()
            metric_store=MetricStore(self.store)
            if maintenance.get("latest_backup_integrity") is not None:
                metric_store.record("VM_Intelligence","latest_backup_integrity",
                    1 if maintenance["latest_backup_integrity"] else 0,quality="verified")
            metric_store.record("VM_Intelligence","intelligence_db_integrity",
                1 if maintenance.get("intelligence_db_integrity") else 0,quality="verified")
            actions=SelfHealingController(self.store,self.root).run()
            analyzer=IntelligenceAnalyzer(self.store);rec=RecommendationEngine(self.store,analyzer)
            report=build_report(self.store,analyzer,rec,hours=24,root=self.root)
            release_changes=ReleaseIntelligence(self.store,self.root).refresh(report["scorecard"]["overall"])
            release_learning=ReleaseLearning(self.store).evaluate(report["scorecard"]["overall"])
            write_report(report,self.root/"diagnostics")
            notifications=TelegramNotifier(self.store,self.root).notify(report)
            self.store.add_snapshot("executive",{
                "scorecard":report["scorecard"],"incidents":len(report["incidents"]),
                "actions":actions,"release_changes":release_changes})
            details={"release_changes":release_changes,"release_learning":release_learning,
                     "maintenance":maintenance,"notifications":notifications}
            return {"ingested":ingested,"score":report["scorecard"]["overall"],
                    "metric_sources":len(report["integrated"]),"incidents":len(report["incidents"]),
                    "self_heal_actions":actions,"release_changes":release_changes,
                    "release_learning":release_learning,"maintenance":maintenance,
                    "notifications":notifications}
        except Exception as exc:
            status="error";details={"error":type(exc).__name__}
            raise
        finally:
            completed=datetime.now(timezone.utc).isoformat()
            duration=(time.perf_counter()-start)*1000
            try:
                with self.store.connect() as con:
                    con.execute("""INSERT INTO intelligence_cycles(
                        started_at_utc,completed_at_utc,duration_ms,ingested_events,metric_sources,
                        incident_count,action_count,status,details_json) VALUES(?,?,?,?,?,?,?,?,?)""",
                        (started,completed,duration,ingested,len(report.get("integrated",{})),
                         len(report.get("incidents",[])),len(actions),status,json.dumps(details,default=str)))
            except Exception:pass

    def run_forever(self):
        lock=FileLock(self.root/"state"/"vm_intelligence_agent.lock")
        if not lock.acquire():
            self._log("another agent instance already owns the lock; exiting");return 0
        self.pid_path.write_text(str(os.getpid()),encoding="ascii")
        self._log("v3 agent started")
        try:
            while True:
                started=time.time()
                try:self._log("cycle "+json.dumps(self.cycle(),default=str))
                except Exception:self._log("cycle_error "+traceback.format_exc().replace("\n"," | "))
                time.sleep(max(1,self.interval-(time.time()-started)))
        finally:
            try:self.pid_path.unlink(missing_ok=True)
            except Exception:pass
            lock.close()
