import html
import re
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core import utc_now

SESSION_SCHEMA = """
CREATE TABLE IF NOT EXISTS marketplace_sessions(
  token TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL,
  chat_scope INTEGER,
  raw_query TEXT NOT NULL,
  global_search INTEGER NOT NULL DEFAULT 0,
  created_utc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_marketplace_sessions_created
  ON marketplace_sessions(created_utc);
"""


def short(value, limit):
    value = str(value or "")
    return value if len(value) <= limit else value[: limit - 1] + "…"


def money(cents, currency="AUD"):
    if cents is None:
        return "Price not listed"
    prefix = "$" if (currency or "AUD") == "AUD" else f"{currency or ''} "
    return f"{prefix}{cents / 100:,.2f}"


def original_message_link(row):
    username = (row["chat_username"] or "").lstrip("@")
    if username and re.fullmatch(r"[A-Za-z0-9_]+", username):
        return f"https://t.me/{username}/{row['message_id']}"
    chat_id = str(row["chat_id"])
    if chat_id.startswith("-100") and len(chat_id) > 4:
        return f"https://t.me/c/{chat_id[4:]}/{row['message_id']}"
    return None


def format_market_row(row):
    chat = short(row["chat_title"] or row["chat_id"], 55)
    title = short(row["title"] or row["text"] or "Marketplace listing", 110)
    status = str(row["status"] or "unknown").replace("_", " ")
    listing_type = str(row["listing_type"] or "unknown").replace("_", " ")
    category = str(row["category"] or "other").replace("_", " ")
    details = [money(row["price_cents"], row["currency"]), status, listing_type, category]
    if row["condition"]:
        details.append(str(row["condition"]).replace("_", " "))
    if row["location_hint"]:
        details.append(f"location: {row['location_hint']}")
    if row["repost_count"] and int(row["repost_count"]) > 1:
        details.append(f"reposts: {row['repost_count']}")
    link = original_message_link(row)
    lines = [
        f"<b>#{row['id']} {html.escape(title)}</b>",
        html.escape(" | ".join(details)),
        f"<i>{html.escape(chat)}</i>",
    ]
    if link:
        lines.append(f'<a href="{html.escape(link, quote=True)}">Open original message</a>')
    return "\n".join(lines)


def render_market_page(rows, page):
    heading = f"<b>Marketplace results — page {page}</b>"
    blocks = [format_market_row(row) for row in rows]
    if not blocks:
        return f"No marketplace matches on page {page}."
    kept = []
    for block in blocks:
        candidate = heading + "\n\n" + "\n\n".join(kept + [block])
        if len(candidate) > 3700:
            break
        kept.append(block)
    suffix = "" if len(kept) == len(blocks) else "\n\n<i>Some result text was shortened for Telegram.</i>"
    return heading + "\n\n" + "\n\n".join(kept) + suffix


class MarketplaceSessionStore:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        with self.conn() as c:
            c.executescript(SESSION_SCHEMA)

    @contextmanager
    def conn(self):
        c = sqlite3.connect(self.db_path, timeout=10)
        c.row_factory = sqlite3.Row
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    def create(self, user_id, chat_scope, raw_query, global_search):
        self.cleanup()
        token = secrets.token_urlsafe(6)
        with self.conn() as c:
            c.execute(
                """INSERT INTO marketplace_sessions(
                       token,user_id,chat_scope,raw_query,global_search,created_utc
                   ) VALUES(?,?,?,?,?,?)""",
                (token, user_id, chat_scope, raw_query, int(bool(global_search)), utc_now()),
            )
        return token

    def get(self, token):
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        with self.conn() as c:
            return c.execute(
                "SELECT * FROM marketplace_sessions WHERE token=? AND created_utc>=?",
                (token, cutoff),
            ).fetchone()

    def cleanup(self):
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        with self.conn() as c:
            return c.execute(
                "DELETE FROM marketplace_sessions WHERE created_utc<?", (cutoff,)
            ).rowcount
