from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .adapters import _connect_readonly, _resolve_bot_path, _tables
from .db import PlatformDB
from .paths import project_root


def _token(*parts: object) -> str:
    raw = "|".join(str(part) for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def collect_business_memory_signals(
    root: Path | None = None,
    *,
    inactive_days: int = 30,
) -> dict[str, Any]:
    """Project Business Memory into bounded chat-level intelligence signals.

    The Relationship Manager database is read only. Shared evidence contains
    aggregate business metadata only: no notes, message bodies, usernames,
    display names, raw Telegram contact IDs, or product names are copied.
    """
    root = root or project_root()
    bot_dir = root / "bots" / "VM_Relationship_Manager"
    default = root / "shared" / "exports" / "VM_Relationship_Manager" / "vm_relationships.db"
    db_path = _resolve_bot_path(bot_dir, "DATABASE_PATH", default)
    con = _connect_readonly(db_path)
    if con is None:
        return {"available": False, "database": str(db_path), "reason": "database_unavailable"}

    shared = PlatformDB(root=root)
    shared.init()
    stamp = datetime.now(timezone.utc).isoformat()
    with shared.connect() as dst:
        dst.execute(
            "UPDATE intelligence_signals SET status='INACTIVE',updated_at_utc=? "
            "WHERE signal_key LIKE 'business:reload:%' OR signal_key LIKE 'business:dormant:%'",
            (stamp,),
        )

    result = {
        "available": True,
        "database": str(db_path),
        "reload_signals": 0,
        "dormant_signals": 0,
        "inactive_days": max(1, int(inactive_days)),
    }
    try:
        tables = _tables(con)
        required = {
            "business_transactions",
            "business_products",
            "business_product_availability",
            "contact_groups",
        }
        if not required.issubset(tables):
            return {**result, "available": False, "reason": "required_tables_missing"}

        reload_rows = con.execute(
            """SELECT t.telegram_id,g.chat_id,p.normalized_name,a.available_at,
                      COUNT(*) AS transaction_count,
                      COALESCE(SUM(t.quantity),0) AS total_quantity,
                      MAX(t.occurred_at) AS last_business_at
               FROM business_product_availability a
               JOIN business_products p ON p.id=a.product_id
               JOIN business_transactions t ON t.product_id=p.id AND t.role='client'
               JOIN contact_groups g ON g.telegram_id=t.telegram_id
               WHERE a.is_available=1 AND p.active=1
               GROUP BY t.telegram_id,g.chat_id,p.id"""
        ).fetchall()

        now = datetime.now(timezone.utc)
        for row in reload_rows:
            count = max(1, int(row["transaction_count"] or 1))
            last = _parse_time(row["last_business_at"])
            age_days = (now - last.astimezone(timezone.utc)).days if last else 9999
            repeat_bonus = min(30, max(0, count - 1) * 10)
            recency_bonus = 20 if age_days <= 90 else 10 if age_days <= 180 else 0
            score = min(100, 50 + repeat_bonus + recency_bonus)
            product_key = _token("product", row["normalized_name"])
            contact_key = _token("contact", row["telegram_id"])
            chat_id = str(row["chat_id"])
            shared.upsert_signal(
                f"business:reload:{_token(contact_key, product_key, chat_id)}",
                "business_reload_opportunity",
                "An available product has previous client history in this Telegram chat.",
                subject_type="chat",
                subject_id=chat_id,
                score=score,
                confidence=0.9,
                evidence={
                    "product_key": product_key,
                    "transaction_count": count,
                    "total_quantity": float(row["total_quantity"] or 0),
                    "last_business_at": row["last_business_at"],
                    "available_at": row["available_at"],
                    "days_since_last_business": max(0, age_days),
                },
            )
            result["reload_signals"] += 1

        days = max(1, int(inactive_days))
        dormant_rows = con.execute(
            """SELECT t.telegram_id,g.chat_id,
                      COUNT(*) AS transaction_count,
                      COUNT(DISTINCT t.product_id) AS product_count,
                      MAX(t.occurred_at) AS last_business_at
               FROM business_transactions t
               JOIN contact_groups g ON g.telegram_id=t.telegram_id
               WHERE t.role='client'
               GROUP BY t.telegram_id,g.chat_id"""
        ).fetchall()
        for row in dormant_rows:
            last = _parse_time(row["last_business_at"])
            if last is None:
                continue
            age_days = max(0, (now - last.astimezone(timezone.utc)).days)
            if age_days < days:
                continue
            count = max(1, int(row["transaction_count"] or 1))
            score = min(100, 45 + min(35, max(0, count - 1) * 10) + min(20, (age_days // 30) * 5))
            chat_id = str(row["chat_id"])
            contact_key = _token("contact", row["telegram_id"])
            shared.upsert_signal(
                f"business:dormant:{_token(contact_key, chat_id)}",
                "business_dormant_client_opportunity",
                "A previous client relationship has been inactive beyond the business reconnect threshold in this Telegram chat.",
                subject_type="chat",
                subject_id=chat_id,
                score=score,
                confidence=0.9,
                evidence={
                    "transaction_count": count,
                    "product_count": int(row["product_count"] or 0),
                    "last_business_at": row["last_business_at"],
                    "days_inactive": age_days,
                    "inactive_threshold_days": days,
                },
            )
            result["dormant_signals"] += 1
    finally:
        con.close()
    return result
