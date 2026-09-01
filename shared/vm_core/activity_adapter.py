from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
from typing import Any

from .db import PlatformDB
from .paths import project_root


def collect_search_activity(root: Path | None = None) -> dict[str, Any]:
    """Derive chat activity signals from Universal Search's indexed history.

    The adapter reads counts/timestamps only. Message text, usernames and query
    text never leave Universal Search's bot-owned database.
    """
    root = root or project_root()
    path = root / "bots" / "Universal_Search" / "data" / "universal_search.db"
    if not path.is_file():
        return {"available": False, "database": str(path), "reason": "database_unavailable"}
    try:
        con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=5)
        con.row_factory = sqlite3.Row
    except sqlite3.Error as exc:
        return {"available": False, "database": str(path), "reason": type(exc).__name__}

    shared = PlatformDB(root=root)
    shared.init()
    now = datetime.now(timezone.utc)
    recent_cutoff = (now - timedelta(hours=24)).isoformat()
    baseline_start = (now - timedelta(days=8)).isoformat()
    baseline_end = (now - timedelta(hours=24)).isoformat()
    result = {"available": True, "database": str(path), "chats": 0, "spikes": 0}
    try:
        tables = {str(r[0]) for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"indexed_messages", "chats"}.issubset(tables):
            return {**result, "available": False, "reason": "required_tables_missing"}
        rows = con.execute("""
            SELECT c.chat_id,c.title,
                   SUM(CASE WHEN m.date_utc>=? THEN 1 ELSE 0 END) AS recent_count,
                   SUM(CASE WHEN m.date_utc>=? AND m.date_utc<? THEN 1 ELSE 0 END) AS baseline_count,
                   SUM(CASE WHEN m.date_utc>=? AND m.is_ad=1 THEN 1 ELSE 0 END) AS recent_ads
            FROM chats c
            LEFT JOIN indexed_messages m ON m.chat_id=c.chat_id
            GROUP BY c.chat_id,c.title
        """, (recent_cutoff, baseline_start, baseline_end, recent_cutoff)).fetchall()
        result["chats"] = len(rows)
        for row in rows:
            recent = int(row["recent_count"] or 0)
            baseline_daily = float(row["baseline_count"] or 0) / 7.0
            recent_ads = int(row["recent_ads"] or 0)
            threshold = max(5.0, baseline_daily * 2.5)
            if recent < threshold:
                continue
            ratio = recent / max(1.0, baseline_daily)
            score = min(100.0, 50.0 + min(50.0, (ratio - 1.0) * 12.5))
            confidence = min(0.99, 0.65 + min(0.30, recent / 100.0))
            chat_id = str(row["chat_id"])
            shared.upsert_signal(
                f"search:activity_spike:{chat_id}",
                "search_activity_spike",
                "Indexed Telegram activity in this chat is materially above its recent baseline",
                subject_type="chat",
                subject_id=chat_id,
                score=score,
                confidence=confidence,
                evidence={
                    "recent_24h_messages": recent,
                    "baseline_daily_messages": round(baseline_daily, 2),
                    "recent_24h_ads": recent_ads,
                    "ratio": round(ratio, 2),
                    "window_hours": 24,
                    "baseline_days": 7,
                },
            )
            result["spikes"] += 1
    finally:
        con.close()
    return result
