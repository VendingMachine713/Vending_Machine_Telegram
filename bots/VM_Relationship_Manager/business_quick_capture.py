from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from business_memory import BusinessMemory, VALID_ROLES
from database import Database


@dataclass(frozen=True)
class ProductSuggestion:
    product_id: int
    name: str
    transaction_count: int
    last_transaction_at: str | None
    source: str


class BusinessQuickCapture:
    """Low-touch write helper for Business Memory.

    The service deliberately keeps the write semantics conservative:
    - an existing Relationship Manager contact is always required;
    - quick capture records one unit by default with no inferred transaction value;
    - product suggestions prefer the contact's own history, then recent global products;
    - repeat-last copies role/product/quantity/unit but never copies an old monetary value.
    """

    def __init__(self, db: Database, memory: BusinessMemory):
        self.db = db
        self.memory = memory

    def contact(self, telegram_id: int):
        row = self.db.one("SELECT * FROM contacts WHERE telegram_id=?", (int(telegram_id),))
        if not row:
            raise ValueError(f"Unknown contact: {telegram_id}")
        return row

    @staticmethod
    def _role(role: str) -> str:
        value = (role or "").strip().lower()
        if value not in VALID_ROLES:
            raise ValueError("Role must be client or supplier.")
        return value

    def suggestions(self, telegram_id: int, role: str, *, limit: int = 6) -> list[ProductSuggestion]:
        self.contact(telegram_id)
        role = self._role(role)
        limit = max(1, min(int(limit), 12))

        personal = self.db.all(
            """SELECT p.id AS product_id, p.name,
                      COUNT(*) AS transaction_count,
                      MAX(t.occurred_at) AS last_transaction_at
               FROM business_transactions t
               JOIN business_products p ON p.id=t.product_id
               WHERE t.telegram_id=? AND t.role=? AND p.active=1
               GROUP BY p.id
               ORDER BY transaction_count DESC, last_transaction_at DESC, p.name COLLATE NOCASE
               LIMIT ?""",
            (int(telegram_id), role, limit),
        )

        suggestions: list[ProductSuggestion] = [
            ProductSuggestion(
                product_id=int(row["product_id"]),
                name=str(row["name"]),
                transaction_count=int(row["transaction_count"] or 0),
                last_transaction_at=str(row["last_transaction_at"]) if row["last_transaction_at"] else None,
                source="contact_history",
            )
            for row in personal
        ]
        seen = {item.product_id for item in suggestions}

        if len(suggestions) < limit:
            global_rows = self.db.all(
                """SELECT p.id AS product_id, p.name,
                          COUNT(t.id) AS transaction_count,
                          MAX(t.occurred_at) AS last_transaction_at
                   FROM business_products p
                   LEFT JOIN business_transactions t ON t.product_id=p.id
                   WHERE p.active=1
                   GROUP BY p.id
                   ORDER BY last_transaction_at DESC, transaction_count DESC, p.name COLLATE NOCASE
                   LIMIT ?""",
                (limit * 3,),
            )
            for row in global_rows:
                product_id = int(row["product_id"])
                if product_id in seen:
                    continue
                suggestions.append(
                    ProductSuggestion(
                        product_id=product_id,
                        name=str(row["name"]),
                        transaction_count=int(row["transaction_count"] or 0),
                        last_transaction_at=str(row["last_transaction_at"]) if row["last_transaction_at"] else None,
                        source="recent_global",
                    )
                )
                seen.add(product_id)
                if len(suggestions) >= limit:
                    break

        return suggestions

    def product(self, product_id: int):
        row = self.db.one(
            "SELECT * FROM business_products WHERE id=? AND active=1",
            (int(product_id),),
        )
        if not row:
            raise ValueError("Product is not available for quick capture.")
        return row

    def record_product_id(
        self,
        telegram_id: int,
        role: str,
        product_id: int,
        *,
        recorded_by: int,
    ) -> int:
        self.contact(telegram_id)
        role = self._role(role)
        product = self.product(product_id)
        return self.memory.record(
            int(telegram_id),
            role,
            str(product["name"]),
            quantity=1,
            total=None,
            recorded_by=int(recorded_by),
            source="quick_capture",
        )

    def record_product_name(
        self,
        telegram_id: int,
        role: str,
        product_name: str,
        *,
        recorded_by: int,
    ) -> int:
        self.contact(telegram_id)
        role = self._role(role)
        name = " ".join((product_name or "").strip().split())
        if not name:
            raise ValueError("Product name is required.")
        if len(name) > 120:
            raise ValueError("Product name is too long.")
        return self.memory.record(
            int(telegram_id),
            role,
            name,
            quantity=1,
            total=None,
            recorded_by=int(recorded_by),
            source="quick_capture_new_product",
        )

    def last_transaction(self, telegram_id: int) -> dict[str, Any] | None:
        self.contact(telegram_id)
        row = self.db.one(
            """SELECT t.*, p.name AS product_name
               FROM business_transactions t
               JOIN business_products p ON p.id=t.product_id
               WHERE t.telegram_id=?
               ORDER BY t.occurred_at DESC, t.id DESC
               LIMIT 1""",
            (int(telegram_id),),
        )
        return dict(row) if row else None

    def repeat_last(self, telegram_id: int, *, recorded_by: int) -> int:
        last = self.last_transaction(telegram_id)
        if not last:
            raise ValueError("No previous business transaction exists for this contact.")
        return self.memory.record(
            int(telegram_id),
            str(last["role"]),
            str(last["product_name"]),
            quantity=float(last["quantity"]),
            unit=str(last["unit"]),
            total=None,
            currency=str(last["currency"] or "AUD"),
            recorded_by=int(recorded_by),
            source="quick_repeat",
        )
