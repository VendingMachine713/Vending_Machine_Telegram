from __future__ import annotations
import argparse,json
from pathlib import Path
from .store import IntelligenceStore
from .v4_schema import ensure_v4_schema
from .analytics import IntelligenceAnalyzer
from .recommendations import RecommendationEngine
from .reporting import build_report,write_report
from .ingest import ingest_vm_diagnostics

def resolve_root(value):
    if value:return Path(value).resolve()
    here=Path.cwd().resolve()
    for c in [here,*here.parents]:
        if (c/"bots").exists() and (c/"shared").exists():return c
    return here

def main(argv=None):
    p=argparse.ArgumentParser(prog="vm-intelligence");p.add_argument("--root")
    s=p.add_subparsers(dest="cmd",required=True)
    s.add_parser("ingest");r=s.add_parser("report");r.add_argument("--hours",type=int,default=24)
    s.add_parser("status");s.add_parser("brain");s.add_parser("cycle");s.add_parser("doctor");s.add_parser("backup")
    s.add_parser("registry");s.add_parser("slo");s.add_parser("objectives");s.add_parser("autonomy")
    al=s.add_parser("autonomy-set");al.add_argument("level",type=int)
    impact=s.add_parser("impact");impact.add_argument("paths",nargs="+")
    a=s.add_parser("agent");a.add_argument("--interval",type=int,default=60)
    q=s.add_parser("ask");q.add_argument("question",nargs="+")
    e=s.add_parser("experiment");e.add_argument("--name",required=True);e.add_argument("--source",required=True)
    e.add_argument("--hypothesis",required=True);e.add_argument("--metric",required=True);e.add_argument("--baseline",type=float)
    args=p.parse_args(argv);root=resolve_root(args.root)
    store=IntelligenceStore(root/"state"/"vm_intelligence.sqlite3");ensure_v4_schema(store)
    analyzer=IntelligenceAnalyzer(store);engine=RecommendationEngine(store,analyzer)
    if args.cmd=="ingest":
        print(json.dumps({"ingested":ingest_vm_diagnostics(store,root)}));return 0
    if args.cmd=="report":
        rep=build_report(store,analyzer,engine,hours=max(1,args.hours),root=root);j,t=write_report(rep,root/"diagnostics")
        print(json.dumps({"json":str(j),"text":str(t),"events":rep["summary"]["events"],
                          "score":rep["scorecard"]["overall"],"incidents":len(rep["incidents"])}));return 0
    if args.cmd=="status":
        print(json.dumps(analyzer.summary(24),indent=2));return 0
    if args.cmd=="brain":
        from .brain import Brain
        snap=Brain(store,root).executive_snapshot(24)
        concise={
            "scorecard":snap["scorecard"],
            "incidents":snap["incidents"][:20],
            "inbox":snap["inbox"][:20],
            "bot_scoreboard":snap["bot_scoreboard"],
            "goals":snap["goals"],
            "security":{"score":snap["security"]["score"],"findings":snap["security"]["findings"][:10]},
            "predictive_maintenance":snap["predictive_maintenance"][:10],
            "cto_priorities":snap["cto_priorities"][:10],
            "meta_intelligence":snap["meta_intelligence"],
            "runtime_registry":snap["runtime_registry"],
            "reliability":snap["reliability"],
            "objectives":snap["objectives"],
            "autonomy":snap["autonomy"],
            "platform_normalization":snap["platform_normalization"],
            "full_report":str(root/"diagnostics"/"intelligence_report.json"),
        }
        print(json.dumps(concise,indent=2,default=str));return 0
    if args.cmd=="registry":
        from .runtime_registry import RuntimeRegistry
        print(json.dumps(RuntimeRegistry(store,root).refresh(),indent=2,default=str));return 0
    if args.cmd=="slo":
        from .brain import Brain
        print(json.dumps(Brain(store,root).executive_snapshot(24)["reliability"],indent=2,default=str));return 0
    if args.cmd=="objectives":
        from .brain import Brain
        print(json.dumps(Brain(store,root).executive_snapshot(24)["objectives"],indent=2,default=str));return 0
    if args.cmd=="autonomy":
        from .autonomy import AutonomyController
        print(json.dumps(AutonomyController(store).state(),indent=2,default=str));return 0
    if args.cmd=="autonomy-set":
        from .autonomy import AutonomyController
        print(json.dumps(AutonomyController(store).set_level(args.level,"CLI administrator request"),indent=2,default=str));return 0
    if args.cmd=="impact":
        from .dependency_graph import DependencyGraph
        graph=DependencyGraph(store,root);graph.build();print(json.dumps(graph.impact(args.paths),indent=2,default=str));return 0
    if args.cmd=="cycle":
        from .agent import IntelligenceAgent
        print(json.dumps(IntelligenceAgent(root).cycle(),indent=2,default=str));return 0
    if args.cmd=="agent":
        from .agent import IntelligenceAgent
        return IntelligenceAgent(root,args.interval).run_forever()
    if args.cmd=="doctor":
        from .doctor import run_doctor
        result=run_doctor(root);print(json.dumps(result,indent=2,default=str));return 0 if result["ok"] else 2
    if args.cmd=="backup":
        from .backup import backup_intelligence
        print(json.dumps({"backup":str(backup_intelligence(root))}));return 0
    if args.cmd=="ask":
        from .brain import Brain
        from .ask import AskEngine
        print(json.dumps(AskEngine(Brain(store,root)).answer(" ".join(args.question)),indent=2,default=str));return 0
    if args.cmd=="experiment":
        eid=store.create_experiment(name=args.name,source=args.source,hypothesis=args.hypothesis,
                                    metric=args.metric,baseline=args.baseline)
        print(json.dumps({"experiment_id":eid,"status":"pending"}));return 0
    return 2
if __name__=="__main__":raise SystemExit(main())
