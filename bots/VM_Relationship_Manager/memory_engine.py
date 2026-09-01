from __future__ import annotations

from database import Database, utcnow

CATEGORIES = {"preference","context","commitment","boundary","commercial","admin","custom"}


class MemoryEngine:
    """Structured, admin-authored relationship memory.

    This intentionally does not ingest message bodies automatically.
    """
    def __init__(self, db: Database):
        self.db = db

    def add(self, telegram_id: int, category: str, key: str, value: str, admin_id: int, confidence: int = 100):
        category = (category or "custom").strip().lower()
        if category not in CATEGORIES:
            raise ValueError(f"Category must be one of: {', '.join(sorted(CATEGORIES))}")
        key = key.strip()[:80]
        value = value.strip()[:1000]
        if not key or not value:
            raise ValueError("Memory key and value are required.")
        confidence = max(0, min(100, int(confidence)))
        mid = self.db.execute(
            """INSERT INTO relationship_memories
               (telegram_id,category,memory_key,memory_value,confidence,created_by,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (telegram_id, category, key, value, confidence, admin_id, utcnow(), utcnow()),
        )
        return self.db.one("SELECT * FROM relationship_memories WHERE id=?", (mid,))

    def list(self, telegram_id: int, limit: int = 30):
        return self.db.all(
            "SELECT * FROM relationship_memories WHERE telegram_id=? AND status='active' ORDER BY updated_at DESC,id DESC LIMIT ?",
            (telegram_id, limit),
        )

    def delete(self, memory_id: int):
        self.db.execute("UPDATE relationship_memories SET status='deleted',updated_at=? WHERE id=?", (utcnow(), memory_id))

    def summary(self, telegram_id: int):
        rows = self.list(telegram_id, 50)
        grouped: dict[str, list] = {}
        for r in rows:
            grouped.setdefault(r["category"], []).append(r)
        return grouped
