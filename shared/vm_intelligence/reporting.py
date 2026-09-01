from __future__ import annotations
from datetime import datetime,timezone
from pathlib import Path
import json
from .brain import Brain

def build_report(store,analyzer=None,recommendation_engine=None,*,hours=24,root=None):
    if root is None:
        db=Path(store.db_path).resolve()
        # Production uses <project>/state/vm_intelligence.sqlite3; standalone/test stores
        # must remain rooted in their own parent rather than accidentally escaping upward.
        root=db.parent.parent if db.parent.name.lower()=="state" else db.parent
    return {"schema_version":12,"generated_at_utc":datetime.now(timezone.utc).isoformat(),
            **Brain(store,root).executive_snapshot(hours)}

def _v(v,suffix=""):
    if v is None:return "n/a"
    if isinstance(v,float):return f"{v:.1f}{suffix}"
    return f"{v}{suffix}"

def write_report(report,output_dir):
    output=Path(output_dir);output.mkdir(parents=True,exist_ok=True)
    jp=output/"intelligence_report.json";tp=output/"intelligence_report.txt"
    jp.write_text(json.dumps(report,indent=2,default=str),encoding="utf-8")
    sc=report["scorecard"];s=report["summary"]
    high=[x for x in report["incidents"] if x["severity"] in {"critical","high"}]
    priority=[x for x in report["inbox"] if x["priority"] in {"P0","P1"}]

    lines=["="*78,"VM INTELLIGENCE v6 SELF-IMPROVING AUTONOMOUS PLATFORM REPORT","="*78,
        f"Generated: {report['generated_at_utc']}",
        f"Overall score: {sc['overall']}/100",
        f"Reliability {sc['reliability']} | Performance {sc['performance']} | Automation {sc['automation']} | Data {sc['data_quality']}",
        f"Security intelligence: {report['security']['score']}/100",
        f"Events {s['events']} | Failures {s['failures']} ({s['failure_rate']:.1%})",
        f"Open incidents {len(report['incidents'])} | High/critical {len(high)}",
        f"Automation opportunities {len(report['automation_opportunities'])} | Goals missed {sum(1 for g in report['goals'] if g['status']=='missed')}",
        f"Meta self-health: {report['meta_intelligence']['self_health']}",
        f"SLO compliance: {report['reliability']['compliance_pct']}% | breaches {report['reliability']['breaches']}",
        f"Autonomy: requested L{report['autonomy'].get('requested_level',report['autonomy']['level'])} / effective L{report['autonomy'].get('effective_level',report['autonomy']['level'])} {report['autonomy'].get('effective_level_name',report['autonomy']['level_name'])}",
        f"Architecture hygiene: {report['platform_normalization']['score']}/100",
        f"Platform drift: {report['platform_drift']['score']}/100",
        f"Reliability burn max: {report['reliability']['historical']['max_burn_rate']}x",
        f"Strategic backlog: {len(report['strategic_planner_v5']['backlog'])} | executable {report['strategic_planner_v5']['executable_count']} | blocked {report['strategic_planner_v5']['blocked_count']}",
        f"Evidence quality: {report['evidence_v6']['score']}/100 grade={report['evidence_v6'].get('grade')} coverage={report['evidence_v6'].get('coverage_pct')}% | stale/invalid {report['evidence_v6']['stale_or_invalid']}",
        f"DR restore confidence: {report['disaster_recovery_v6']['restore_confidence_pct']}% | drill age={report['disaster_recovery_v6'].get('last_verified_restore_age_days')}d | due={report['disaster_recovery_v6']['drill_due']}",
        "","OBJECTIVES","-"*78]
    lines += [f"{x['status'].upper():<8} {x['score']:>5.1f}/100 {x['title']}" for x in report['objectives']] or ["None."]
    lines += ["","SLO / ERROR BUDGET","-"*78]
    lines += [f"{x['status'].upper():<8} {x['service']} {x['metric']}={x['actual']} target {x['operator']} {x['target']} budget={x['error_budget_remaining_pct']}%" for x in report['reliability']['slos']] or ["None."]
    lines += ["","PLATFORM NORMALISATION / DRIFT","-"*78]
    lines += [f"[{x['severity'].upper()}] {x['service']}: {x['title']}" for x in report['platform_drift']['findings']] or ["No architecture drift findings."]
    lines += ["","RELIABILITY ENGINEERING","-"*78]
    lines += [f"{x['service']}: incidents30d={x.get('incidents_30d',0)} recurrences={x.get('recurrences_30d',0)} MTTR={x.get('mttr_seconds')}s MTBF={x.get('mtbf_seconds')}s SLO={x.get('slo_compliance_pct')}%"
              for x in report['reliability']['historical']['service_stats']] or ["No historical service reliability evidence yet."]
    lines += ["Runbook trust:"]
    lines += [f"{x['runbook_key']}: trust={x['trust_score']} certification={x['certification']} attempts={x['attempts']} success={x['success_rate_pct']}%"
              for x in report['reliability']['historical']['runbook_trust']] or ["No runbook execution history yet."]
    lines += ["","V5 STRATEGIC PLAN","-"*78]
    lines += [f"{x['priority']} {'EXEC' if x['allowed'] else 'BLOCK'} {x['title']} | action={x['action_key']} L{x['authority_required']} confidence={x['confidence']:.0%}"
              for x in report["strategic_planner_v5"]["backlog"]] or ["No strategic backlog."]
    lines += ["","V5 PREDICTIVE PREVENTION","-"*78]
    lines += [f"{x['status'].upper()} {x['source']} {x['metric']} p={x.get('probability')} predicted={x.get('predicted_value')} confidence={x.get('confidence')}"
              for x in report["predictive_v5"]["predictions"]] or ["No predictive evidence."]
    lines += ["","V5 FAILURE FAMILIES","-"*78]
    lines += [f"{x['source']}: {x['title']} incidents={x['incident_count']} recurrences={x['recurrence_count']}"
              for x in report["root_cause_v5"]["failure_families"]] or ["No failure families."]
    lines += ["","V5 CAPABILITY TRUST","-"*78]
    lines += [f"{x['capability']}: {x['certification']} trust={x['trust_score']} effective=L{x['effective_level']}"
              for x in report["capability_trust_v5"]["capabilities"]] or ["No capability trust records."]
    lines += ["","V5 SHADOW AUTOMATION","-"*78]
    lines += [f"{x['title']} frequency={x['frequency']} saved={x['estimated_minutes_saved']}m confidence={x['confidence']:.0%}"
              for x in report["automation_discovery_v5"]["candidates"]] or ["No repeated workflow candidates."]
    lines += ["","V6 POLICY KERNEL","-"*78]
    lines += [f"{x['decision']} {x['action_key']} evidence={x['evidence_quality']}/100 risk={x['risk']} reasons={','.join(x['reasons'])}" for x in report['policy_kernel_v6']['previews']] or ["No strategic action previews."]
    lines += ["","V6 STRATEGIC HORIZONS","-"*78]
    for horizon,rows in report['strategic_operator_v6']['horizons'].items():
        lines.append(f"{horizon}: {len(rows)} planned item(s)")
    lines += ["","V6 INTERVENTION LEARNING","-"*78]
    lines += [f"{x['action_key']}: immediate={x['immediate_success_pct']}% root_cause={x['root_cause_success_pct']}% recur7d={x['recurrence_7d_pct']}%" for x in report['intervention_learning_v6']['actions']] or ["No intervention outcome history yet."]
    lines += ["","V6 RUNBOOK FACTORY","-"*78]
    lines += [f"{x['runbook_key']} v{x['version']} {x['status']} sim={x['simulation_status']} shadow={x['shadow_status']}" for x in report['runbook_factory_v6']['revisions'][:20]] or ["No generated runbook revisions yet."]
    lines += ["","V6 ARCHITECTURE MODERNISATION","-"*78]
    lines += [f"{x['service']}: {x['title']} isolated={x['isolated_only']} production_mutation={x['production_mutation']}" for x in report['architecture_modernization_v6']['candidates']] or ["No modernisation candidates."]
    lines += ["","BOT PERFORMANCE LEAGUE","-"*78]
    lines += [f"{x['score']:>5.1f}/100 {x['source']}" for x in report["bot_scoreboard"]] or ["No bot metrics."]
    lines += ["","OPEN INCIDENTS","-"*78]
    lines += [f"[{x['severity'].upper()}] {x['title']} (x{x['occurrences']})" for x in report["incidents"]] or ["None."]
    lines += ["","ROOT CAUSE","-"*78]
    lines += [f"{x['source']} ({x['confidence']:.0%}): {x['probable_cause']}" for x in report["root_causes"]] or ["No active root-cause reports."]
    lines += ["","PREDICTIVE MAINTENANCE","-"*78]
    lines += [f"[{x['severity'].upper()}] {x['source']} {x['metric']} latest={x['latest']} threshold={x['threshold']} confidence={x['confidence']}" for x in report["predictive_maintenance"]] or ["No threshold risk predicted from current history."]
    lines += ["","TOP CTO PRIORITIES","-"*78]
    lines += [f"{x['priority_score']:>5} {x['source']}: {x['title']} ({x['reason']})" for x in report["cto_priorities"][:10]] or ["None."]
    lines += ["","EFFICIENCY","-"*78]
    lines += [f"{x['score']:>3} {x['source']}: {x['title']}" for x in report["efficiency"]] or ["No material efficiency issue detected."]
    lines += ["","OPERATIONAL GOALS","-"*78]
    lines += [f"{g['status'].upper():<7} {g['title']} | actual={g['actual']} target {g['operator']} {g['target']}" for g in report["goals"]]
    lines += ["","CAPACITY","-"*78,
        f"Disk free: {report['capacity']['disk_free_gib']} GiB / {report['capacity']['disk_total_gib']} GiB",
        f"Known DB size: {report['capacity']['known_database_mib']} MiB",
        report["capacity"]["recommendation"]]
    tp.write_text("\n".join(lines)+"\n",encoding="utf-8")

    attention={
        "generated_at_utc":report["generated_at_utc"],
        "requires_attention":bool(priority),
        "inbox":priority,
        "incidents":high,
        "root_causes":[x for x in report["root_causes"] if any(i["incident_id"]==x["incident_id"] for i in high)],
        "goals_missed":[g for g in report["goals"] if g["status"]=="missed"],
    }
    (output/"intelligence_attention.json").write_text(json.dumps(attention,indent=2,default=str),encoding="utf-8")

    brief=[
        "VM INTELLIGENCE v6 BRIEF",
        f"Overall: {sc['overall']}/100",
        f"SLO compliance: {report['reliability']['compliance_pct']}% | burn max {report['reliability']['historical']['max_burn_rate']}x",
        f"Platform drift: {report['platform_drift']['score']}/100 | findings {sum(report['platform_drift']['counts'].values())}",
        f"Autonomy: requested L{report['autonomy'].get('requested_level',report['autonomy']['level'])} / effective L{report['autonomy'].get('effective_level',report['autonomy']['level'])} {report['autonomy'].get('effective_level_name',report['autonomy']['level_name'])}",
        f"Security: {report['security']['score']}/100",
        f"Open incidents: {len(report['incidents'])} ({len(high)} high/critical)",
        f"Automation opportunities: {len(report['automation_opportunities'])}",
        f"Predicted maintenance risks: {len(report['predictive_maintenance'])}",
        f"Goals missed: {sum(1 for g in report['goals'] if g['status']=='missed')}",
        f"Strategic plan: {len(report['strategic_planner_v5']['backlog'])} items / {report['strategic_planner_v5']['executable_count']} executable",
        f"Evidence quality: {report['evidence_v6']['score']}/100 grade={report['evidence_v6'].get('grade')} authority_cap={report['evidence_v6'].get('authority_cap')}",
        f"Policy previews: {len(report['policy_kernel_v6']['previews'])}",
        f"DR restore confidence: {report['disaster_recovery_v6']['restore_confidence_pct']}%",
        "Top strategic priority: "+(report["strategic_planner_v5"]["backlog"][0]["title"] if report["strategic_planner_v5"]["backlog"] else "None"),
        "USER ACTION: "+("REVIEW HIGH-SEVERITY INBOX" if priority else "None"),
    ]
    (output/"intelligence_brief.txt").write_text("\n".join(brief)+"\n",encoding="utf-8")

    weekly=[
        "VM WEEKLY ENGINEERING REVIEW",
        f"Overall score: {sc['overall']}/100",
        f"Security score: {report['security']['score']}/100",
        f"Observed events: {s['events']}",
        f"Failure rate: {s['failure_rate']:.1%}",
        f"Incidents open: {len(report['incidents'])}",
        f"Improvement ledger records: {len(report['improvements'])}",
        f"Automation opportunities: {len(report['automation_opportunities'])}",
        f"Technical debt score: {report['technical_debt'].get('debt_score','n/a')}",
        f"Intelligence cycle reliability: {report['meta_intelligence']['cycle_reliability_pct']}%",
        f"SLO compliance: {report['reliability']['compliance_pct']}%",
        f"Architecture hygiene: {report['platform_normalization']['score']}/100",
        f"Platform drift score: {report['platform_drift']['score']}/100",
        f"Reliability max burn rate: {report['reliability']['historical']['max_burn_rate']}x",
        f"Attention estimated minutes saved: {report['attention_budget']['estimated_minutes_saved']}",
    ]
    (output/"intelligence_weekly.txt").write_text("\n".join(weekly)+"\n",encoding="utf-8")

    # Structured surfaces for mobile/admin and future visual dashboards.
    artifacts={
        "intelligence_digital_twin.json":report["digital_twin"],
        "intelligence_inbox.json":report["inbox"],
        "intelligence_security.json":report["security"],
        "intelligence_cto.json":report["cto_priorities"],
        "intelligence_postmortems.json":report["postmortems"],
        "intelligence_testing.json":report["testing_intelligence"],
        "intelligence_predictive.json":report["predictive_maintenance"],
        "intelligence_scoreboard.json":report["bot_scoreboard"],
        "intelligence_meta.json":report["meta_intelligence"],
        "intelligence_runtime_registry.json":report["runtime_registry"],
        "intelligence_platform_service_registry.json":report["platform_registry"],
        "intelligence_config_registry.json":report["config_registry"],
        "intelligence_platform_drift.json":report["platform_drift"],
        "intelligence_platform_normalization.json":report["platform_normalization"],
        "intelligence_reliability.json":report["reliability"],
        "intelligence_objectives.json":report["objectives"],
        "intelligence_autonomy.json":report["autonomy"],
        "intelligence_dependency_graph.json":report["dependency_graph"],
        "intelligence_attention_budget.json":report["attention_budget"],
        "intelligence_release_gate.json":report["release_gate"],
        "intelligence_root_cause_v5.json":report["root_cause_v5"],
        "intelligence_predictive_v5.json":report["predictive_v5"],
        "intelligence_release_intelligence_v5.json":report["release_intelligence_v5"],
        "intelligence_automation_discovery_v5.json":report["automation_discovery_v5"],
        "intelligence_capability_trust_v5.json":report["capability_trust_v5"],
        "intelligence_engineering_v5.json":report["engineering_v5"],
        "intelligence_strategic_planner_v5.json":report["strategic_planner_v5"],
        "intelligence_evidence_v6.json":report["evidence_v6"],
        "intelligence_evidence_quality_v6.json":report["evidence_v6"],
        "intelligence_policy_kernel_v6.json":report["policy_kernel_v6"],
        "intelligence_prediction_calibration_v6.json":report["prediction_calibration_v6"],
        "intelligence_intervention_learning_v6.json":report["intervention_learning_v6"],
        "intelligence_intervention_effectiveness_v6.json":report["intervention_learning_v6"],
        "intelligence_runbook_factory_v6.json":report["runbook_factory_v6"],
        "intelligence_runbook_evolution_v6.json":report["runbook_factory_v6"],
        "intelligence_attention_governor_v6.json":report["attention_governor_v6"],
        "intelligence_disaster_recovery_v6.json":report["disaster_recovery_v6"],
        "intelligence_architecture_modernization_v6.json":report["architecture_modernization_v6"],
        "intelligence_strategic_operator_v6.json":report["strategic_operator_v6"],
        "intelligence_self_improvement_v6.json":report["self_improvement_v6"],
    }
    for name,data in artifacts.items():
        (output/name).write_text(json.dumps(data,indent=2,default=str),encoding="utf-8")
    return jp,tp
