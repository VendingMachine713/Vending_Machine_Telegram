from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
from . import __version__
from .paths import project_root, ensure_platform_dirs
from .manifests import discover_bots, write_inventory, create_missing_bot_manifests, refresh_bot_manifests
from .doctor import run_doctor, write_diagnostics
from .inspect import write_structure_report
from .dependencies import environment_report, requirements_inventory, pip_check, setup_dependencies
from .db import PlatformDB
from .services import service_status, start_service, stop_service, restart_service, start_managed
from .health import run_health
from .backup import create_backup, list_backups, rollback
from .registry import sync_accounts, sync_destinations, registry_summary
from .jobs import enqueue, run_one
from .events import emit
from .simulate import run_scenario, SCENARIOS
from .support import create_support_bundle, create_support_text
from .checks import run_tests, run_all_tests, lint, format_check, full_check
from .release import set_baseline, build_delta
from .logging_setup import tail_logs
from .supervisor import supervise_once, supervise_loop
from .duplicates import write_duplicate_report
from .validation import run_full_validation
from .devtools import install as install_devtools, git_status
from .search_index import SearchIndex
from .guard_engine import guard_pass
from .runtime_snapshot import write_report as write_runtime_report, verify as verify_runtime
from .autostart import status as autostart_status
from .relationship_cleanup import plan as relationship_cleanup_plan, apply as apply_relationship_cleanup
from .legacy_recovery import recover as recover_legacy, write_report as write_legacy_recovery_report
from .git_audit import audit as git_audit
from .storage_audit import audit as storage_audit
from .stabilization import run_stabilization, write_stabilization_report


def _json(obj): print(json.dumps(obj,indent=2,ensure_ascii=False,default=str))

def cmd_status(root):
    rows=service_status(root)
    print("="*78); print(f" VENDING MACHINE PLATFORM v{__version__}"); print("="*78)
    for r in rows:
        alive="ALIVE" if r.get("process_alive") else r["runtime_status"]
        print(f"{r['name']:<28} {alive:<10} entry={r.get('entrypoint') or 'not detected'}")
    print(f"\nServices discovered: {len(rows)}")
    return 0

def cmd_dashboard(root):
    health=run_health(root); reg=registry_summary(root); db=PlatformDB(root=root)
    jobs=db.jobs(10); events=db.events(10)
    print("="*78); print(" VM DASHBOARD"); print("="*78)
    for h in health: print(f"{h['status']:<10} {h['service']}")
    print("-"*78)
    bots=discover_bots(root)
    runnable=sum(1 for b in bots if b.classification=="CANONICAL")
    planned=sum(1 for b in bots if b.classification=="PLACEHOLDER")
    alert_count=len(db.alerts(100))
    try: search_docs=SearchIndex(root).stats()["documents"]
    except Exception: search_docs=0
    print(f"Destinations: {reg['destinations']} | Accounts: {reg['accounts']} | Recent jobs: {len(jobs)} | Recent events: {len(events)}")
    print(f"Bots: {len(bots)} total | {runnable} runnable | {planned} planned")
    print(f"Open alerts: {alert_count} | Search documents: {search_docs}")
    return 0

def build_parser():
    p=argparse.ArgumentParser(prog="vm",description="Vending Machine Telegram Platform")
    p.add_argument("--version",action="version",version=f"vm_core {__version__}")
    s=p.add_subparsers(dest="command",required=True)
    for name,help_text in [
        ("status","Show VM service state."),("dashboard","Show platform dashboard."),
        ("doctor","Run diagnostics."),("inspect","Write safe structure report."),
        ("inventory","Refresh machine-readable inventory."),("health","Run service health checks."),
        ("env","Show environment/developer tools."),("deps","Show dependency inventory."),
        ("test","Run platform self-tests."),("test-all","Run platform and all bot test suites."),("check","Run release pre-flight checks."),
        ("support","Create safe support bundle."),("support-text","Create one safe readable support text file."),("registry","Sync/show shared registries."),
        ("jobs","Manage platform jobs."),("events","Manage platform events."),
        ("simulate","Run safe simulated scenarios."),("backup","Create/list backups."),
        ("rollback","Preview/apply rollback."),("logs","Show structured logs."),
        ("release-baseline","Set a bot release baseline."),("release","Build a bot delta release."),
        ("supervise","Run one self-healing supervisor pass."),
        ("supervise-loop","Run persistent self-healing supervisor loop."),
        ("duplicates","Analyze nested duplicate bot folders safely."),
        ("validate-all","Run the complete platform validation and create one rich support bundle."),
        ("dev-tools","Preview/install Ruff and uv developer tools."),
        ("git-status","Show safe local Git repository status."),
        ("git-audit","Audit Git tracked files for sensitive/runtime data."),
        ("storage","Show project/disk storage usage without deleting anything."),
        ("search","Search the local Universal Search index."),
        ("search-refresh","Rebuild the local Universal Search index."),
        ("alerts","Show open VM Guard alerts."),
        ("guard","Run one VM Guard pass."),
        ("start-managed","Start services whose manifests opt into auto_start."),
        ("runtime","Write/show the live runtime snapshot."),
        ("autostart-status","Show Windows logon autostart state."),
        ("relationship-cleanup","Preview or apply safe nested Relationship Manager cleanup."),
        ("legacy-recovery","Preview/apply recovery of pre-v1.3 Search/Guard Telegram components."),
        ("runtime-check","Verify managed services/components and optional autostart."),
        ("stabilize","Audit runtime, database, backup, Git drift, and recovery readiness."),
        ("init","Initialise platform folders/database."),
    ]: s.add_parser(name,help=help_text)
    m=s.add_parser("manifests",help="Preview/create/refresh bot manifests."); m.add_argument("--write",action="store_true"); m.add_argument("--refresh",action="store_true")
    s.choices["dev-tools"].add_argument("--apply",action="store_true")
    s.choices["search"].add_argument("query",nargs="+")
    s.choices["search"].add_argument("--limit",type=int,default=20)
    s.choices["start-managed"].add_argument("--apply",action="store_true")
    s.choices["start-managed"].add_argument("--foreground",action="store_true")
    s.choices["relationship-cleanup"].add_argument("--apply",action="store_true")
    s.choices["legacy-recovery"].add_argument("--apply",action="store_true")
    s.choices["runtime-check"].add_argument("--require-autostart",action="store_true")
    s.choices["runtime-check"].add_argument("--require-legacy-components",action="store_true")
    s.choices["stabilize"].add_argument("--reference",default="origin/dev/v6.2-brain-native-fabric-final2")
    setup=s.add_parser("setup",help="Preview/install bot dependencies."); setup.add_argument("--apply",action="store_true")
    lintp=s.add_parser("lint",help="Run Ruff when available."); lintp.add_argument("--fix",action="store_true")
    fmt=s.add_parser("format-check",help="Check formatting with Ruff.")
    for action in ("start","stop","restart"):
        q=s.add_parser(action,help=f"{action.title()} a VM service."); q.add_argument("service"); q.add_argument("--apply",action="store_true"); q.add_argument("--force",action="store_true"); q.add_argument("--background",action="store_true")
    s.choices["logs"].add_argument("service",nargs="?",default="platform"); s.choices["logs"].add_argument("--lines",type=int,default=50); s.choices["logs"].add_argument("--errors",action="store_true")
    s.choices["registry"].add_argument("action",choices=["summary","sync"],nargs="?",default="summary")
    s.choices["jobs"].add_argument("action",choices=["list","enqueue","run-one"],nargs="?",default="list"); s.choices["jobs"].add_argument("job_type",nargs="?")
    s.choices["events"].add_argument("action",choices=["list","emit"],nargs="?",default="list"); s.choices["events"].add_argument("event_type",nargs="?")
    s.choices["simulate"].add_argument("scenario",choices=sorted(SCENARIOS))
    s.choices["backup"].add_argument("action",choices=["create","list"],nargs="?",default="create")
    s.choices["rollback"].add_argument("backup",nargs="?"); s.choices["rollback"].add_argument("--apply",action="store_true")
    s.choices["release-baseline"].add_argument("service")
    s.choices["release"].add_argument("service")
    s.choices["supervise"].add_argument("--apply",action="store_true")
    s.choices["supervise-loop"].add_argument("--apply",action="store_true")
    s.choices["supervise-loop"].add_argument("--interval",type=int,default=60)
    return p

def main(argv=None):
    args=build_parser().parse_args(argv); root=project_root(); ensure_platform_dirs(root); PlatformDB(root=root).init()
    c=args.command
    if c=="status": return cmd_status(root)
    if c=="dashboard": return cmd_dashboard(root)
    if c=="init":
        write_inventory(root); create_missing_bot_manifests(root,write=True); print(f"Initialised: {root}"); return 0
    if c=="doctor":
        report=run_doctor(root); jp,tp=write_diagnostics(report,root); print(tp.read_text(encoding="utf-8")); return 2 if report["summary"]["FAIL"] else 0
    if c=="inspect":
        jp,tp=write_structure_report(root); print(f"TEXT: {tp}\nJSON: {jp}"); return 0
    if c=="inventory": print(write_inventory(root)); return 0
    if c=="manifests":
        if args.refresh:
            _json(refresh_bot_manifests(root, write=args.write))
        else:
            _json(create_missing_bot_manifests(root,write=args.write))
        return 0
    if c=="health": _json(run_health(root)); return 0
    if c=="stabilize":
        result=run_stabilization(root,args.reference); jp,tp=write_stabilization_report(result,root)
        _json({"report":result,"json":str(jp),"text":str(tp)})
        return 0 if result["release_ready"] else 2
    if c=="env": _json(environment_report(root)); return 0
    if c=="deps":
        _json({"requirements":requirements_inventory(root),"pip_check":pip_check()}); return 0
    if c=="setup":
        _json(setup_dependencies(root,apply=args.apply)); return 0
    if c=="test": return run_tests(root)
    if c=="test-all":
        result=run_all_tests(root); _json(result); return 0 if result["ok"] else 2
    if c=="lint":
        result=lint(root,args.fix); _json(result); return 0 if result["ok"] else 2
    if c=="format-check":
        result=format_check(root); _json(result); return 0 if result["ok"] else 2
    if c=="check":
        result=full_check(root); _json(result); return 0 if result["ok"] else 2
    if c in {"start","stop","restart"}:
        names=[b.folder for b in discover_bots(root)] if args.service.lower()=="all" else [args.service]
        results=[]
        for name in names:
            if c=="start": results.append(start_service(name,root,dry_run=not args.apply,force=args.force,background=args.background))
            elif c=="stop": results.append(stop_service(name,root,dry_run=not args.apply))
            else: results.append(restart_service(name,root,dry_run=not args.apply,force=args.force,background=args.background))
        _json(results if len(results)>1 else results[0]); return 0
    if c=="backup":
        if args.action=="list": _json([str(p) for p in list_backups(root)])
        else: print(create_backup(root))
        return 0
    if c=="rollback":
        backups=list_backups(root)
        if args.backup: b=Path(args.backup)
        elif backups: b=backups[0]
        else: print("No backups found."); return 1
        _json(rollback(b,root,apply=args.apply)); return 0
    if c=="registry":
        if args.action=="sync":
            _json({"accounts_synced":sync_accounts(root),"destinations":sync_destinations(root),"summary":registry_summary(root)})
        else: _json(registry_summary(root))
        return 0
    if c=="jobs":
        db=PlatformDB(root=root)
        if args.action=="list": _json(db.jobs(50))
        elif args.action=="run-one": _json(run_one(root))
        else:
            if not args.job_type: print("job_type required"); return 1
            print(enqueue(args.job_type,{},root))
        return 0
    if c=="events":
        db=PlatformDB(root=root)
        if args.action=="list": _json(db.events(50))
        else:
            if not args.event_type: print("event_type required"); return 1
            print(emit(args.event_type,"manual",{},root))
        return 0
    if c=="simulate": _json(run_scenario(args.scenario,root)); return 0
    if c=="logs":
        lines=tail_logs(args.service,args.lines,args.errors,root)
        print("\n".join(lines) if lines else "No matching logs."); return 0
    if c=="support": print(create_support_bundle(root)); return 0
    if c=="support-text": print(create_support_text(root)); return 0
    if c=="release-baseline": print(set_baseline(args.service,root)); return 0
    if c=="release": _json(build_delta(args.service,root)); return 0
    if c=="supervise": _json(supervise_once(root,apply=args.apply)); return 0
    if c=="supervise-loop": supervise_loop(root,apply=args.apply,interval_seconds=args.interval); return 0
    if c=="duplicates":
        jp,tp,dp=write_duplicate_report(root); print(f"TEXT: {tp}\nJSON: {jp}\nDIFF: {dp}"); return 0
    if c=="validate-all":
        summary=run_full_validation(root, backup_first=True)
        _json(summary)
        print("\nSupport bundle:")
        print(create_support_bundle(root))
        return 0 if summary["critical_tests_ok"] and summary["doctor_summary"]["FAIL"]==0 else 2
    if c=="dev-tools": _json(install_devtools(apply=args.apply)); return 0
    if c=="git-status": _json(git_status(root)); return 0
    if c=="git-audit":
        result=git_audit(root); _json(result); return 0 if result.get("ok",True) else 2
    if c=="storage": _json(storage_audit(root)); return 0
    if c=="search":
        _json(SearchIndex(root).search(" ".join(args.query),args.limit)); return 0
    if c=="search-refresh":
        _json(SearchIndex(root).rebuild()); return 0
    if c=="alerts":
        _json(PlatformDB(root=root).alerts(50)); return 0
    if c=="guard":
        _json(guard_pass(root)); return 0
    if c=="start-managed":
        _json(start_managed(root,dry_run=not args.apply,background=not args.foreground)); return 0
    if c=="runtime":
        jp,tp=write_runtime_report(root); print(tp.read_text(encoding="utf-8")); print(f"JSON: {jp}"); return 0
    if c=="autostart-status":
        _json(autostart_status(root)); return 0
    if c=="relationship-cleanup":
        result=apply_relationship_cleanup(root) if args.apply else relationship_cleanup_plan(root)
        _json(result); return 0 if (not args.apply or result.get("ok")) else 2
    if c=="legacy-recovery":
        result=recover_legacy(root,apply=args.apply)
        write_legacy_recovery_report(root,apply=False)
        _json(result); return 0 if result.get("ok",True) else 2
    if c=="runtime-check":
        result=verify_runtime(root,require_autostart=args.require_autostart,
                              require_legacy_components=args.require_legacy_components)
        _json(result); return 0 if result.get("ok") else 2
    return 1

if __name__=="__main__": raise SystemExit(main())
