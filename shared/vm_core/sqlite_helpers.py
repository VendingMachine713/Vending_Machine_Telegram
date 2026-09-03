from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Iterator


@contextmanager
def readonly_connection(path: Path, *, timeout: float = 2.0) -> Iterator[sqlite3.Connection]:
    """Open SQLite fail-closed in read-only mode."""
    resolved = Path(path).resolve()
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    con = sqlite3.connect(
        f"file:{resolved.as_posix()}?mode=ro",
        uri=True,
        timeout=max(0.1, float(timeout)),
    )
    con.row_factory = sqlite3.Row
    try:
        yield con
    finally:
        con.close()


def integrity_check(path: Path, *, quick: bool = True) -> str:
    pragma = "quick_check" if quick else "integrity_check"
    with readonly_connection(path) as con:
        row = con.execute(f"PRAGMA {pragma}").fetchone()
    return str(row[0]) if row else "no result"


def table_exists(con: sqlite3.Connection, table: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (str(table),),
    ).fetchone()
    return row is not None


def table_columns(con: sqlite3.Connection, table: str) -> tuple[str, ...]:
    if not table_exists(con, table):
        return ()
    safe = str(table).replace('"', '""')
    return tuple(str(row[1]) for row in con.execute(f'PRAGMA table_info("{safe}")'))


@contextmanager
def write_transaction(con: sqlite3.Connection, *, immediate: bool = True) -> Iterator[sqlite3.Connection]:
    """Explicit transaction helper for bot-owned DB code that opts into VM Core."""
    if con.in_transaction:
        raise RuntimeError("connection already has an active transaction")
    con.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
    try:
        yield con
    except Exception:
        con.rollback()
        raise
    else:
        con.commit()
