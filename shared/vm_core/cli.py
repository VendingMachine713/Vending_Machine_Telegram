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
from .services import service_status, start_service, stop_service, restart_service
from .health import run_health
from .health_engine import health_snapshot, format_health_snapshot
from .backup import create_backup, list_backups, rollback
from .registry import sync_accounts, sync_destinations, registry_summary
from .jobs import enqueue, run_one
from .events import emit
from .simulate import run_scenario, SCENARIOS
from .support import create_support_bundle
from .checks import run_tests, lint, format_check, full_check
from .release import set_baseline, build_delta
from .logging_setup import tail_logs
from .supervisor import supervise_once, supervise_loop
from .duplicates import write_duplicate_report
from .validation import run_full_validation
from .devtools import install as install_devtools, git_status
from .intelligence import intelligence_summary, format_intelligence_summary
from .foundation import foundation_report, format_foundation_report
from .platform_registry import service_registry, write_service_registry, format_service_registry
from .config_registry import configuration_registry, write_configuration_registry, format_configuration_registry
from .runtime_registry import runtime_registry, write_runtime_registry, format_runtime_registry
from .core1_readiness import core1_readiness, format_core1_readiness
from .heartbeat import heartbeat_snapshot, format_heartbeat_snapshot
from .watchdog import watchdog_snapshot, format_watchdog_snapshot
from .recovery_classifier import recovery_plan, format_recovery_plan
from .recovery_executor import execute_recovery_plan

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
    print(f"Destinations: {reg['destinations']} | Accounts: {reg['accounts']} | Recent jobs: {len(jobs)} | Recent events: {len(events)}")
    print(f"Bots: {len(bots)} total | {runnable} runnable | {planned} planned")
    return 0

def build_parser():
    p=argparse.ArgumentParser(prog="vm",description="Vending Machine Telegram Platform")
    p.add_argument("--version",action="version",version=f"vm_core {__version__}")
    s=p.add_subparsers(dest="command",required=True)
    for name,help_text in [
        ("status","Show VM service state."),("dashboard","Show platform dashboard."),
        ("doctor","Run diagnostics."),("inspect","Write safe structure report."),
        ("inventory","Refresh machine-readable inventory."),("health","Run service health checks."),
        ("health-v2","Run universal health classification."),\n        ("heartbeats","Show universal heartbeat freshness."),\n        ("watchdog","Run read-only universal watchdog analysis."),\n        ("recovery-plan","Classify failures and show policy-gated recovery decisions."),
        ("recovery-execute","Preview or apply policy-gated safe lifecycle recovery."),
        ("env","Show environment/developer tools."),("deps","Show dependency inventory."),
        ("test","Run platform self-tests."),("check","Run release pre-flight checks."),
        ("support","Create safe support bundle."),("registry","Sync/show shared registries."),
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
        ("intelligence","Refresh and show shared cross-bot intelligence."),
        ("foundation","Validate the VM Core foundation contract."),
        ("core-readiness","Show Core 1 Foundation readiness and adoption."),
        ("init","Initialise platform folders/database."),
    ]: s.add_parser(name,help=help_text)
    m=s.add_parser("manifests",help="Preview/create/refresh bot manifests."); m.add_argument("--write",action="store_true"); m.add_argument("--refresh",action="store_true")
    s.choices["dev-tools"].add_argument("--apply",action="store_true")
    setup=s.add_parser("setup",help="Preview/install bot dependencies."); setup.add_argument("--apply",action="store_true")
    lintp=s.add_parser("lint",help="Run Ruff when available."); lintp.add_argument("--fix",action="store_true")
    fmt=s.add_parser("format-check",help="Check formatting with Ruff.")
    for action in ("start","stop","restart"):
        q=s.add_parser(action,help=f"{action.title()} a VM service."); q.add_argument("service"); q.add_argument("--apply",action="store_true"); q.add_argument("--force",action="store_true")
    s.choices["logs"].add_argument("service",nargs="?",default="platform"); s.choices["logs"].add_argument("--lines",type=int,default=50); s.choices["logs"].add_argument("--errors",action="store_true")
    s.choices["registry"].add_argument("action",choices=["summary","sync","services","config","runtime"],nargs="?",default="summary"); s.choices["registry"].add_argument("--write",action="store_true")
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
    s.choices["recovery-execute"].add_argument("--apply-safe",action="store_true")
    return p

def main(argv=None):
    args=build_parser().parse_args(argv); root=project_root(); ensure_platform_dirs(root); PlatformDB(root=root).init()
    c=args.command
    if c=="status": return cmd_status(root)
    if c=="dashboard": return cmd_dashboard(root)
    if c=="foundation":
        report=foundation_report(root); print(format_foundation_report(report)); return 2 if report["summary"]["ERROR"] else 0
    if c=="core-readiness":
        report=core1_readiness(root); print(format_core1_readiness(report)); return 0 if report["status"]=="PASS" else 2
    if c=="health-v2":
        report=health_snapshot(root); print(format_health_snapshot(report)); return 2 if report["status"]=="ATTENTION_REQUIRED" else 0
    if c=="heartbeats":
        report=heartbeat_snapshot(root); print(format_heartbeat_snapshot(report)); return 2 if report["summary"]["EXPIRED"] else 0
    if c=="watchdog":
        report=watchdog_snapshot(root); print(format_watchdog_snapshot(report)); return 2 if report["state"]=="ATTENTION_REQUIRED" else 0
    if c=="recovery-plan":
        report=recovery_plan(root); print(format_recovery_plan(report)); return 2 if report["summary"]["BLOCKED"] or report["summary"]["REVIEW_REQUIRED"] else 0
    if c=="recovery-execute":
        plan=recovery_plan(root); _json(execute_recovery_plan(plan,root,apply=args.apply_safe)); return 0
    if c=="intelligence":
        print(format_intelligence_summary(intelligence_summary(root, refresh=True))); return 0
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
    if c=="env": _json(environment_report(root)); return 0
    if c=="deps":
        _json({"requirements":requirements_inventory(root),"pip_check":pip_check()}); return 0
    if c=="setup":
        _json(setup_dependencies(root,apply=args.apply)); return 0
    if c=="test": return run_tests(root)
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
            if c=="start": results.append(start_service(name,root,dry_run=not args.apply,force=args.force))
            elif c=="stop": results.append(stop_service(name,root,dry_run=not args.apply))
            else: results.append(restart_service(name,root,dry_run=not args.apply,force=args.force))
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
        elif args.action=="services":
            report=service_registry(root)
            if args.write:
                print(write_service_registry(root))
            else:
                print(format_service_registry(report))
        elif args.action=="config":
            report=configuration_registry(root)
            if args.write:
                print(write_configuration_registry(root))
            else:
                print(format_configuration_registry(report))
        elif args.action=="runtime":
            report=runtime_registry(root)
            if args.write:
                print(write_runtime_registry(root))
            else:
                print(format_runtime_registry(report))
        else:
            _json(registry_summary(root))
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
    if c=="release-baseline": print(set_baseline(args.service,root)); return 0
    if c=="release": _json(build_delta(args.service,root)); return 0
    if c=="supervise": _json(supervise_once(root,apply=args.apply)); return 0
    if c=="supervise-loop": supervise_loop(root,apply=args.apply,interval_seconds=args.interval); return 0
    if c=="duplicates":
        jp,tp=write_duplicate_report(root); print(f"TEXT: {tp}\nJSON: {jp}"); return 0
    if c=="validate-all":
        summary=run_full_validation(root, backup_first=True)
        _json(summary)
        print("\nSupport bundle:")
        print(create_support_bundle(root))
        return 0 if summary["platform_tests_ok"] and summary["doctor_summary"]["FAIL"]==0 else 2
    if c=="dev-tools": _json(install_devtools(apply=args.apply)); return 0
    if c=="git-status": _json(git_status(root)); return 0
    return 1

if __name__=="__main__": raise SystemExit(main())
