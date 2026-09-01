from __future__ import annotations
from pathlib import Path

from .integrated_schema import ensure_v3_schema
from .v4_schema import ensure_v4_schema
from .v42_schema import ensure_v42_schema
from .v5_schema import ensure_v5_schema
from .v6_schema import ensure_v6_schema
from .analytics import IntelligenceAnalyzer
from .recommendations import RecommendationEngine
from .scoring import ScoreEngine
from .learning import LearningEngine
from .forecasting import ForecastEngine
from .knowledge import KnowledgeInventory
from .incidents import IncidentEngine
from .techdebt import TechnicalDebtScanner
from .improvements import ImprovementLedger
from .adapters import AdapterHub
from .rootcause import RootCauseEngine
from .opportunities import AutomationOpportunityDetector
from .goals import GoalEngine
from .insights import InsightsEngine
from .metrics import MetricStore
from .efficiency import EfficiencyBrain
from .security_intelligence import SecurityBrain
from .config_intelligence import ConfigurationIntelligence
from .code_intelligence import CodeIntelligence
from .testing_intelligence import TestingIntelligence
from .postmortem import PostmortemEngine
from .predictive import PredictiveMaintenance
from .scoreboard import BotScoreboard
from .meta_intelligence import MetaIntelligence
from .capacity import CapacityPlanner
from .digital_twin import DigitalTwin
from .inbox import IntelligenceInbox
from .cto import CTOBrain
from .causal import CausalIntelligence
from .cost_intelligence import CostIntelligence
from .runtime_registry import RuntimeRegistry
from .platform_normalization import PlatformNormalizer
from .reliability import ReliabilityBrain
from .dependency_graph import DependencyGraph
from .autonomy import AutonomyController
from .runbooks import RunbookEngine
from .objectives import ObjectiveEngine
from .attention_budget import AttentionBudget
from .release_gate import ReleaseGate
from .platform_registry import PlatformServiceRegistry
from .config_registry import ConfigRegistry
from .drift_guardian import DriftGuardian
from .reliability_engineering import ReliabilityEngineering
from .root_cause_v5 import RootCauseEngine as RootCauseEngineV5
from .predictive_ops_v5 import PredictiveOperations
from .release_intelligence_v5 import ReleaseIntelligence
from .automation_discovery_v5 import AutomationDiscovery
from .experiment_governance_v5 import ExperimentGovernance
from .capability_trust_v5 import CapabilityTrust
from .engineering_candidate_v5 import EngineeringCandidateManager
from .strategic_planner_v5 import StrategicPlanner
from .evidence_truth_v6 import EvidenceTruthLayer
from .policy_kernel_v6 import PolicyKernel
from .prediction_calibration_v6 import PredictionCalibration
from .intervention_learning_v6 import InterventionLearning
from .runbook_factory_v6 import RunbookFactory
from .attention_governor_v6 import AttentionGovernor
from .disaster_recovery_v6 import DisasterRecoveryController
from .architecture_modernization_v6 import ArchitectureModernizer
from .strategic_operator_v6 import StrategicOperator
from .self_improvement_v6 import SelfImprovementController

class Brain:
    def __init__(self,store,root):
        self.store=store;self.root=Path(root);ensure_v3_schema(store);ensure_v4_schema(store);ensure_v42_schema(store);ensure_v5_schema(store);ensure_v6_schema(store)
        self.analyzer=IntelligenceAnalyzer(store)
        self.recommendations=RecommendationEngine(store,self.analyzer)
        self.scores=ScoreEngine(self.analyzer)
        self.learning=LearningEngine(store)
        self.forecast=ForecastEngine(store)
        self.knowledge=KnowledgeInventory(root)
        self.incident_engine=IncidentEngine(store,self.analyzer)
        self.techdebt=TechnicalDebtScanner(root)
        self.improvements=ImprovementLedger(store)
        self.adapters=AdapterHub(store,self.root)
        self.rootcause=RootCauseEngine(store)
        self.opportunities=AutomationOpportunityDetector(store)
        self.goals=GoalEngine(store)
        self.runtime_registry=RuntimeRegistry(store,self.root)
        self.platform_normalizer=PlatformNormalizer(store,self.root)
        self.reliability=ReliabilityBrain(store)
        self.dependencies=DependencyGraph(store,self.root)
        self.autonomy=AutonomyController(store)
        self.runbooks=RunbookEngine(store)
        self.objectives=ObjectiveEngine(store)
        self.attention=AttentionBudget(store)
        self.release_gate=ReleaseGate(store)
        self.platform_registry=PlatformServiceRegistry(store,self.root)
        self.config_registry=ConfigRegistry(store,self.root)
        self.drift_guardian=DriftGuardian(store,self.root)
        self.reliability_engineering=ReliabilityEngineering(store)
        self.rootcause_v5=RootCauseEngineV5(store)
        self.predictive_v5=PredictiveOperations(store)
        self.release_intelligence_v5=ReleaseIntelligence(store,self.root)
        self.automation_discovery_v5=AutomationDiscovery(store)
        self.experiment_governance_v5=ExperimentGovernance(store)
        self.capability_trust_v5=CapabilityTrust(store)
        self.engineering_v5=EngineeringCandidateManager(store,self.root)
        self.strategic_planner_v5=StrategicPlanner(store)
        self.evidence_v6=EvidenceTruthLayer(store)
        self.policy_v6=PolicyKernel(store)
        self.prediction_calibration_v6=PredictionCalibration(store)
        self.intervention_learning_v6=InterventionLearning(store)
        self.runbook_factory_v6=RunbookFactory(store)
        self.attention_governor_v6=AttentionGovernor(store)
        self.disaster_recovery_v6=DisasterRecoveryController(store,self.root)
        self.architecture_modernization_v6=ArchitectureModernizer(store)
        self.strategic_operator_v6=StrategicOperator(store)
        self.self_improvement_v6=SelfImprovementController()

    def _recent_release_changes(self):
        with self.store.connect() as con:
            return [dict(r) for r in con.execute("""SELECT source,detected_at_utc,previous_version,version,status
                FROM release_events ORDER BY detected_at_utc DESC LIMIT 20""").fetchall()]

    def executive_snapshot(self,hours=24):
        integrated=self.adapters.collect()
        runtime_registry=self.runtime_registry.refresh()
        dependency_edges=self.dependencies.build()
        platform_registry=self.platform_registry.refresh(runtime_registry)
        config_registry=self.config_registry.refresh(platform_registry)
        platform_normalization=self.platform_normalizer.refresh(runtime_registry)
        platform_drift=self.drift_guardian.evaluate(platform_registry,config_registry,platform_normalization)
        self.recommendations.refresh(hours)
        tech=self.techdebt.scan()
        incidents=self.incident_engine.refresh(hours,integrated)
        improvements=self.improvements.sync_experiments()
        root_causes=self.rootcause.refresh(incidents,integrated)
        opportunities=self.opportunities.refresh(incidents,integrated,tech)
        from .security import SecurityPostureEngine
        posture=SecurityPostureEngine(self.root).evaluate(integrated)
        scan_security=SecurityBrain(self.root).analyze(integrated)
        security={**scan_security,
                  "score":min(float(posture.get("score",100)),float(scan_security.get("score",100))),
                  "administrative_posture":posture}
        scorecard=self.scores.scorecard(hours,security_posture=security,integrated=integrated)

        platform=integrated.get("VM_Platform",{}).get("metrics",{})
        intel_metrics=MetricStore(self.store).latest("VM_Intelligence").get("VM_Intelligence",{})
        goals=self.goals.evaluate({
            "overall_score":scorecard["overall"],
            "critical_incidents":sum(1 for x in incidents if x["severity"]=="critical"),
            "managed_services_down":platform.get("managed_services_down"),
            "latest_backup_integrity":intel_metrics.get("latest_backup_integrity"),
            "intelligence_db_integrity":intel_metrics.get("intelligence_db_integrity"),
        })

        recommendations=self.store.open_recommendations()
        insights=InsightsEngine().build(
            scorecard=scorecard,incidents=incidents,recommendations=recommendations,
            opportunities=opportunities,goals=goals,integrated=integrated,techdebt=tech)

        efficiency=EfficiencyBrain().analyze(integrated,tech)
        config_drift=ConfigurationIntelligence(self.store,self.root).refresh()
        code=CodeIntelligence(self.root).build()
        predictive=PredictiveMaintenance(self.store).forecast()
        scoreboard=BotScoreboard().build(integrated)
        meta=MetaIntelligence(self.store).analyze()
        capacity=CapacityPlanner(self.root).snapshot(integrated)
        postmortems=PostmortemEngine(self.store).refresh(incidents,root_causes)
        testing=TestingIntelligence(self.store,self.root).impact_plan(self._recent_release_changes(),incidents)
        causal=CausalIntelligence(self.store).evidence()
        cost=CostIntelligence(self.root).analyze(integrated)
        twin=DigitalTwin().build(integrated,code)
        inbox=IntelligenceInbox().build(
            incidents,recommendations,goals,opportunities,predictive,
            security=security,config_drift=config_drift)
        cto=CTOBrain().prioritize(inbox,scoreboard,tech,efficiency)

        reliability_context={source:data.get("metrics",{}) for source,data in integrated.items()}
        reliability_context["VM_Intelligence"]={
            "overall_score":scorecard["overall"],
            "latest_backup_integrity":intel_metrics.get("latest_backup_integrity"),
            "intelligence_db_integrity":intel_metrics.get("intelligence_db_integrity"),
        }
        reliability=self.reliability.evaluate(reliability_context)
        reliability_engineering=self.reliability_engineering.evaluate(reliability,integrated)
        # Historical burn/recurrence can tighten the freeze; it never loosens the base safety decision.
        reliability["historical"]=reliability_engineering
        reliability["experiment_freeze_recommended"]=bool(
            reliability.get("experiment_freeze_recommended") or reliability_engineering.get("experiment_freeze_recommended")
        )
        attention=self.attention.snapshot()
        objective_context={
            "critical_incidents":sum(1 for x in incidents if x["severity"]=="critical"),
            "managed_services_down":platform.get("managed_services_down") or 0,
            "backup_integrity":intel_metrics.get("latest_backup_integrity"),
            "security_score":security.get("score"),
            "noise_ratio":attention.get("noise_ratio",0.0),
        }
        objectives=self.objectives.evaluate(objective_context)
        autonomy=self.autonomy.effective_level(reliability["experiment_freeze_recommended"])
        objectives=self.objectives.bind_authority(
            objectives,self.autonomy,
            backup_available=bool(objective_context.get("backup_integrity")),
            reliability_freeze=bool(reliability["experiment_freeze_recommended"]),
        )
        release_gate=self.release_gate.refresh_latest(
            scorecard["overall"],objective_context["critical_incidents"],reliability["breaches"]
        )
        runbooks={"catalog":self.runbooks.catalog(),"stats":self.runbooks.stats()}

        # v4.3-v4.9 accumulated Intelligence layers.
        root_cause_v5=self.rootcause_v5.analyze(max(168,hours))
        predictive_v5=self.predictive_v5.forecast(integrated)
        automation_discovery_v5=self.automation_discovery_v5.discover(30)
        capability_trust_v5=self.capability_trust_v5.snapshot(autonomy.get("effective_level",4))
        engineering_v5=self.engineering_v5.list()
        # Release Intelligence evaluates the current observed platform as a no-change baseline.
        release_intelligence_v5=self.release_intelligence_v5.gate(
            "observed-current",
            [],
            dependency_edges,
            baseline={"overall_score":scorecard["overall"],
                      "slo_compliance_pct":reliability.get("compliance_pct",0),
                      "security_score":security.get("score",0)},
            observed={"overall_score":scorecard["overall"],
                      "slo_compliance_pct":reliability.get("compliance_pct",0),
                      "security_score":security.get("score",0)},
        )

        preplan={
            "scorecard":scorecard,"platform_drift":platform_drift,"reliability":reliability,
            "predictive_v5":predictive_v5,"automation_discovery_v5":automation_discovery_v5,
            "engineering_v5":engineering_v5,"attention_budget":attention,
        }
        strategic_planner_v5=self.strategic_planner_v5.compile(
            preplan,objectives,capability_trust_v5
        )

        # v6 closed-loop governance and self-improvement layers.
        evidence_v6=self.evidence_v6.assess(integrated)
        prediction_calibration_v6=self.prediction_calibration_v6.evaluate_due()
        intervention_learning_v6=self.intervention_learning_v6.summarize()
        runbook_factory_v6=self.runbook_factory_v6.refresh(
            automation_discovery_v5.get("candidates",[]),
            reliability_engineering.get("runbook_trust",[]),
        )
        attention_governor_v6=self.attention_governor_v6.snapshot(attention)
        disaster_recovery_v6=self.disaster_recovery_v6.snapshot()
        architecture_modernization_v6=self.architecture_modernization_v6.propose(
            platform_normalization,platform_registry
        )
        self_improvement_v6=self.self_improvement_v6.build(
            intervention_learning_v6,runbook_factory_v6,prediction_calibration_v6,architecture_modernization_v6
        )
        # Policy-kernel preview for every currently proposed strategic action. Planning remains L7;
        # execution is independently evaluated and never inherited from planner authority.
        cap_by_key={x.get("capability"):x for x in capability_trust_v5.get("capabilities",[])}
        policy_previews=[]
        for item in strategic_planner_v5.get("backlog",[]):
            action=item.get("action_key") or "objective_planning"
            cap=cap_by_key.get(action)
            policy_previews.append(self.policy_v6.evaluate(
                action_key=action,capability=action,
                requested_level=7,effective_level=int(autonomy.get("effective_level",4)),
                capability_record=cap,risk="medium" if float(item.get("risk",0))>=3 else "low",
                evidence_quality=float(evidence_v6.get("score",0)),
                rollback_ready=True,backup_ready=bool(objective_context.get("backup_integrity")),
                security_score=float(security.get("score",0)),
                reliability_freeze=bool(reliability.get("experiment_freeze_recommended")),
                mode="production",record=False,
            ))
        strategic_operator_v6=self.strategic_operator_v6.build(
            strategic_planner_v5,
            {"security_score":security.get("score"),
             "reliability_freeze":reliability.get("experiment_freeze_recommended"),
             "evidence_quality":evidence_v6.get("score")},
            policy_previews,
        )

        return {
            "scorecard":scorecard,
            "runtime_registry":runtime_registry,
            "platform_registry":platform_registry,
            "config_registry":config_registry,
            "platform_normalization":platform_normalization,
            "platform_drift":platform_drift,
            "dependency_graph":dependency_edges,
            "reliability":reliability,
            "objectives":objectives,
            "autonomy":autonomy,
            "runbooks":runbooks,
            "attention_budget":attention,
            "release_gate":release_gate,
            "root_cause_v5":root_cause_v5,
            "predictive_v5":predictive_v5,
            "release_intelligence_v5":release_intelligence_v5,
            "automation_discovery_v5":automation_discovery_v5,
            "capability_trust_v5":capability_trust_v5,
            "engineering_v5":engineering_v5,
            "strategic_planner_v5":strategic_planner_v5,
            "evidence_v6":evidence_v6,
            "policy_kernel_v6":{"previews":policy_previews,"forbidden":sorted(__import__('shared.vm_intelligence.policy_kernel_v6',fromlist=['FORBIDDEN']).FORBIDDEN)},
            "prediction_calibration_v6":prediction_calibration_v6,
            "intervention_learning_v6":intervention_learning_v6,
            "runbook_factory_v6":runbook_factory_v6,
            "attention_governor_v6":attention_governor_v6,
            "disaster_recovery_v6":disaster_recovery_v6,
            "architecture_modernization_v6":architecture_modernization_v6,
            "strategic_operator_v6":strategic_operator_v6,
            "self_improvement_v6":self_improvement_v6,
            "security_posture":posture,
            "summary":self.analyzer.summary(hours),
            "health":self.analyzer.source_health(hours),
            "integrated":integrated,
            "anomalies":self.analyzer.anomalies(hours),
            "incidents":incidents,
            "root_causes":root_causes,
            "postmortems":postmortems,
            "recommendations":recommendations,
            "lessons":self.learning.lessons()[:20],
            "improvements":improvements[:20],
            "automation_opportunities":opportunities[:20],
            "efficiency":efficiency,
            "security":security,
            "configuration_drift":config_drift,
            "code_intelligence":code,
            "testing_intelligence":testing,
            "predictive_maintenance":predictive,
            "bot_scoreboard":scoreboard,
            "meta_intelligence":meta,
            "capacity":capacity,
            "causal_evidence":causal,
            "cost_intelligence":cost,
            "digital_twin":twin,
            "goals":goals,
            "insights":insights,
            "inbox":inbox,
            "cto_priorities":cto,
            "forecast":self.forecast.event_volume(),
            "inventory":self.knowledge.snapshot(),
            "technical_debt":tech,
        }
