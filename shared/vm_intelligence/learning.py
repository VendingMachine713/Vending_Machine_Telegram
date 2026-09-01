from __future__ import annotations
from typing import Any

class LearningEngine:
    """Outcome-based learning over completed experiments."""
    def __init__(self, store):
        self.store = store

    def lessons(self) -> list[dict[str, Any]]:
        with self.store.connect() as con:
            rows = con.execute(
                "SELECT * FROM experiments WHERE result != 'pending' ORDER BY updated_at_utc DESC"
            ).fetchall()
        lessons = []
        for r in rows:
            before, after = r["baseline"], r["candidate"]
            delta = None
            if before is not None and after is not None:
                delta = round(after - before, 12)
            lessons.append({
                "experiment_id": r["experiment_id"], "source": r["source"],
                "name": r["name"], "hypothesis": r["hypothesis"],
                "metric": r["metric"], "result": r["result"],
                "baseline": before, "candidate": after, "delta": delta,
                "lesson": (
                    "Candidate retained as evidence of improvement."
                    if r["result"] == "win" else
                    "Candidate should not become the default."
                    if r["result"] == "loss" else
                    "Experiment did not establish a clear improvement."
                )
            })
        return lessons
