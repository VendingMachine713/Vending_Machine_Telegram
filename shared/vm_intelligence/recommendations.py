from __future__ import annotations

import hashlib
import json


class RecommendationEngine:
    def __init__(self, store, analyzer):
        self.store = store
        self.analyzer = analyzer

    @staticmethod
    def _fingerprint(payload: dict) -> str:
        raw = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()[:24]

    def refresh(self, hours: int = 24) -> list[dict]:
        generated = []
        for anomaly in self.analyzer.anomalies(hours=hours):
            if anomaly["type"] == "high_failure_rate":
                severity = "high" if anomaly["failure_rate"] >= 0.50 else "medium"
                title = f"Investigate {anomaly['source']} / {anomaly['action']} failures"
                rationale = (
                    f"Failure rate is {anomaly['failure_rate']:.0%} across "
                    f"{anomaly['events']} recent events. Review the failing path, transient-error "
                    "handling and recent configuration changes."
                )
                category = "reliability"
            else:
                severity = "medium"
                title = f"Investigate latency spike in {anomaly['source']} / {anomaly['action']}"
                rationale = (
                    f"Observed latency {anomaly['observed_ms']} ms exceeds the explainable "
                    f"baseline threshold {anomaly['threshold_ms']} ms."
                )
                category = "performance"

            fp_payload = {
                "source": anomaly["source"],
                "action": anomaly["action"],
                "type": anomaly["type"],
            }
            fp = self._fingerprint(fp_payload)
            self.store.upsert_recommendation(
                source=anomaly["source"],
                category=category,
                severity=severity,
                title=title,
                rationale=rationale,
                evidence=anomaly,
                fingerprint=fp,
            )
            generated.append({"fingerprint": fp, "title": title, "severity": severity})
        return generated
