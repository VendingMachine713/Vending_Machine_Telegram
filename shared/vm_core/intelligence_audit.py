from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3
from typing import Any

from .db import PlatformDB
from .paths import project_root


@dataclass(frozen=True, slots=True)
class AuditQuery:
    event_type_prefix: str | None = "intelligence."
    source: str | None = None
    subject_type: str | None = None
    subject_id: str | None = None
    correlation_id: str | None = None
    limit: int = 100


def _readonly_connect(path: Path) -> sqlite3.Connection | None:
    if not path.exists():
        return None
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    try:
        con = sqlite3.connect(uri, uri=True, timeout=5)
    except sqlite3.Error:
        return None
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only=ON")
    return con


def query_intelligence_events(
    query: AuditQuery | None = None,
    *,
    root: Path | None = None,
) -> list[dict[str, Any]]:
    """Query the VM event ledger without initializing or mutating platform state."""
    root = root or project_root()
    query = query or AuditQuery()
    db_path = PlatformDB(root=root).path
    con = _readonly_connect(db_path)
    if con is None:
        return []
    try:
        table = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='events'"
        ).fetchone()
        if table is None:
            return []

        where: list[str] = []
        params: list[Any] = []
        if query.event_type_prefix:
            where.append("event_type LIKE ?")
            params.append(f"{query.event_type_prefix}%")
        if query.source:
            where.append("source=?")
            params.append(query.source)
        if query.subject_type:
            where.append("subject_type=?")
            params.append(query.subject_type)
        if query.subject_id is not None:
            where.append("subject_id=?")
            params.append(str(query.subject_id))
        if query.correlation_id:
            where.append("correlation_id=?")
            params.append(query.correlation_id)

        sql = "SELECT * FROM events"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(max(1, min(5000, int(query.limit))))
        return [dict(row) for row in con.execute(sql, params).fetchall()]
    finally:
        con.close()


def audit_summary(*, root: Path | None = None, limit: int = 1000) -> dict[str, Any]:
    """Return a compact passive summary of stored canonical intelligence events."""
    rows = query_intelligence_events(AuditQuery(limit=limit), root=root)
    kinds: dict[str, int] = {}
    sources: dict[str, int] = {}
    subjects: dict[str, int] = {}
    confidence_values: list[float] = []

    for row in rows:
        parts = str(row.get("event_type") or "").split(".")
        kind = parts[1] if len(parts) > 1 else "unknown"
        kinds[kind] = kinds.get(kind, 0) + 1
        source = str(row.get("source") or "unknown")
        sources[source] = sources.get(source, 0) + 1
        subject = str(row.get("subject_type") or "unknown")
        subjects[subject] = subjects.get(subject, 0) + 1
        try:
            payload = json.loads(row.get("payload_json") or "{}")
            value = payload.get("confidence")
            if value is not None:
                confidence_values.append(float(value))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue

    return {
        "event_count": len(rows),
        "kinds": dict(sorted(kinds.items())),
        "sources": dict(sorted(sources.items())),
        "subjects": dict(sorted(subjects.items())),
        "mean_confidence": (
            sum(confidence_values) / len(confidence_values)
            if confidence_values else None
        ),
        "read_only": True,
        "automatic_execution": False,
    }
