from __future__ import annotations
from typing import Any

def clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))

class ScoreEngine:
    """Explainable operational scorecard. It is an indicator, not a security guarantee."""
    def __init__(self, analyzer): self.analyzer=analyzer

    def scorecard(self, hours: int = 24, *, security_posture: dict | None = None,
                  integrated: dict | None = None) -> dict[str, Any]:
        health=self.analyzer.source_health(hours)
        if not health:
            base={"overall":0.0,"reliability":0.0,"performance":0.0,"automation":70.0,
                  "security":float((security_posture or {}).get("score",80.0)),"data_quality":0.0,
                  "explanation":["No telemetry available in selected window."]}
            return base
        total_events=sum(x["events"] for x in health);failures=sum(x["failures"] for x in health)
        failure_rate=failures/total_events if total_events else 1
        reliability=clamp(100-failure_rate*100)
        security=float((security_posture or {}).get("score",100.0))
        if integrated:
            expected=["Smart_Auto_Poster_V2","VM_Relationship_Manager","Universal_Search","VM_Guard","Admin_Command_Centre","VM_Platform"]
            available=sum(1 for x in expected if (integrated.get(x) or {}).get("available"))
            coverage=available/len(expected)
            event_quality=1.0 if total_events>=20 else min(1,total_events/20)
            # Native adapter coverage strengthens confidence, but a backwards-compatible
            # telemetry-only project is not treated as bad data merely because v3 adapters
            # are not applicable there.
            data_quality=clamp(max(event_quality,coverage)*100)
        else:
            data_quality=100.0 if total_events>=20 else clamp(total_events*5)
        latency_vals=[x["avg_duration_ms"] for x in health if x["avg_duration_ms"] is not None]
        avg_latency=sum(latency_vals)/len(latency_vals) if latency_vals else 0
        performance=clamp(100-max(0,avg_latency-250)/50) if latency_vals else 90.0
        if integrated:
            sap=(integrated.get("Smart_Auto_Poster_V2") or {}).get("metrics",{})
            if sap.get("success_rate_24h") is not None:
                performance=min(performance,max(0,float(sap["success_rate_24h"])))
        automation=90.0
        overall=reliability*.35+performance*.20+automation*.15+security*.15+data_quality*.15
        explanation=[f"{total_events} telemetry events evaluated.",f"Observed failure rate: {failure_rate:.1%}."]
        if security_posture is not None:
            explanation.append("Security score is derived from local administrative posture and open high-severity alerts.")
        if integrated:
            explanation.append("Data-quality score includes native adapter coverage across six core platform sources.")
        return {"overall":round(overall,1),"reliability":round(reliability,1),"performance":round(performance,1),
                "automation":automation,"security":round(security,1),"data_quality":round(data_quality,1),
                "explanation":explanation}
