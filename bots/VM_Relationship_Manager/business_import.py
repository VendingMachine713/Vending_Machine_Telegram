from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass, field
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Any

from business_memory import (
    BusinessMemory,
    VALID_ROLES,
    normalise_product_name,
    parse_money,
)
from database import Database, utcnow


IMPORT_SCHEMA_VERSION = 1
IMPORT_SCHEMA = """
CREATE TABLE IF NOT EXISTS business_import_receipts (
    import_key TEXT PRIMARY KEY,
    transaction_id INTEGER NOT NULL,
    source_file TEXT,
    source_row INTEGER,
    imported_at TEXT NOT NULL,
    FOREIGN KEY (transaction_id) REFERENCES business_transactions(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_business_import_tx
    ON business_import_receipts(transaction_id);
"""

REQUIRED_COLUMNS = {"contact", "role", "product"}
OPTIONAL_COLUMNS = {
    "quantity",
    "unit",
    "total",
    "currency",
    "occurred_at",
    "note",
    "external_id",
}
ALLOWED_COLUMNS = REQUIRED_COLUMNS | OPTIONAL_COLUMNS


@dataclass(frozen=True)
class ImportRow:
    source_row: int
    telegram_id: int
    role: str
    product: str
    normalized_product: str
    quantity: float
    unit: str
    total_minor_units: int | None
    currency: str
    occurred_at: str
    note: str | None
    import_key: str


@dataclass(frozen=True)
class ImportProblem:
    source_row: int
    message: str


@dataclass
class ImportPreview:
    source_file: str
    total_rows: int = 0
    valid_rows: list[ImportRow] = field(default_factory=list)
    duplicate_rows: list[ImportRow] = field(default_factory=list)
    problems: list[ImportProblem] = field(default_factory=list)

    @property
    def can_apply(self) -> bool:
        return not self.problems

    @property
    def new_count(self) -> int:
        return len(self.valid_rows)

    @property
    def duplicate_count(self) -> int:
        return len(self.duplicate_rows)


@dataclass(frozen=True)
class ImportResult:
    source_file: str
    inserted: int
    skipped_duplicates: int
    transaction_ids: tuple[int, ...]


class BusinessHistoryImporter:
    """Dry-run-first, idempotent CSV importer for historical CRM records.

    Contact resolution is intentionally strict: a CSV contact must be a Telegram
    numeric ID or an exact username already present in Relationship Manager.
    Fuzzy display-name matching is not used for bulk writes.
    """

    def __init__(self, db: Database):
        self.db = db
        # The importer may be used directly by tests/tools, so make the business
        # schema dependency explicit instead of relying on runtime startup order.
        self.memory = BusinessMemory(db)
        self.init()

    def init(self) -> None:
        with self.db.connect() as con:
            con.executescript(IMPORT_SCHEMA)
            con.execute(
                """INSERT INTO business_memory_meta(key,value,updated_at)
                   VALUES('import_schema_version',?,?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
                (str(IMPORT_SCHEMA_VERSION), utcnow()),
            )

    @staticmethod
    def _clean_header(value: str | None) -> str:
        return (value or "").strip().lower()

    def _contact_id(self, value: str) -> int:
        raw = value.strip()
        if not raw:
            raise ValueError("contact is required")
        without_at = raw.lstrip("@")
        if without_at.lstrip("-").isdigit():
            telegram_id = int(without_at)
            row = self.db.one(
                "SELECT telegram_id FROM contacts WHERE telegram_id=?",
                (telegram_id,),
            )
        else:
            rows = self.db.all(
                "SELECT telegram_id FROM contacts WHERE username=? COLLATE NOCASE LIMIT 2",
                (without_at,),
            )
            if len(rows) > 1:
                raise ValueError(f"contact username is ambiguous: {raw}")
            row = rows[0] if rows else None
        if not row:
            raise ValueError(
                f"contact is not known to Relationship Manager: {raw}. "
                "Resolve/rescan the contact before importing."
            )
        return int(row["telegram_id"])

    @staticmethod
    def _quantity(value: str | None) -> float:
        raw = (value or "").strip()
        if not raw:
            return 1.0
        try:
            result = float(raw)
        except ValueError as exc:
            raise ValueError("quantity must be a positive number") from exc
        if result <= 0:
            raise ValueError("quantity must be a positive number")
        return result

    @staticmethod
    def _currency(value: str | None) -> str:
        code = ((value or "AUD").strip() or "AUD").upper()
        if len(code) != 3 or not code.isalpha():
            raise ValueError("currency must be a three-letter code such as AUD")
        return code

    @staticmethod
    def _occurred_at(value: str | None) -> str:
        raw = (value or "").strip()
        if not raw:
            return utcnow()
        try:
            if len(raw) == 10:
                day = datetime.strptime(raw, "%Y-%m-%d").date()
                # Midday UTC keeps a date-only historical record stable and
                # avoids pretending an exact clock time was supplied.
                return datetime.combine(day, time(12, 0), tzinfo=timezone.utc).isoformat()
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(
                "occurred_at must be YYYY-MM-DD or ISO-8601 with a timezone"
            ) from exc
        if dt.tzinfo is None:
            raise ValueError("occurred_at ISO timestamps must include a timezone")
        return dt.astimezone(timezone.utc).isoformat()

    @staticmethod
    def _fingerprint(values: dict[str, Any], external_id: str | None) -> str:
        external = (external_id or "").strip()
        if external:
            return "external:" + hashlib.sha256(external.encode("utf-8")).hexdigest()
        canonical = "\x1f".join(
            str(values[key])
            for key in (
                "telegram_id",
                "role",
                "normalized_product",
                "quantity",
                "unit",
                "total_minor_units",
                "currency",
                "occurred_at",
                "note",
            )
        )
        return "rowhash:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _parse_row(self, row: dict[str, str], source_row: int) -> ImportRow:
        telegram_id = self._contact_id(row.get("contact", ""))
        role = (row.get("role") or "").strip().lower()
        if role not in VALID_ROLES:
            raise ValueError("role must be client or supplier")

        product = " ".join((row.get("product") or "").strip().split())
        normalized_product = normalise_product_name(product)
        if not normalized_product:
            raise ValueError("product is required")

        quantity = self._quantity(row.get("quantity"))
        unit = " ".join((row.get("unit") or "unit").strip().split())[:32] or "unit"
        currency = self._currency(row.get("currency"))
        money = parse_money(row.get("total"), currency)
        occurred_raw = (row.get("occurred_at") or "").strip()
        occurred_at = self._occurred_at(occurred_raw)
        note = (row.get("note") or "").strip()[:1000] or None
        values = {
            "telegram_id": telegram_id,
            "role": role,
            "normalized_product": normalized_product,
            "quantity": format(quantity, ".12g"),
            "unit": unit,
            "total_minor_units": money.minor_units if money else None,
            "currency": money.currency if money else currency,
            # Keep row-hash dedupe stable when no date was supplied. The actual
            # transaction still receives an import timestamp, but rerunning the
            # same historical CSV does not create another transaction.
            "occurred_at": occurred_at if occurred_raw else "<unspecified>",
            "note": note or "",
        }
        import_key = self._fingerprint(values, row.get("external_id"))
        return ImportRow(
            source_row=source_row,
            telegram_id=telegram_id,
            role=role,
            product=product,
            normalized_product=normalized_product,
            quantity=quantity,
            unit=unit,
            total_minor_units=money.minor_units if money else None,
            currency=money.currency if money else currency,
            occurred_at=occurred_at,
            note=note,
            import_key=import_key,
        )

    def preview_text(self, text: str, *, source_file: str = "<memory>") -> ImportPreview:
        preview = ImportPreview(source_file=source_file)
        reader = csv.DictReader(io.StringIO(text))
        if reader.fieldnames is None:
            preview.problems.append(ImportProblem(1, "CSV header row is missing"))
            return preview

        headers = [self._clean_header(item) for item in reader.fieldnames]
        if any(not item for item in headers):
            preview.problems.append(ImportProblem(1, "CSV contains a blank column name"))
            return preview
        if len(headers) != len(set(headers)):
            preview.problems.append(ImportProblem(1, "CSV contains duplicate column names"))
            return preview
        missing = sorted(REQUIRED_COLUMNS - set(headers))
        unknown = sorted(set(headers) - ALLOWED_COLUMNS)
        if missing:
            preview.problems.append(
                ImportProblem(1, "missing required column(s): " + ", ".join(missing))
            )
        if unknown:
            preview.problems.append(
                ImportProblem(1, "unknown column(s): " + ", ".join(unknown))
            )
        if preview.problems:
            return preview

        # DictReader preserves original header spelling, so normalize row keys.
        seen_in_file: set[str] = set()
        for source_row, raw_row in enumerate(reader, start=2):
            if raw_row is None:
                continue
            extra = raw_row.get(None)
            if extra and any((item or "").strip() for item in extra):
                preview.total_rows += 1
                preview.problems.append(
                    ImportProblem(source_row, "row contains more values than the CSV header")
                )
                continue
            if all(
                not (value or "").strip()
                for key, value in raw_row.items()
                if key is not None
            ):
                continue
            preview.total_rows += 1
            row = {
                self._clean_header(key): (value or "")
                for key, value in raw_row.items()
                if key is not None
            }
            try:
                parsed = self._parse_row(row, source_row)
            except ValueError as exc:
                preview.problems.append(ImportProblem(source_row, str(exc)))
                continue

            if parsed.import_key in seen_in_file:
                preview.duplicate_rows.append(parsed)
                continue
            seen_in_file.add(parsed.import_key)
            exists = self.db.one(
                "SELECT 1 FROM business_import_receipts WHERE import_key=?",
                (parsed.import_key,),
            )
            if exists:
                preview.duplicate_rows.append(parsed)
            else:
                preview.valid_rows.append(parsed)
        return preview

    def preview_file(self, path: Path) -> ImportPreview:
        text = path.read_text(encoding="utf-8-sig")
        return self.preview_text(text, source_file=path.name)

    def apply_text(
        self,
        text: str,
        *,
        source_file: str = "<memory>",
        recorded_by: int | None = None,
    ) -> ImportResult:
        preview = self.preview_text(text, source_file=source_file)
        if preview.problems:
            details = "; ".join(
                f"row {item.source_row}: {item.message}" for item in preview.problems[:10]
            )
            raise ValueError(f"Import validation failed: {details}")

        inserted_ids: list[int] = []
        skipped = preview.duplicate_count
        stamp = utcnow()
        with self.db.connect() as con:
            for row in preview.valid_rows:
                # Race-safe idempotency check inside the write transaction.
                if con.execute(
                    "SELECT 1 FROM business_import_receipts WHERE import_key=?",
                    (row.import_key,),
                ).fetchone():
                    skipped += 1
                    continue

                product = con.execute(
                    "SELECT id FROM business_products WHERE normalized_name=?",
                    (row.normalized_product,),
                ).fetchone()
                if product:
                    product_id = int(product["id"])
                else:
                    product_id = int(
                        con.execute(
                            """INSERT INTO business_products
                               (name,normalized_name,created_at,updated_at)
                               VALUES(?,?,?,?)""",
                            (row.product, row.normalized_product, stamp, stamp),
                        ).lastrowid
                    )

                tx_id = int(
                    con.execute(
                        """INSERT INTO business_transactions
                           (telegram_id,role,product_id,quantity,unit,total_minor_units,currency,
                            occurred_at,note,recorded_by,source,created_at,updated_at)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            row.telegram_id,
                            row.role,
                            product_id,
                            row.quantity,
                            row.unit,
                            row.total_minor_units,
                            row.currency,
                            row.occurred_at,
                            row.note,
                            recorded_by,
                            "csv_import",
                            stamp,
                            stamp,
                        ),
                    ).lastrowid
                )
                con.execute(
                    "INSERT OR IGNORE INTO tags(telegram_id,tag,created_at) VALUES(?,?,?)",
                    (row.telegram_id, row.role, stamp),
                )
                con.execute(
                    """INSERT INTO relationship_events
                       (telegram_id,event_type,details,created_at) VALUES(?,?,?,?)""",
                    (
                        row.telegram_id,
                        "business_transaction_imported",
                        f"{row.role}:{row.normalized_product}:{row.quantity:g} {row.unit}",
                        stamp,
                    ),
                )
                if recorded_by is not None:
                    con.execute(
                        """INSERT INTO admin_audit
                           (admin_id,action,telegram_id,details,created_at) VALUES(?,?,?,?,?)""",
                        (
                            recorded_by,
                            "business_transaction_imported",
                            row.telegram_id,
                            f"{row.role}:{row.normalized_product}",
                            stamp,
                        ),
                    )
                con.execute(
                    """INSERT INTO business_import_receipts
                       (import_key,transaction_id,source_file,source_row,imported_at)
                       VALUES(?,?,?,?,?)""",
                    (row.import_key, tx_id, source_file[:255], row.source_row, stamp),
                )
                inserted_ids.append(tx_id)

        return ImportResult(
            source_file=source_file,
            inserted=len(inserted_ids),
            skipped_duplicates=skipped,
            transaction_ids=tuple(inserted_ids),
        )

    def apply_file(self, path: Path, *, recorded_by: int | None = None) -> ImportResult:
        text = path.read_text(encoding="utf-8-sig")
        return self.apply_text(text, source_file=path.name, recorded_by=recorded_by)
