from __future__ import annotations
from pathlib import Path
from datetime import datetime,timezone
import json
from .store import IntelligenceStore
from .brain import Brain
from .ask import AskEngine
from .simulation import SimulationEngine

COMMANDS={
 "brain","insights","incidents","recommendations","improvements","experiments",
 "performance","learning","why","what_changed","askvm","goals","automation","intelhelp",
 "security","cto","league","predict","autopsy","twin","meta","inbox","efficiency",
 "capacity","simulate","causal","cost","testing","intelfeedback",
 "goalset","goalon","goaloff","experimentstart","experimentfinish",
 "registry","drift","slo","errorbudget","objective","autonomy","safe","whyact","runbooks","impact","releasegate","attention","configreg","reliability","runbooktrust","plan","captrust","failurefamilies","forecast","shadowautomation","engineering","releaseintel","truth","policy","intervention","runbookfactory","dr","horizons","modernize"
}
def is_intelligence_command(cmd):return cmd in COMMANDS
def _store(root):return IntelligenceStore(Path(root)/"state"/"vm_intelligence.sqlite3")
def _brain(root):return Brain(_store(root),root)
def _clip(text):return text[:3900]

def _snapshot(root,max_age_seconds=600):
    path=Path(root)/"diagnostics"/"intelligence_report.json"
    if path.is_file():
        try:
            data=json.loads(path.read_text(encoding="utf-8-sig"))
            stamp=datetime.fromisoformat(str(data.get("generated_at_utc","")).replace("Z","+00:00"))
            age=(datetime.now(timezone.utc)-stamp).total_seconds()
            if 0 <= age <= max_age_seconds:
                return data,True
        except Exception:
            pass
    return _brain(root).executive_snapshot(24),False

def handle_intelligence_command(cmd,args,root):
    s,_cached=_snapshot(root)
    store=None
    if cmd=="intelhelp":
        return _clip(
          "VM INTELLIGENCE COMMANDS\n"
          "/brain /inbox /insights /incidents /why [service]\n"
          "/performance /league /predict /security /capacity\n"
          "/recommendations /automation /efficiency /cto\n"
          "/improvements /experiments /learning /causal\n"
          "/goals /what_changed /testing /autopsy /meta\n"
          "/twin /cost /simulate <action> /askvm <question>\n"
          "/intelfeedback <incident_id> useful|noise\n"
          "/registry /configreg /drift /slo /errorbudget /reliability\n"
          "/runbooks /runbooktrust /objective /plan /autonomy /captrust /safe /whyact\n"
          "/failurefamilies /forecast /shadowautomation /engineering /impact /releasegate /releaseintel /attention\n"
          "/truth /policy /intervention /runbookfactory /dr /horizons /modernize"
        )
    if cmd=="brain":
        sc=s["scorecard"];high=sum(1 for x in s["incidents"] if x["severity"] in {"critical","high"})
        urgent=sum(1 for x in s["inbox"] if x["priority"] in {"P0","P1"})
        return _clip(
          "VM INTELLIGENCE BRAIN\n"
          f"Overall: {sc['overall']}/100 | Security: {s['security']['score']}/100\n"
          f"Incidents: {len(s['incidents'])} ({high} high/critical)\n"
          f"Predicted risks: {len(s['predictive_maintenance'])}\n"
          f"Automation opportunities: {len(s['automation_opportunities'])}\n"
          f"Goals missed: {sum(1 for g in s['goals'] if g['status']=='missed')}\n"
          f"Meta health: {s['meta_intelligence']['self_health']}\n"
          f"Top priority: {(s['strategic_planner_v5']['backlog'][0]['title'] if s.get('strategic_planner_v5',{}).get('backlog') else (s['cto_priorities'][0]['title'] if s['cto_priorities'] else 'None'))}\n"
          f"Planner: L{s.get('strategic_planner_v5',{}).get('planner_level','?')} | executable={s.get('strategic_planner_v5',{}).get('executable_count',0)} blocked={s.get('strategic_planner_v5',{}).get('blocked_count',0)}\n"
          f"User action: {'REVIEW INBOX' if urgent else 'None'}"
        )
    if cmd=="inbox":
        return _clip("VM INTELLIGENCE INBOX\n"+("\n".join(
            f"{x['priority']} {x['source']}: {x['title']}" for x in s["inbox"][:25]) or "Empty."))
    if cmd=="insights":
        return _clip("VM INSIGHTS\n"+("\n".join(f"{x['priority']:>3} {x['source']}: {x['title']}" for x in s["insights"]) or "None."))
    if cmd=="incidents":
        return _clip("VM INCIDENTS\n"+("\n".join(f"#{x['incident_id']} [{x['severity'].upper()}] {x['title']} x{x['occurrences']}" for x in s["incidents"]) or "None."))
    if cmd=="why":
        source=" ".join(args).strip() if args else None
        rows=[x for x in s["root_causes"] if not source or source.lower() in x["source"].lower()]
        return _clip("VM ROOT CAUSE\n"+("\n".join(f"{x['source']} {x['confidence']:.0%}: {x['probable_cause']}" for x in rows[:10]) or "No active root-cause report matches."))
    if cmd=="performance":
        return _clip("VM PERFORMANCE\n"+"\n".join(f"{x['score']:>5.1f}/100 {x['source']}" for x in s["bot_scoreboard"]))
    if cmd=="league":
        return _clip("VM BOT LEAGUE\n"+"\n".join(f"{i}. {x['source']} — {x['score']}/100" for i,x in enumerate(sorted(s["bot_scoreboard"],key=lambda z:-z["score"]),1)))
    if cmd in {"predict","forecast"}:
        rows=s.get("predictive_v5",{}).get("predictions",[])
        return _clip("VM PREDICTIVE OPERATIONS\n"+("\n".join(
            f"{x['status'].upper()} {x['source']} {x['metric']}: current={x.get('current')} predicted={x.get('predicted_value')} p={x.get('probability')} confidence={x.get('confidence')}"
            for x in rows) or "No predictive evidence yet."))
    if cmd=="security":
        return _clip("VM SECURITY INTELLIGENCE\n"
          f"Score: {s['security']['score']}/100\nFiles scanned: {s['security']['files_scanned']}\n"+
          ("\n".join(f"[{x['severity'].upper()}] {x['title']}: {x['detail']}" for x in s["security"]["findings"]) or "No exposure indicator detected."))
    if cmd=="capacity":
        c=s["capacity"]
        return _clip(f"VM CAPACITY\nDisk free: {c['disk_free_gib']} / {c['disk_total_gib']} GiB\nKnown DBs: {c['known_database_mib']} MiB\nCPU: {c['cpu_capacity']}\nMemory: {c['memory_capacity']}\n{c['recommendation']}")
    if cmd=="cto":
        return _clip("VM CTO PRIORITIES\n"+("\n".join(
            f"{x['priority_score']:>5} {x['source']}: {x['title']} [{x['estimated_effort']}]"
            for x in s["cto_priorities"][:15]) or "None."))
    if cmd=="efficiency":
        return _clip("VM EFFICIENCY\n"+("\n".join(f"{x['score']} {x['source']}: {x['title']}" for x in s["efficiency"]) or "No material efficiency issue detected."))
    if cmd=="recommendations":
        return _clip("VM RECOMMENDATIONS\n"+("\n".join(f"[{x['severity'].upper()}] {x['title']}" for x in s["recommendations"][:15]) or "None."))
    if cmd=="automation":
        return _clip("VM AUTOMATION OPPORTUNITIES\n"+("\n".join(f"{float(x['confidence']):.0%} {x['source']}: {x['title']}" for x in s["automation_opportunities"][:15]) or "None."))
    if cmd=="shadowautomation":
        rows=s.get("automation_discovery_v5",{}).get("candidates",[])
        return _clip("VM SHADOW AUTOMATION CANDIDATES\n"+("\n".join(
            f"{x['frequency']}x {x['title']} | save={x['estimated_minutes_saved']}m risk={x['risk']} confidence={x['confidence']:.0%}"
            for x in rows[:20]) or "No repeated workflow candidate currently qualifies."))
    if cmd=="goals":
        return _clip("VM OPERATIONAL GOALS\n"+"\n".join(f"{x['status'].upper():<7} {x['title']} | {x['actual']} {x['operator']} {x['target']}" for x in s["goals"]))
    if cmd=="goalset":
        if len(args)<6:return "Usage: /goalset <key> <source> <metric> <operator> <target> <title...>  (operator: >= <= > < ==)"
        key,source,metric,operator,target=args[:5];title=" ".join(args[5:]).strip()
        try:
            from .goals import GoalEngine
            GoalEngine(_store(root)).set_goal(key,source,metric,operator,float(target),title)
            return f"Goal {key} saved and enabled. It will be evaluated on the next Intelligence cycle."
        except Exception as exc:return f"Goal update rejected: {exc}"
    if cmd in {"goalon","goaloff"}:
        if len(args)!=1:return f"Usage: /{cmd} <goal_key>"
        try:
            from .goals import GoalEngine
            GoalEngine(_store(root)).set_enabled(args[0],cmd=="goalon")
            return f"Goal {args[0]} {'enabled' if cmd=='goalon' else 'disabled'}."
        except KeyError:return f"Goal {args[0]} was not found."
    if cmd=="improvements":
        return _clip("VM IMPROVEMENT LEDGER\n"+("\n".join(f"{x['source']}: {x['title']} -> {x['status']} delta={x['delta']}" for x in s["improvements"][:15]) or "No measured improvements yet."))
    if cmd=="experiments":
        store=store or _store(root)
        with store.connect() as con:rows=[dict(r) for r in con.execute("SELECT * FROM experiments ORDER BY updated_at_utc DESC LIMIT 15").fetchall()]
        return _clip("VM EXPERIMENTS\n"+("\n".join(f"#{x['experiment_id']} {x['source']}: {x['name']} [{x['result']}]" for x in rows) or "None."))
    if cmd=="experimentstart":
        if len(args)<4:return "Usage: /experimentstart <source> <metric/domain> <baseline> <name...>"
        source,metric,baseline=args[:3];name=" ".join(args[3:]).strip()
        st=s.get("autonomy",{})
        effective=int(st.get("effective_level",st.get("level",0)))
        from .experiment_governance_v5 import ExperimentGovernance
        decision=ExperimentGovernance(_store(root)).evaluate(metric,s.get("reliability",{}),effective)
        if not decision["allowed"]:
            return f"Experiment start blocked: {decision['reason']}. Domain={metric}; effective autonomy=L{effective}."
        from .policy_kernel_v6 import PolicyKernel
        caps=s.get("capability_trust_v5",{}).get("capabilities",[])
        cap=next((x for x in caps if x.get("capability")=="certified_experiment"),None)
        kernel=PolicyKernel(_store(root)).evaluate(action_key="certified_experiment",capability="certified_experiment",
            requested_level=int(st.get("requested_level",st.get("level",effective))),effective_level=effective,capability_record=cap,
            risk="low",evidence_quality=float(s.get("evidence_v6",{}).get("score",0)),rollback_ready=True,
            backup_ready=bool(s.get("disaster_recovery_v6",{}).get("latest_backup")),
            security_score=float(s.get("security",{}).get("score",0)),
            reliability_freeze=bool(s.get("reliability",{}).get("experiment_freeze_recommended")),mode="experiment")
        if kernel["decision"]!="ALLOW_EXPERIMENT":
            return f"Experiment start blocked by v6 policy kernel: {kernel['decision']} ({', '.join(kernel['reasons'])})."
        try:
            baseline=float(baseline)
            store=store or _store(root)
            eid=store.create_experiment(name=name,source=source,
                hypothesis=f"Evaluate whether {name} improves {metric} for {source}.",
                metric=metric,baseline=baseline)
            return f"Experiment #{eid} started in certified domain {metric}. Automatic production promotion remains disabled."
        except Exception as exc:return f"Experiment start rejected: {exc}"
    if cmd=="experimentfinish":
        if len(args)<3:return "Usage: /experimentfinish <id> win|loss|neutral|invalid <candidate> [notes...]"
        try:
            eid=int(args[0]);result=args[1].lower();candidate=float(args[2]);notes=" ".join(args[3:])
            store=store or _store(root)
            store.finish_experiment(eid,result=result,candidate=candidate,notes=notes)
            return f"Experiment #{eid} completed as {result} with candidate={candidate}. Improvement ledger updates on the next Brain cycle."
        except Exception as exc:return f"Experiment finish rejected: {exc}"
    if cmd=="learning":
        return _clip("VM LEARNING\n"+("\n".join(f"{x['source']}: {x['name']} -> {x['result']} | {x['lesson']}" for x in s["lessons"][:15]) or "No completed experiment lessons yet."))
    if cmd=="causal":
        return _clip("VM CAUSAL EVIDENCE\n"+("\n".join(f"{x['source']} [{x['confidence']}] {x['name']}: {x['result']}" for x in s["causal_evidence"][:20]) or "No experiment/release evidence yet."))
    if cmd=="what_changed":
        store=store or _store(root)
        with store.connect() as con:rows=[dict(r) for r in con.execute("SELECT * FROM release_events ORDER BY detected_at_utc DESC LIMIT 12").fetchall()]
        return _clip("VM CHANGES\n"+("\n".join(f"{x['detected_at_utc'][:19]} {x['source']} {x.get('previous_version') or '?'} -> {x.get('version') or '?'} [{x['status']}]" for x in rows) or "No source changes recorded yet."))
    if cmd=="testing":
        t=s["testing_intelligence"]
        return _clip("VM TEST INTELLIGENCE\nImpact suites: "+str(len(t["impact_suites"]))+
                     "\nRegression proposals: "+str(len(t["regression_test_proposals"]))+
                     ("\n"+"\n".join(x["title"] for x in t["regression_test_proposals"][:10]) if t["regression_test_proposals"] else ""))
    if cmd=="autopsy":
        return _clip("VM AUTOPSY / POSTMORTEMS\n"+("\n".join(
            f"#{x['incident_id']} {x['source']}: {x['probable_cause']} | prevention: {x['prevention']}"
            for x in s["postmortems"][:10]) or "No high-severity postmortem required."))
    if cmd=="meta":
        m=s["meta_intelligence"]
        return _clip(f"VM META-INTELLIGENCE\nSelf health: {m['self_health']}\nCycles 7d: {m['cycles_7d']}\nReliability: {m['cycle_reliability_pct']}%\nAvg cycle: {m['avg_cycle_ms']} ms\nMetric sources: {m['max_metric_sources']}")
    if cmd=="twin":
        t=s["digital_twin"]
        return _clip(f"VM DIGITAL TWIN\nNodes: {len(t['nodes'])}\nEdges: {len(t['edges'])}\n{t['note']}")
    if cmd=="cost":
        c=s["cost_intelligence"]
        return _clip(f"VM COST INTELLIGENCE\nConfigured: {c['configured']}\nEstimated cost: {c['total_estimated_cost']}\n{c['note']}")
    if cmd=="intelfeedback":
        if len(args)<2:return "Usage: /intelfeedback <incident_id> useful|noise [details]"
        try:incident_id=int(args[0])
        except Exception:return "Incident ID must be an integer."
        verdict=args[1].strip().lower()
        if verdict not in {"useful","noise"}:return "Verdict must be useful or noise."
        details=" ".join(args[2:]).strip()
        from datetime import datetime,timezone
        store=store or _store(root)
        with store.connect() as con:
            exists=con.execute("SELECT 1 FROM incidents WHERE incident_id=?",(incident_id,)).fetchone()
            if not exists:return f"Incident #{incident_id} was not found."
            con.execute("""INSERT INTO intelligence_feedback(incident_id,verdict,details,created_at_utc)
                VALUES(?,?,?,?)""",(incident_id,verdict,details,datetime.now(timezone.utc).isoformat()))
        return f"Recorded Intelligence feedback for incident #{incident_id}: {verdict}."
    if cmd=="registry":
        rows=s.get("platform_registry") or s["runtime_registry"]
        return _clip("VM AUTHORITATIVE PLATFORM REGISTRY\n"+("\n".join(
            f"{x.get('service')}: managed={x.get('managed')} owner={x.get('owner',x.get('service'))} health={x.get('health_provider','n/a')} root={x.get('canonical_root')}" for x in rows) or "Empty."))
    if cmd=="configreg":
        rows=s.get("config_registry",[])
        return _clip("VM CONFIG REGISTRY (HASH-ONLY)\n"+("\n".join(
            f"{x.get('service')}: {x.get('role')} secret={bool(x.get('secret_bearing'))} exists={x.get('exists')} {x.get('path')}"
            for x in rows[:30]) or "Empty."))
    if cmd=="drift":
        n=s["platform_normalization"]
        return _clip(f"VM PLATFORM NORMALISATION\nScore: {n['score']}/100\n"+("\n".join(
            f"[{x['severity'].upper()}] {x['service']}: {x['title']}" for x in n['violations']) or "No architecture violations."))
    if cmd in {"slo","errorbudget"}:
        r=s["reliability"]
        lines=[f"Compliance: {r['compliance_pct']}% | Breaches: {r['breaches']} | Max burn: {r.get('historical',{}).get('max_burn_rate','n/a')}x"]
        lines += [f"{x['status'].upper()} {x['service']} {x['metric']}={x['actual']} target {x['operator']} {x['target']} budget={x['error_budget_remaining_pct']}% burn={x.get('burn_rate','n/a')}x" for x in r['slos']]
        return _clip(("VM SLO STATUS\n" if cmd=="slo" else "VM ERROR BUDGETS\n")+"\n".join(lines))
    if cmd=="reliability":
        h=s["reliability"].get("historical",{})
        rows=h.get("service_stats",[])
        lines=[f"Max burn: {h.get('max_burn_rate',0)}x | Exhausted budgets: {h.get('error_budgets_exhausted',0)}"]
        lines += [f"{x['service']}: incidents30d={x.get('incidents_30d',0)} recur={x.get('recurrences_30d',0)} MTTR={x.get('mttr_seconds')}s MTBF={x.get('mtbf_seconds')}s SLO={x.get('slo_compliance_pct')}%" for x in rows]
        return _clip("VM RELIABILITY ENGINEERING\n"+"\n".join(lines))
    if cmd=="objective":
        return _clip("VM OBJECTIVES\n"+"\n".join(
            f"{x['status'].upper()} {x['score']}/100 {x['title']} | next={(x['plan'][0]['action'] if x['plan'] else 'none')}" for x in s['objectives']))
    if cmd=="autonomy":
        from .autonomy import AutonomyController, LEVELS
        ctl=AutonomyController(_store(root))
        if args:
            raw=args[0].strip().lower()
            aliases={v:k for k,v in LEVELS.items()};aliases.update({"off":0,"on":4,"objective":7,"optimize":6,"optimise":6})
            try:
                level=int(raw) if raw.lstrip("-").isdigit() else aliases[raw]
                state=ctl.set_level(level,"Telegram administrator request")
                suffix=" Planning may operate at L7; production execution remains capability-certified." if level>=5 else ""
                return f"Requested autonomy set to L{state['level']} {state['level_name']}.{suffix}"
            except Exception as exc:return f"Autonomy update rejected: {exc}"
        st=s['autonomy'];return (f"VM AUTONOMY\nRequested: L{st.get('requested_level',st['level'])} ({st['level_name']})\n"
            f"Effective: L{st.get('effective_level',st['level'])} ({st.get('effective_level_name',st['level_name'])})\nReason: {st['reason']}")
    if cmd=="safe":
        from .autonomy import AutonomyController
        ctl=AutonomyController(_store(root));raw=(args[0].lower() if args else "status")
        if raw in {"on","enable","1"}:
            st=ctl.freeze(24,"Telegram administrator safe mode")
            return f"Safe mode enabled until {st['freeze_until_utc']}. Recovery remains allowed; experiments/optimisation are frozen."
        if raw in {"off","disable","0"}:
            ctl.unfreeze();return "Safe mode cleared."
        st=s['autonomy'];return f"VM SAFE MODE\nFreeze until: {st.get('freeze_until_utc') or 'not active'}\nReliability freeze: {st.get('reliability_freeze',False)}"
    if cmd=="whyact":
        from .ask import AskEngine
        return _clip("VM WHY DIDN'T YOU ACT?\n"+AskEngine(_brain(root)).answer("why didn't you act")["answer"])
    if cmd=="runbooks":
        rb=s['runbooks'];return _clip("VM RUNBOOKS\n"+"\n".join(
            f"{x['key']} minL{x['minimum_autonomy']} automatic={x['automatic']}" for x in rb['catalog']))
    if cmd=="runbooktrust":
        rows=s["reliability"].get("historical",{}).get("runbook_trust",[])
        return _clip("VM RUNBOOK TRUST\n"+("\n".join(
            f"{x['runbook_key']}: trust={x['trust_score']} cert={x['certification']} attempts={x['attempts']} success={x['success_rate_pct']}%"
            for x in rows) or "No runbook execution evidence yet."))
    if cmd=="impact":
        return _clip(f"VM DEPENDENCY GRAPH\nEdges: {len(s['dependency_graph'])}\n"+"\n".join(
            f"{x['source']} -> {x['target']}" for x in s['dependency_graph'][:20]))
    if cmd=="releasegate":
        g=s.get('release_gate')
        if not g:return "VM RELEASE GATE\nNo release candidate currently awaiting evaluation."
        return _clip(f"VM RELEASE GATE\nDecision: {g.get('decision')}\nScore delta: {g.get('score_delta')}\nReasons: {', '.join(g.get('reasons') or []) or 'none'}")
    if cmd=="attention":
        a=s['attention_budget'];return _clip(
            f"VM ATTENTION BUDGET\nUseful: {a['useful']} | Noise: {a['noise']} | Noise ratio: {a['noise_ratio']:.1%}\n"
            f"Automatic decisions: {a['automatic_decisions']}\nEstimated minutes saved: {a['estimated_minutes_saved']}")
    if cmd=="plan":
        p=s.get("strategic_planner_v5",{})
        return _clip("VM v6 STRATEGIC PLAN\n"+("\n".join(
            f"{x['priority']} {'EXEC' if x['allowed'] else 'BLOCK'} {x['title']} | {x['action_key']} requires L{x['authority_required']}"
            for x in p.get("backlog",[])[:20]) or "No strategic backlog."))
    if cmd=="captrust":
        rows=s.get("capability_trust_v5",{}).get("capabilities",[])
        return _clip("VM CAPABILITY TRUST\n"+("\n".join(
            f"{x['capability']}: {x['certification']} trust={x['trust_score']} effective=L{x['effective_level']} attempts={x['attempts']}"
            for x in rows) or "No capability trust evidence."))
    if cmd=="failurefamilies":
        rows=s.get("root_cause_v5",{}).get("failure_families",[])
        return _clip("VM FAILURE FAMILIES\n"+("\n".join(
            f"{x['source']}: {x['title']} incidents={x['incident_count']} recurrence={x['recurrence_count']}"
            for x in rows[:20]) or "No clustered failure families."))
    if cmd=="engineering":
        rows=s.get("engineering_v5",[])
        return _clip("VM ISOLATED ENGINEERING CANDIDATES\n"+("\n".join(
            f"{x['candidate_key']}: {x['title']} target={x['targeted_status']} full={x['full_status']} security={x['security_status']} production_mutation={bool(x['production_mutation'])}"
            for x in rows[:15]) or "No engineering candidates."))
    if cmd=="releaseintel":
        g=s.get("release_intelligence_v5",{})
        return _clip(f"VM RELEASE INTELLIGENCE\nGate: {g.get('gate_status')} | risk={g.get('risk_score')} | confidence={g.get('confidence')}\n"
                     f"Blast radius: {', '.join(g.get('blast_radius',[])) or 'none'}\n"
                     f"Tests: {', '.join(g.get('selected_test_suites',[])) or 'none'}\nAutomatic promotion: {g.get('automatic_promotion',False)}")
    if cmd=="truth":
        e=s.get("evidence_v6",{})
        return _clip(f"VM EVIDENCE/TRUTH LAYER\nQuality: {e.get('score')} / 100 | grade={e.get('grade')} | coverage={e.get('coverage_pct')}% | authority_cap={e.get('authority_cap')} | stale/invalid={e.get('stale_or_invalid')}\n"+
                     ("\n".join(f"{x['freshness']} {x['claim_key']} confidence={x['confidence']:.0%} via {x['provenance']}" for x in e.get('records',[])[:20]) or "No evidence records."))
    if cmd=="policy":
        p=s.get("policy_kernel_v6",{})
        return _clip("VM v6 POLICY KERNEL\n"+("\n".join(
            f"{x['decision']} {x['action_key']} risk={x['risk']} evidence={x['evidence_quality']}/100 | {', '.join(x['reasons'])}"
            for x in p.get('previews',[])[:20]) or "No current strategic action previews."))
    if cmd=="intervention":
        rows=s.get("intervention_learning_v6",{}).get("actions",[])
        return _clip("VM INTERVENTION LEARNING\n"+("\n".join(
            f"{x['action_key']}: immediate={x['immediate_success_pct']}% root-cause={x['root_cause_success_pct']}% recurrence7d={x['recurrence_7d_pct']}%"
            for x in rows[:20]) or "No intervention outcomes yet."))
    if cmd=="runbookfactory":
        r=s.get("runbook_factory_v6",{})
        return _clip("VM RUNBOOK FACTORY\n"+("\n".join(
            f"{x['runbook_key']} v{x['version']} {x['status']} sim={x['simulation_status']} shadow={x['shadow_status']}"
            for x in r.get('revisions',[])[:20]) or "No generated revisions yet."))
    if cmd=="dr":
        d=s.get("disaster_recovery_v6",{})
        return _clip(f"VM DISASTER RECOVERY\nLatest backup: {d.get('latest_backup')}\nAge: {d.get('latest_backup_age_minutes')} min\n"
                     f"Restore confidence: {d.get('restore_confidence_pct')}% | drill_age={d.get('last_verified_restore_age_days')}d | RPO={d.get('rpo_minutes')}m | RTO={d.get('rto_seconds')}s | drill_due={d.get('drill_due')}\n"
                     f"Automatic destructive restore: {d.get('automatic_destructive_restore',False)}")
    if cmd=="horizons":
        h=s.get("strategic_operator_v6",{}).get("horizons",{})
        return _clip("VM STRATEGIC HORIZONS\n"+"\n".join(f"{k}: {len(v)} item(s) | allowed={sum(1 for x in v if x.get('execution_allowed'))}" for k,v in h.items()))
    if cmd=="modernize":
        rows=s.get("architecture_modernization_v6",{}).get("candidates",[])
        return _clip("VM ARCHITECTURE MODERNISATION\n"+("\n".join(
            f"{x['service']}: {x['title']} | isolated={x['isolated_only']} production_mutation={x['production_mutation']}"
            for x in rows[:20]) or "No modernisation candidates."))
    if cmd=="simulate":
        if not args:return "Usage: /simulate <action>"
        r=SimulationEngine().simulate(" ".join(args),s["integrated"])
        return _clip("VM SIMULATION\n"+"\n".join(f"{k}: {v}" for k,v in r.items()))
    if cmd=="askvm":
        if not args:return "Usage: /askvm <question>"
        return _clip("ASK VM\n"+AskEngine(_brain(root)).answer(" ".join(args))["answer"])
    return "Unknown VM Intelligence command."
