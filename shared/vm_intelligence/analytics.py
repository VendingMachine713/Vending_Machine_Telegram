from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from statistics import mean, median, pstdev
from typing import Any


class IntelligenceAnalyzer:
    def __init__(self, store):
        self.store = store

    @staticmethod
    def _since(hours: int) -> str:
        return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

    def summary(self, hours: int = 24) -> dict[str, Any]:
        rows = self.store.query_events(since_utc=self._since(hours))
        total = len(rows)
        outcomes = Counter(r["outcome"] for r in rows)
        sources = Counter(r["source"] for r in rows)
        actions = Counter(r["action"] for r in rows)
        durations = [r["duration_ms"] for r in rows if r["duration_ms"] is not None]
        failures = outcomes.get("failure", 0)
        return {
            "window_hours": hours,
            "events": total,
            "successes": outcomes.get("success", 0),
            "failures": failures,
            "failure_rate": round(failures / total, 4) if total else 0.0,
            "sources": dict(sources),
            "top_actions": actions.most_common(10),
            "duration_ms": {
                "count": len(durations),
                "mean": round(mean(durations), 2) if durations else None,
                "median": round(median(durations), 2) if durations else None,
                "max": round(max(durations), 2) if durations else None,
            },
        }

    def source_health(self, hours: int = 24) -> list[dict[str, Any]]:
        rows = self.store.query_events(since_utc=self._since(hours))
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            grouped[row["source"]].append(row)

        result = []
        for source, items in grouped.items():
            total = len(items)
            failures = sum(1 for x in items if x["outcome"] == "failure")
            errors = sum(1 for x in items if x["level"] in {"error", "critical"})
            durations = [x["duration_ms"] for x in items if x["duration_ms"] is not None]
            result.append({
                "source": source,
                "events": total,
                "failures": failures,
                "failure_rate": round(failures / total, 4) if total else 0.0,
                "error_events": errors,
                "avg_duration_ms": round(mean(durations), 2) if durations else None,
            })
        return sorted(result, key=lambda x: (-x["failure_rate"], -x["error_events"], x["source"]))

    def anomalies(self, hours: int = 24) -> list[dict[str, Any]]:
        """Simple explainable anomaly detector; no ML dependency."""
        rows = self.store.query_events(since_utc=self._since(hours))
        by_action: dict[tuple[str, str], list[float]] = defaultdict(list)
        latest: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            key = (row["source"], row["action"])
            latest[key].append(row)
            if row["duration_ms"] is not None:
                by_action[key].append(float(row["duration_ms"]))

        anomalies = []
        for key, values in by_action.items():
            if len(values) < 5:
                continue
            avg = mean(values)
            sd = pstdev(values)
            if sd <= 0:
                continue
            threshold = avg + 2.5 * sd
            high = max(values)
            if high > threshold:
                anomalies.append({
                    "source": key[0],
                    "action": key[1],
                    "type": "latency_spike",
                    "observed_ms": round(high, 2),
                    "baseline_ms": round(avg, 2),
                    "threshold_ms": round(threshold, 2),
                })

        for key, items in latest.items():
            failures = sum(1 for x in items if x["outcome"] == "failure")
            if len(items) >= 5 and failures / len(items) >= 0.30:
                anomalies.append({
                    "source": key[0],
                    "action": key[1],
                    "type": "high_failure_rate",
                    "failure_rate": round(failures / len(items), 4),
                    "events": len(items),
                })
        return anomalies
