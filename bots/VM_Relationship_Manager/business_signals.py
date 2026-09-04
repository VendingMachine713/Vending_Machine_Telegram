from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from business_memory import normalise_product_name
from database import Database, utcnow


BUSINESS_SIGNAL_SCHEMA = """
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS business_product_availability (
    product_id INTEGER PRIMARY KEY,
    is_available INTEGER NOT NULL DEFAULT 0 CHECK(is_available IN (0,1)),
    available_at TEXT,
    updated_at TEXT NOT NULL,
    updated_by INTEGER,
    note TEXT,
    FOREIGN KEY (product_id) REFERENCES business_products(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_business_availability_active
    ON business_product_availability(is_available, updated_at DESC);
"""


@dataclass(frozen=True)
class BusinessOperatorBrief:
    available_products: int
    reload_candidates: int
    dormant_clients: int
    repeat_dormant_clients: int
    top_reload: tuple[dict[str, Any], ...]
    top_dormant: tuple[dict[str, Any], ...]
    inactive_days: int


class BusinessSignals:
    """Private, review-first business status and passive candidate projections."""

    def __init__(self, db: Database):
        self.db = db
        self.init()

    def init(self) -> None:
        with self.db.connect() as con:
            con.executescript(BUSINESS_SIGNAL_SCHEMA)

    def _product(self, product: str):
        normalized = normalise_product_name(product)
        if not normalized:
            raise ValueError("Product name is required.")
        row = self.db.one(
            "SELECT * FROM business_products WHERE normalized_name=? AND active=1",
            (normalized,),
        )
        if not row:
            raise ValueError(
                "Product is not in Business Memory yet. Record or import business history first."
            )
        return row

    def mark_available(
        self,
        product: str,
        *,
        available: bool,
        updated_by: int | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        row = self._product(product)
        stamp = utcnow()
        available_at = stamp if available else None
        note_value = note.strip()[:500] if note and note.strip() else None
        with self.db.connect() as con:
            con.execute(
                """INSERT INTO business_product_availability
                   (product_id,is_available,available_at,updated_at,updated_by,note)
                   VALUES(?,?,?,?,?,?)
                   ON CONFLICT(product_id) DO UPDATE SET
                     is_available=excluded.is_available,
                     available_at=excluded.available_at,
                     updated_at=excluded.updated_at,
                     updated_by=excluded.updated_by,
                     note=excluded.note""",
                (
                    int(row["id"]),
                    1 if available else 0,
                    available_at,
                    stamp,
                    updated_by,
                    note_value,
                ),
            )
            if updated_by is not None:
                con.execute(
                    """INSERT INTO admin_audit(admin_id,action,telegram_id,details,created_at)
                       VALUES(?,?,?,?,?)""",
                    (
                        int(updated_by),
                        "business_product_availability_changed",
                        None,
                        f"{row['normalized_name']}:{'available' if available else 'unavailable'}",
                        stamp,
                    ),
                )
        return {
            "product_id": int(row["id"]),
            "name": str(row["name"]),
            "normalized_name": str(row["normalized_name"]),
            "is_available": bool(available),
            "available_at": available_at,
            "note": note_value,
        }

    def available_products(self) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in self.db.all(
                """SELECT p.id,p.name,p.normalized_name,a.available_at,a.updated_at,a.note
                   FROM business_product_availability a
                   JOIN business_products p ON p.id=a.product_id
                   WHERE a.is_available=1 AND p.active=1
                   ORDER BY a.available_at DESC, p.name COLLATE NOCASE"""
            )
        ]

    def reload_candidates(self, *, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.db.all(
            """SELECT p.id AS product_id,p.name AS product_name,p.normalized_name,
                      a.available_at,c.telegram_id,c.username,c.display_name,
                      COUNT(*) AS transaction_count,
                      COALESCE(SUM(t.quantity),0) AS total_quantity,
                      MAX(t.occurred_at) AS last_transaction_at
               FROM business_product_availability a
               JOIN business_products p ON p.id=a.product_id
               JOIN business_transactions t ON t.product_id=p.id AND t.role='client'
               JOIN contacts c ON c.telegram_id=t.telegram_id
               WHERE a.is_available=1 AND p.active=1
               GROUP BY p.id,c.telegram_id
               ORDER BY transaction_count DESC,total_quantity DESC,last_transaction_at DESC
               LIMIT ?""",
            (max(1, min(int(limit), 200)),),
        )
        return [dict(row) for row in rows]

    def dormant_clients(
        self,
        *,
        inactive_days: int = 30,
        limit: int = 50,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        days = max(1, min(int(inactive_days), 3650))
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            raise ValueError("now must include a timezone")
        cutoff = current.astimezone(timezone.utc) - timedelta(days=days)
        rows = self.db.all(
            """SELECT c.telegram_id,c.username,c.display_name,
                      COUNT(*) AS transaction_count,
                      COUNT(DISTINCT t.product_id) AS product_count,
                      MAX(t.occurred_at) AS last_transaction_at
               FROM business_transactions t
               JOIN contacts c ON c.telegram_id=t.telegram_id
               WHERE t.role='client'
               GROUP BY c.telegram_id
               HAVING MAX(t.occurred_at) <= ?
               ORDER BY transaction_count DESC,last_transaction_at ASC
               LIMIT ?""",
            (cutoff.isoformat(), max(1, min(int(limit), 200))),
        )
        return [dict(row) for row in rows]

    def operator_brief(
        self,
        *,
        inactive_days: int = 30,
        limit: int = 3,
        now: datetime | None = None,
    ) -> BusinessOperatorBrief:
        available = self.available_products()
        reload_rows = self.reload_candidates(limit=200)
        dormant = self.dormant_clients(
            inactive_days=inactive_days,
            limit=200,
            now=now,
        )
        repeat_dormant = sum(
            1 for row in dormant if int(row.get("transaction_count") or 0) >= 2
        )
        top_n = max(1, min(int(limit), 10))
        return BusinessOperatorBrief(
            available_products=len(available),
            reload_candidates=len(reload_rows),
            dormant_clients=len(dormant),
            repeat_dormant_clients=repeat_dormant,
            top_reload=tuple(reload_rows[:top_n]),
            top_dormant=tuple(dormant[:top_n]),
            inactive_days=max(1, min(int(inactive_days), 3650)),
        )
