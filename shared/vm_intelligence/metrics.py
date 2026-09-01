from __future__ import annotations
from datetime import datetime, timezone, timedelta
import json

class MetricStore:
    def __init__(self, store):
        self.store = store

    @staticmethod
    def _bucket(minutes: int = 15) -> str:
        now = datetime.now(timezone.utc)
        minute = (now.minute // minutes) * minutes
        return now.replace(minute=minute, second=0, microsecond=0).isoformat()

    def record(self, source: str, metric: str, value, *, unit: str | None = None,
               quality: str = "observed", metadata: dict | None = None) -> None:
        bucket = self._bucket()
        observed = datetime.now(timezone.utc).isoformat()
        numeric = None if value is None else float(value)
        with self.store.connect() as con:
            con.execute("""
                INSERT INTO bot_metrics(bucket_utc,observed_at_utc,source,metric,value,unit,quality,metadata_json)
                VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(source,metric,bucket_utc) DO UPDATE SET
                    observed_at_utc=excluded.observed_at_utc,
                    value=excluded.value,
                    unit=excluded.unit,
                    quality=excluded.quality,
                    metadata_json=excluded.metadata_json
            """, (bucket, observed, source, metric, numeric, unit, quality,
                  json.dumps(metadata or {}, sort_keys=True, default=str)))

    def latest(self, source: str | None = None) -> dict[str, dict[str, float | None]]:
        sql = """
        SELECT m.source,m.metric,m.value
        FROM bot_metrics m
        JOIN (
          SELECT source,metric,MAX(observed_at_utc) latest
          FROM bot_metrics GROUP BY source,metric
        ) x ON x.source=m.source AND x.metric=m.metric AND x.latest=m.observed_at_utc
        """
        args = []
        if source:
            sql += " WHERE m.source=?"
            args.append(source)
        out = {}
        with self.store.connect() as con:
            for r in con.execute(sql, args).fetchall():
                out.setdefault(r["source"], {})[r["metric"]] = r["value"]
        return out

    def history(self, source: str, metric: str, hours: int = 168, limit: int = 1000):
        since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        with self.store.connect() as con:
            return [dict(r) for r in con.execute("""
                SELECT observed_at_utc,value,quality,metadata_json
                FROM bot_metrics
                WHERE source=? AND metric=? AND observed_at_utc>=?
                ORDER BY observed_at_utc ASC LIMIT ?
            """, (source, metric, since, limit)).fetchall()]
