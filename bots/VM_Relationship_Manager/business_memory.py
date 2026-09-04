from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from database import Database, utcnow


BUSINESS_SCHEMA_VERSION = 1
VALID_ROLES = {"client", "supplier"}

BUSINESS_SCHEMA = """
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS business_memory_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS business_products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    normalized_name TEXT NOT NULL UNIQUE,
    category TEXT,
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS business_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('client','supplier')),
    product_id INTEGER NOT NULL,
    quantity REAL NOT NULL DEFAULT 1 CHECK(quantity > 0),
    unit TEXT NOT NULL DEFAULT 'unit',
    total_minor_units INTEGER CHECK(total_minor_units IS NULL OR total_minor_units >= 0),
    currency TEXT NOT NULL DEFAULT 'AUD',
    occurred_at TEXT NOT NULL,
    note TEXT,
    recorded_by INTEGER,
    source TEXT NOT NULL DEFAULT 'manual',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (telegram_id) REFERENCES contacts(telegram_id) ON DELETE CASCADE,
    FOREIGN KEY (product_id) REFERENCES business_products(id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_business_tx_contact
    ON business_transactions(telegram_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_business_tx_role
    ON business_transactions(role, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_business_tx_product
    ON business_transactions(product_id, role, occurred_at DESC);
"""


@dataclass(frozen=True)
class Money:
    minor_units: int
    currency: str = "AUD"

    @property
    def amount(self) -> Decimal:
        return Decimal(self.minor_units) / Decimal(100)


def normalise_product_name(value: str) -> str:
    return " ".join(value.strip().lower().split())


def parse_money(value: str | int | float | Decimal | None, currency: str = "AUD") -> Money | None:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None

    try:
        amount = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, AttributeError) as exc:
        raise ValueError("Amount must be a valid number.") from exc

    if amount < 0:
        raise ValueError("Amount cannot be negative.")

    code = (currency or "AUD").strip().upper()
    if len(code) != 3 or not code.isalpha():
        raise ValueError("Currency must be a three-letter code such as AUD.")

    minor = int((amount * Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return Money(minor_units=minor, currency=code)


class BusinessMemory:
    """Private CRM memory for client/supplier product history.

    This layer deliberately does not send messages automatically. It records
    operator-entered business history and returns ranked candidates so the
    existing Relationship Manager can remain admin-by-exception.
    """

    def __init__(self, db: Database):
        self.db = db
        self.init()

    def init(self) -> None:
        with self.db.connect() as con:
            con.executescript(BUSINESS_SCHEMA)
            con.execute(
                """INSERT INTO business_memory_meta(key,value,updated_at)
                   VALUES('schema_version',?,?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
                (str(BUSINESS_SCHEMA_VERSION), utcnow()),
            )

    def _contact(self, telegram_id: int):
        row = self.db.one("SELECT * FROM contacts WHERE telegram_id=?", (telegram_id,))
        if not row:
            raise ValueError(f"Unknown contact: {telegram_id}")
        return row

    def _product(self, name: str):
        display = " ".join(name.strip().split())
        normalized = normalise_product_name(display)
        if not normalized:
            raise ValueError("Product name is required.")

        row = self.db.one(
            "SELECT * FROM business_products WHERE normalized_name=?",
            (normalized,),
        )
        if row:
            if row["name"] != display:
                self.db.execute(
                    "UPDATE business_products SET name=?, updated_at=? WHERE id=?",
                    (display, utcnow(), row["id"]),
                )
                row = self.db.one("SELECT * FROM business_products WHERE id=?", (row["id"],))
            return row

        product_id = self.db.execute(
            """INSERT INTO business_products(name,normalized_name,created_at,updated_at)
               VALUES(?,?,?,?)""",
            (display, normalized, utcnow(), utcnow()),
        )
        return self.db.one("SELECT * FROM business_products WHERE id=?", (product_id,))

    @staticmethod
    def _occurred_iso(occurred_at: datetime | None) -> str:
        if occurred_at is None:
            return utcnow()
        if occurred_at.tzinfo is None:
            raise ValueError("occurred_at must include a timezone.")
        return occurred_at.astimezone(timezone.utc).isoformat()

    def record(
        self,
        telegram_id: int,
        role: str,
        product: str,
        *,
        quantity: float = 1,
        unit: str = "unit",
        total: str | int | float | Decimal | None = None,
        currency: str = "AUD",
        occurred_at: datetime | None = None,
        note: str | None = None,
        recorded_by: int | None = None,
        source: str = "manual",
    ) -> int:
        role = role.strip().lower()
        if role not in VALID_ROLES:
            raise ValueError("Role must be client or supplier.")

        self._contact(telegram_id)
        product_row = self._product(product)

        try:
            qty = float(quantity)
        except (TypeError, ValueError) as exc:
            raise ValueError("Quantity must be a positive number.") from exc
        if qty <= 0:
            raise ValueError("Quantity must be a positive number.")

        unit_value = " ".join((unit or "unit").strip().split())[:32] or "unit"
        money = parse_money(total, currency)
        code = money.currency if money else (currency or "AUD").strip().upper()
        if len(code) != 3 or not code.isalpha():
            raise ValueError("Currency must be a three-letter code such as AUD.")

        note_value = note.strip()[:1000] if note and note.strip() else None
        source_value = (source or "manual").strip().lower()[:64] or "manual"
        stamp = utcnow()
        tx_id = self.db.execute(
            """INSERT INTO business_transactions
               (telegram_id,role,product_id,quantity,unit,total_minor_units,currency,
                occurred_at,note,recorded_by,source,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                telegram_id,
                role,
                product_row["id"],
                qty,
                unit_value,
                money.minor_units if money else None,
                code,
                self._occurred_iso(occurred_at),
                note_value,
                recorded_by,
                source_value,
                stamp,
                stamp,
            ),
        )

        # Preserve multi-role contacts without forcing the single legacy
        # relationship_type field to choose between client and supplier.
        self.db.execute(
            "INSERT OR IGNORE INTO tags(telegram_id,tag,created_at) VALUES(?,?,?)",
            (telegram_id, role, stamp),
        )
        self.db.execute(
            """INSERT INTO relationship_events(telegram_id,event_type,details,created_at)
               VALUES(?,?,?,?)""",
            (
                telegram_id,
                "business_transaction_recorded",
                f"{role}:{product_row['normalized_name']}:{qty:g} {unit_value}",
                stamp,
            ),
        )
        if recorded_by is not None:
            self.db.execute(
                """INSERT INTO admin_audit(admin_id,action,telegram_id,details,created_at)
                   VALUES(?,?,?,?,?)""",
                (
                    recorded_by,
                    "business_transaction_recorded",
                    telegram_id,
                    f"{role}:{product_row['normalized_name']}",
                    stamp,
                ),
            )
        return tx_id

    def transaction(self, transaction_id: int):
        return self.db.one(
            """SELECT t.*, p.name AS product_name, p.normalized_name,
                      c.username, c.display_name
               FROM business_transactions t
               JOIN business_products p ON p.id=t.product_id
               JOIN contacts c ON c.telegram_id=t.telegram_id
               WHERE t.id=?""",
            (transaction_id,),
        )

    def correct_transaction(
        self,
        transaction_id: int,
        *,
        recorded_by: int,
        role: str | None = None,
        product: str | None = None,
        quantity: float | None = None,
        total: str | int | float | Decimal | None = None,
        currency: str | None = None,
        note: str | None = None,
        occurred_at: datetime | None = None,
    ) -> dict[str, Any]:
        """Apply an explicit correction and retain a before/after audit trail."""
        before = self.transaction(transaction_id)
        if not before:
            raise ValueError("Business transaction was not found.")
        next_role = (role or before["role"]).strip().lower()
        if next_role not in VALID_ROLES:
            raise ValueError("Role must be client or supplier.")
        product_row = self._product(product or before["product_name"])
        qty = float(quantity if quantity is not None else before["quantity"])
        if qty <= 0:
            raise ValueError("Quantity must be a positive number.")
        next_currency = (currency or before["currency"] or "AUD").strip().upper()
        money = parse_money(total if total is not None else (before["total_minor_units"] / 100 if before["total_minor_units"] is not None else None), next_currency)
        next_note = (note if note is not None else before["note"])
        next_date = self._occurred_iso(occurred_at) if occurred_at is not None else before["occurred_at"]
        after_values = {"role": next_role, "product": product_row["normalized_name"], "quantity": qty, "total_minor_units": money.minor_units if money else None, "currency": money.currency if money else next_currency, "occurred_at": next_date, "note": next_note}
        before_values = {key: before[key] for key in after_values if key != "product"}
        before_values["product"] = before["normalized_name"]
        stamp = utcnow()
        self.db.execute(
            """UPDATE business_transactions SET role=?,product_id=?,quantity=?,total_minor_units=?,currency=?,occurred_at=?,note=?,updated_at=? WHERE id=?""",
            (next_role, product_row["id"], qty, after_values["total_minor_units"], after_values["currency"], next_date, next_note, stamp, transaction_id),
        )
        details = f"transaction={transaction_id}; before={before_values}; after={after_values}"
        self.db.execute("INSERT INTO admin_audit(admin_id,action,telegram_id,details,created_at) VALUES(?,?,?,?,?)", (recorded_by, "business_transaction_corrected", before["telegram_id"], details[:4000], stamp))
        self.db.execute("INSERT INTO relationship_events(telegram_id,event_type,details,created_at) VALUES(?,?,?,?)", (before["telegram_id"], "business_transaction_corrected", f"transaction:{transaction_id}", stamp))
        return self.transaction(transaction_id)

    def history(self, telegram_id: int, limit: int = 20):
        self._contact(telegram_id)
        return self.db.all(
            """SELECT t.*, p.name AS product_name
               FROM business_transactions t
               JOIN business_products p ON p.id=t.product_id
               WHERE t.telegram_id=?
               ORDER BY t.occurred_at DESC, t.id DESC
               LIMIT ?""",
            (telegram_id, max(1, min(int(limit), 100))),
        )

    def contact_summary(self, telegram_id: int) -> dict[str, Any]:
        contact = self._contact(telegram_id)
        rows = self.db.all(
            """SELECT role,
                      COUNT(*) AS transaction_count,
                      COALESCE(SUM(quantity),0) AS total_quantity,
                      MAX(occurred_at) AS last_transaction_at,
                      COALESCE(SUM(CASE WHEN currency='AUD' THEN total_minor_units ELSE 0 END),0) AS aud_minor
               FROM business_transactions
               WHERE telegram_id=?
               GROUP BY role""",
            (telegram_id,),
        )
        products = self.db.all(
            """SELECT p.name, t.role, COUNT(*) AS transaction_count,
                      COALESCE(SUM(t.quantity),0) AS total_quantity,
                      MAX(t.occurred_at) AS last_transaction_at
               FROM business_transactions t
               JOIN business_products p ON p.id=t.product_id
               WHERE t.telegram_id=?
               GROUP BY p.id, t.role
               ORDER BY transaction_count DESC, last_transaction_at DESC""",
            (telegram_id,),
        )
        return {
            "contact": contact,
            "roles": {r["role"]: dict(r) for r in rows},
            "products": [dict(r) for r in products],
        }

    def _top(
        self,
        role: str,
        *,
        product: str | None = None,
        days: int | None = None,
        limit: int = 10,
    ):
        if role not in VALID_ROLES:
            raise ValueError("Role must be client or supplier.")

        where = ["t.role=?"]
        params: list[Any] = [role]
        if product:
            where.append("p.normalized_name=?")
            params.append(normalise_product_name(product))
        if days is not None:
            cutoff = datetime.now(timezone.utc) - timedelta(days=max(0, int(days)))
            where.append("t.occurred_at>=?")
            params.append(cutoff.isoformat())

        params.append(max(1, min(int(limit), 100)))
        return self.db.all(
            f"""SELECT c.telegram_id, c.username, c.display_name,
                       COUNT(*) AS transaction_count,
                       COALESCE(SUM(t.quantity),0) AS total_quantity,
                       MAX(t.occurred_at) AS last_transaction_at,
                       COALESCE(SUM(CASE WHEN t.currency='AUD' THEN t.total_minor_units ELSE 0 END),0) AS aud_minor
                FROM business_transactions t
                JOIN business_products p ON p.id=t.product_id
                JOIN contacts c ON c.telegram_id=t.telegram_id
                WHERE {' AND '.join(where)}
                GROUP BY c.telegram_id
                ORDER BY transaction_count DESC, total_quantity DESC, last_transaction_at DESC
                LIMIT ?""",
            tuple(params),
        )

    def top_clients(self, product: str | None = None, *, days: int | None = None, limit: int = 10):
        return self._top("client", product=product, days=days, limit=limit)

    def top_suppliers(self, product: str | None = None, *, days: int | None = None, limit: int = 10):
        return self._top("supplier", product=product, days=days, limit=limit)

    def reload_candidates(self, product: str, *, limit: int = 25):
        normalized = normalise_product_name(product)
        if not normalized:
            raise ValueError("Product name is required.")
        return self.db.all(
            """SELECT c.telegram_id, c.username, c.display_name,
                      COUNT(*) AS transaction_count,
                      COALESCE(SUM(t.quantity),0) AS total_quantity,
                      MAX(t.occurred_at) AS last_transaction_at,
                      COALESCE(SUM(CASE WHEN t.currency='AUD' THEN t.total_minor_units ELSE 0 END),0) AS aud_minor
               FROM business_transactions t
               JOIN business_products p ON p.id=t.product_id
               JOIN contacts c ON c.telegram_id=t.telegram_id
               WHERE t.role='client' AND p.normalized_name=?
               GROUP BY c.telegram_id
               ORDER BY transaction_count DESC, total_quantity DESC, last_transaction_at DESC
               LIMIT ?""",
            (normalized, max(1, min(int(limit), 100))),
        )

    def touchbase_candidates(self, *, inactive_days: int = 30, limit: int = 25):
        cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, int(inactive_days)))
        return self.db.all(
            """SELECT c.telegram_id, c.username, c.display_name,
                      COUNT(*) AS transaction_count,
                      MAX(t.occurred_at) AS last_transaction_at,
                      COUNT(DISTINCT t.product_id) AS product_count
               FROM business_transactions t
               JOIN contacts c ON c.telegram_id=t.telegram_id
               WHERE t.role='client'
               GROUP BY c.telegram_id
               HAVING MAX(t.occurred_at) <= ?
               ORDER BY transaction_count DESC, last_transaction_at ASC
               LIMIT ?""",
            (cutoff.isoformat(), max(1, min(int(limit), 100))),
        )

    def overview(self) -> dict[str, int]:
        products = self.db.one("SELECT COUNT(*) AS n FROM business_products WHERE active=1")["n"]
        transactions = self.db.one("SELECT COUNT(*) AS n FROM business_transactions")["n"]
        clients = self.db.one(
            "SELECT COUNT(DISTINCT telegram_id) AS n FROM business_transactions WHERE role='client'"
        )["n"]
        suppliers = self.db.one(
            "SELECT COUNT(DISTINCT telegram_id) AS n FROM business_transactions WHERE role='supplier'"
        )["n"]
        return {
            "products": int(products),
            "transactions": int(transactions),
            "clients": int(clients),
            "suppliers": int(suppliers),
        }
