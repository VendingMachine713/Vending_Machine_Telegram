from __future__ import annotations
from datetime import datetime, timezone, timedelta
from collections import defaultdict

class ForecastEngine:
    """Conservative trend estimator; labels outputs as estimates."""
    def __init__(self, store):
        self.store = store

    def event_volume(self, days: int = 7) -> dict:
        since = (datetime.now(timezone.utc)-timedelta(days=days)).isoformat()
        rows = self.store.query_events(since_utc=since)
        per_day = defaultdict(int)
        for r in rows:
            per_day[r["timestamp_utc"][:10]] += 1
        values = list(per_day.values())
        avg = sum(values)/len(values) if values else 0
        return {
            "basis_days": days, "observed_days": len(values),
            "average_events_per_observed_day": round(avg,2),
            "next_day_estimate": round(avg,2),
            "confidence": "low" if len(values)<4 else "medium",
            "note": "Simple historical-volume estimate; not a guarantee."
        }
