import hashlib
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from core import utc_now

MARKET_SCHEMA = """
CREATE TABLE IF NOT EXISTS marketplace_listings(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  chat_id INTEGER NOT NULL,
  message_id INTEGER NOT NULL,
  sender_id INTEGER,
  listing_type TEXT NOT NULL DEFAULT 'unknown',
  title TEXT,
  category TEXT NOT NULL DEFAULT 'other',
  price_cents INTEGER,
  currency TEXT,
  condition TEXT,
  location_hint TEXT,
  status TEXT NOT NULL DEFAULT 'unknown',
  confidence REAL NOT NULL DEFAULT 0.0,
  logical_listing_id TEXT NOT NULL,
  fingerprint TEXT NOT NULL,
  first_seen_utc TEXT NOT NULL,
  last_seen_utc TEXT NOT NULL,
  UNIQUE(chat_id,message_id)
);
CREATE INDEX IF NOT EXISTS ix_market_type ON marketplace_listings(listing_type,status);
CREATE INDEX IF NOT EXISTS ix_market_price ON marketplace_listings(currency,price_cents);
CREATE INDEX IF NOT EXISTS ix_market_category ON marketplace_listings(category,status);
CREATE INDEX IF NOT EXISTS ix_market_logical ON marketplace_listings(logical_listing_id);
CREATE INDEX IF NOT EXISTS ix_market_sender ON marketplace_listings(sender_id,last_seen_utc DESC);

CREATE TABLE IF NOT EXISTS marketplace_price_history(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  logical_listing_id TEXT NOT NULL,
  chat_id INTEGER NOT NULL,
  message_id INTEGER NOT NULL,
  price_cents INTEGER NOT NULL,
  currency TEXT NOT NULL,
  observed_utc TEXT NOT NULL,
  UNIQUE(logical_listing_id,chat_id,message_id,price_cents)
);
CREATE INDEX IF NOT EXISTS ix_market_price_history_logical
  ON marketplace_price_history(logical_listing_id,observed_utc);
"""

LISTING_TYPES = {"sale", "wanted", "service", "trade", "unknown"}
STATUSES = {"available", "wanted", "pending", "sold", "unavailable", "unknown"}
MARKET_SORTS = {"relevant", "newest", "oldest", "price-asc", "price-desc"}

CATEGORY_RULES = {
    "vehicles_parts": (
        "car", "vehicle", "ute", "sedan", "wagon", "4wd", "4x4", "hilux", "commodore",
        "falcon", "engine", "gearbox", "wheel", "wheels", "tyre", "tyres", "rim", "rims",
        "exhaust", "bumper", "headlight", "tail light", "suspension", "turbo", "motorbike",
        "motorcycle", "trailer",
    ),
    "electronics": (
        "iphone", "ipad", "phone", "samsung", "galaxy", "laptop", "computer", "pc ",
        "playstation", "ps5", "xbox", "switch", "tablet", "monitor", "camera", "tv ",
        "television", "speaker", "headphones", "airpods",
    ),
    "tools": (
        "tool", "drill", "grinder", "saw", "welder", "socket", "spanner", "makita",
        "milwaukee", "dewalt", "ryobi", "compressor",
    ),
    "home": (
        "couch", "sofa", "table", "chair", "bed", "mattress", "fridge", "freezer",
        "washing machine", "dryer", "microwave", "furniture", "cabinet", "desk",
    ),
    "clothing": (
        "shirt", "hoodie", "jacket", "pants", "jeans", "shoes", "sneakers", "boots",
        "dress", "clothing", "clothes",
    ),
    "services": (
        "service", "repair", "repairs", "installation", "install", "cleaning", "gardening",
        "maintenance", "delivery service", "detailing", "mechanic", "towing",
    ),
}

SALE_CUES = (
    "for sale", "selling", "sell ", "available", "price", "asking", "ono", "firm",
    "pickup", "pick up", "delivery", "dm me", "pm me",
)
WANTED_CUES = (
    "wtb", "wanted", "want to buy", "looking for", "looking to buy", "chasing", "after a ",
    "after an ", "need a ", "need an ",
)
TRADE_CUES = ("wtt", "swap", "swaps", "trade for", "trade only", "open to trades")
SERVICE_CUES = (
    "services available", "service available", "offering services", "repairs available",
    "installation available", "mobile mechanic", "we repair", "i repair", "can repair",
)
SOLD_CUES = ("sold", "gone", "no longer available", "not available", "unavailable")
PENDING_CUES = ("pending pickup", "pending pick up", "pending sale", "deposit taken", "on hold")

PRICE_RE = re.compile(
    r"(?i)(?:\bAUD\s*\$?|\bA\$|\$)\s*"
    r"(?P<amount>\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)\s*(?P<k>k)?\b"
)
PRICE_WORD_RE = re.compile(
    r"(?i)\b(?:price|asking|ask|ono|firm)\s*(?:is|:|-)?\s*"
    r"(?:AUD\s*\$?|A\$|\$)?\s*"
    r"(?P<amount>\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)\s*(?P<k>k)?\b"
)
LOCATION_RE = re.compile(
    r"(?i)\b(?:pickup|pick\s*up|located|location|collection)\s*"
    r"(?:from|in|at|:|-)?\s*([A-Za-z][A-Za-z0-9 .'-]{2,45})"
)


@dataclass(frozen=True)
class ListingExtraction:
    listing_type: str
    title: str | None
    category: str
    price_cents: int | None
    currency: str | None
    condition: str | None
    location_hint: str | None
    status: str
    confidence: float
    fingerprint: str
    logical_listing_id: str


@dataclass
class MarketQuery:
    text: str = ""
    listing_type: str | None = None
    category: str | None = None
    status: str | None = None
    min_price_cents: int | None = None
    max_price_cents: int | None = None
    user: str | None = None
    sort: str = "relevant"
    limit: int = 10
    page: int = 1

    @property
    def offset(self):
        return (self.page - 1) * self.limit


def _normalise_space(value):
    return re.sub(r"\s+", " ", value or "").strip()


def _parse_money_number(amount, suffix):
    try:
        value = float(amount.replace(",", ""))
    except (AttributeError, ValueError):
        return None
    if suffix:
        value *= 1000
    if value <= 0 or value > 10_000_000:
        return None
    return int(round(value * 100))


def extract_price(text):
    text = text or ""
    for pattern in (PRICE_RE, PRICE_WORD_RE):
        for match in pattern.finditer(text):
            cents = _parse_money_number(match.group("amount"), match.group("k"))
            if cents is not None:
                return cents, "AUD"
    return None, None


def detect_listing_type(text):
    lowered = " " + (text or "").lower() + " "
    if any(cue in lowered for cue in WANTED_CUES):
        return "wanted"
    if any(cue in lowered for cue in TRADE_CUES):
        return "trade"
    if any(cue in lowered for cue in SERVICE_CUES):
        return "service"
    price_cents, _ = extract_price(text)
    if any(cue in lowered for cue in SALE_CUES) or price_cents is not None:
        return "sale"
    return "unknown"


def detect_status(text, listing_type):
    lowered = (text or "").lower()
    if any(cue in lowered for cue in SOLD_CUES):
        return "sold"
    if any(cue in lowered for cue in PENDING_CUES):
        return "pending"
    if listing_type == "wanted":
        return "wanted"
    if listing_type in {"sale", "service", "trade"}:
        return "available"
    return "unknown"


def detect_condition(text):
    lowered = (text or "").lower()
    if any(cue in lowered for cue in ("brand new", "bnib", "new in box", "unused", "never used")):
        return "new"
    if any(cue in lowered for cue in ("refurbished", "refurb", "reconditioned")):
        return "refurbished"
    if any(cue in lowered for cue in ("as new", "like new", "near new")):
        return "like_new"
    if any(cue in lowered for cue in ("used", "second hand", "pre-owned", "preowned")):
        return "used"
    if "good condition" in lowered:
        return "good"
    if any(cue in lowered for cue in ("damaged", "for parts", "parts only", "not working", "broken")):
        return "damaged"
    return None


def detect_category(text, listing_type):
    lowered = " " + (text or "").lower() + " "
    if listing_type == "service":
        return "services"
    best = ("other", 0)
    for category, keywords in CATEGORY_RULES.items():
        score = sum(1 for keyword in keywords if keyword in lowered)
        if score > best[1]:
            best = (category, score)
    return best[0]


def extract_location_hint(text):
    match = LOCATION_RE.search(text or "")
    if not match:
        return None
    value = match.group(1)
    value = re.split(r"[\n\r,;.!?]|\s+(?:price|asking|cash|today|only)\b", value, maxsplit=1, flags=re.I)[0]
    return _normalise_space(value)[:45] or None


def extract_title(text):
    lines = [_normalise_space(line) for line in (text or "").splitlines() if _normalise_space(line)]
    candidate = lines[0] if lines else _normalise_space(text)
    candidate = re.sub(r"(?i)^\s*(?:for sale|selling|sold|wtb|wanted|wtt|swap|trade)\s*[:\-–—]*\s*", "", candidate)
    candidate = PRICE_RE.sub("", candidate)
    candidate = _normalise_space(candidate).strip(" -–—:|•")
    if not candidate:
        return None
    return candidate[:120]


def canonical_fingerprint_text(text):
    value = (text or "").lower()
    value = re.sub(r"https?://\S+|t\.me/\S+", " ", value)
    value = PRICE_RE.sub(" <price> ", value)
    value = PRICE_WORD_RE.sub(" <price> ", value)
    value = re.sub(r"@\w+", " ", value)
    value = re.sub(r"\b(?:dm|pm)\s+me\b", " ", value)
    value = re.sub(r"\b0?4\d{8}\b", " ", value)
    value = re.sub(r"[^a-z0-9<>]+", " ", value)
    words = value.split()
    return " ".join(words[:80])


def extract_listing(text, *, sender_id=None):
    text = text or ""
    listing_type = detect_listing_type(text)
    price_cents, currency = extract_price(text)
    status = detect_status(text, listing_type)
    category = detect_category(text, listing_type)
    condition = detect_condition(text)
    location_hint = extract_location_hint(text)
    title = extract_title(text)

    canonical = canonical_fingerprint_text(text)
    fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]
    owner_component = str(sender_id) if sender_id is not None else "unknown"
    logical_source = f"{owner_component}|{canonical}"
    logical_listing_id = hashlib.sha256(logical_source.encode("utf-8")).hexdigest()[:24]

    signals = 0
    if listing_type != "unknown":
        signals += 2
    if price_cents is not None:
        signals += 2
    if category != "other":
        signals += 1
    if condition:
        signals += 1
    if location_hint:
        signals += 1
    if title:
        signals += 1
    confidence = min(1.0, signals / 7.0)

    return ListingExtraction(
        listing_type=listing_type,
        title=title,
        category=category,
        price_cents=price_cents,
        currency=currency,
        condition=condition,
        location_hint=location_hint,
        status=status,
        confidence=confidence,
        fingerprint=fingerprint,
        logical_listing_id=logical_listing_id,
    )


def is_marketplace_candidate(extraction):
    return extraction.listing_type != "unknown" or extraction.price_cents is not None


def parse_market_query(raw):
    raw = raw or ""
    listing_type = None
    category = None
    status = None
    user = None
    min_price = None
    max_price = None
    sort = "relevant"
    limit = 10
    page = 1

    def capture(name):
        return re.search(rf"--{name}\s+(\S+)", raw, flags=re.I)

    match = capture("type")
    if match and match.group(1).lower() in LISTING_TYPES:
        listing_type = match.group(1).lower()
    match = capture("category")
    if match:
        category = re.sub(r"[^a-z0-9_]+", "_", match.group(1).lower()).strip("_") or None
    match = capture("status")
    if match and match.group(1).lower() in STATUSES:
        status = match.group(1).lower()
    match = capture("user")
    if match:
        user = match.group(1).lstrip("@").lower()
    match = capture("min")
    if match:
        min_price = _parse_money_number(match.group(1).replace("$", ""), None)
    match = capture("max")
    if match:
        max_price = _parse_money_number(match.group(1).replace("$", ""), None)
    match = capture("sort")
    if match and match.group(1).lower() in MARKET_SORTS:
        sort = match.group(1).lower()
    match = capture("limit")
    if match and match.group(1).isdigit():
        limit = max(1, min(int(match.group(1)), 25))
    match = capture("page")
    if match and match.group(1).isdigit():
        page = max(1, min(int(match.group(1)), 10000))

    text = re.sub(
        r"--(?:type|category|status|user|min|max|sort|limit|page)\s+\S+|--global",
        " ", raw, flags=re.I,
    )
    text = _normalise_space(text)
    return MarketQuery(
        text=text,
        listing_type=listing_type,
        category=category,
        status=status,
        min_price_cents=min_price,
        max_price_cents=max_price,
        user=user,
        sort=sort,
        limit=limit,
        page=page,
    )


class MarketplaceStore:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        with self.conn() as c:
            c.executescript(MARKET_SCHEMA)

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

    def ingest(self, chat_id, message_id, sender_id, date_utc, text):
        extraction = extract_listing(text, sender_id=sender_id)
        if not is_marketplace_candidate(extraction):
            return None
        now = utc_now()
        with self.conn() as c:
            existing = c.execute(
                "SELECT * FROM marketplace_listings WHERE chat_id=? AND message_id=?",
                (chat_id, message_id),
            ).fetchone()
            first_seen = existing["first_seen_utc"] if existing else (date_utc or now)
            c.execute(
                """INSERT INTO marketplace_listings(
                       chat_id,message_id,sender_id,listing_type,title,category,price_cents,currency,
                       condition,location_hint,status,confidence,logical_listing_id,fingerprint,
                       first_seen_utc,last_seen_utc
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(chat_id,message_id) DO UPDATE SET
                       sender_id=excluded.sender_id,
                       listing_type=excluded.listing_type,
                       title=excluded.title,
                       category=excluded.category,
                       price_cents=excluded.price_cents,
                       currency=excluded.currency,
                       condition=excluded.condition,
                       location_hint=excluded.location_hint,
                       status=excluded.status,
                       confidence=excluded.confidence,
                       logical_listing_id=excluded.logical_listing_id,
                       fingerprint=excluded.fingerprint,
                       last_seen_utc=excluded.last_seen_utc""",
                (
                    chat_id, message_id, sender_id, extraction.listing_type, extraction.title,
                    extraction.category, extraction.price_cents, extraction.currency,
                    extraction.condition, extraction.location_hint, extraction.status,
                    extraction.confidence, extraction.logical_listing_id, extraction.fingerprint,
                    first_seen, now,
                ),
            )
            if extraction.price_cents is not None and extraction.currency:
                c.execute(
                    """INSERT OR IGNORE INTO marketplace_price_history(
                           logical_listing_id,chat_id,message_id,price_cents,currency,observed_utc
                       ) VALUES(?,?,?,?,?,?)""",
                    (
                        extraction.logical_listing_id, chat_id, message_id,
                        extraction.price_cents, extraction.currency, date_utc or now,
                    ),
                )
            return c.execute(
                "SELECT * FROM marketplace_listings WHERE chat_id=? AND message_id=?",
                (chat_id, message_id),
            ).fetchone()

    def remove_for_message(self, chat_id, message_id):
        with self.conn() as c:
            return c.execute(
                "DELETE FROM marketplace_listings WHERE chat_id=? AND message_id=?",
                (chat_id, message_id),
            ).rowcount > 0

    def search(self, q: MarketQuery, chat_scope=None):
        args = []
        sql = """SELECT l.*,m.text,m.date_utc,m.has_media,
                        c.title chat_title,c.username chat_username,
                        s.username sender_username,s.display_name,
                        (SELECT COUNT(*) FROM marketplace_listings lr
                         WHERE lr.logical_listing_id=l.logical_listing_id) AS repost_count
                 FROM marketplace_listings l
                 JOIN indexed_messages m ON m.chat_id=l.chat_id AND m.message_id=l.message_id
                 LEFT JOIN chats c ON c.chat_id=l.chat_id
                 LEFT JOIN senders s ON s.sender_id=l.sender_id
                 WHERE 1=1"""
        if chat_scope is not None:
            sql += " AND l.chat_id=?"
            args.append(chat_scope)
        if q.text:
            for term in re.findall(r"\w+", q.text.lower()):
                sql += " AND lower(m.text) LIKE ?"
                args.append("%" + term + "%")
        if q.listing_type:
            sql += " AND l.listing_type=?"
            args.append(q.listing_type)
        if q.category:
            sql += " AND l.category=?"
            args.append(q.category)
        if q.status:
            sql += " AND l.status=?"
            args.append(q.status)
        if q.user:
            sql += " AND lower(COALESCE(s.username,''))=?"
            args.append(q.user)
        if q.min_price_cents is not None:
            sql += " AND l.price_cents>=?"
            args.append(q.min_price_cents)
        if q.max_price_cents is not None:
            sql += " AND l.price_cents<=?"
            args.append(q.max_price_cents)

        if q.sort == "oldest":
            sql += " ORDER BY m.date_utc ASC,l.id ASC"
        elif q.sort == "newest":
            sql += " ORDER BY m.date_utc DESC,l.id DESC"
        elif q.sort == "price-asc":
            sql += " ORDER BY l.price_cents IS NULL,l.price_cents ASC,m.date_utc DESC"
        elif q.sort == "price-desc":
            sql += " ORDER BY l.price_cents IS NULL,l.price_cents DESC,m.date_utc DESC"
        else:
            sql += " ORDER BY l.confidence DESC,(l.status='available') DESC,m.date_utc DESC"
        sql += " LIMIT ? OFFSET ?"
        args.extend([q.limit + 1, q.offset])
        with self.conn() as c:
            rows = c.execute(sql, args).fetchall()
        return rows[:q.limit], len(rows) > q.limit

    def get_listing(self, listing_id):
        with self.conn() as c:
            return c.execute(
                """SELECT l.*,m.text,m.date_utc,m.has_media,
                          c.title chat_title,c.username chat_username,
                          s.username sender_username,s.display_name,
                          (SELECT COUNT(*) FROM marketplace_listings lr
                           WHERE lr.logical_listing_id=l.logical_listing_id) AS repost_count
                   FROM marketplace_listings l
                   JOIN indexed_messages m ON m.chat_id=l.chat_id AND m.message_id=l.message_id
                   LEFT JOIN chats c ON c.chat_id=l.chat_id
                   LEFT JOIN senders s ON s.sender_id=l.sender_id
                   WHERE l.id=?""",
                (listing_id,),
            ).fetchone()

    def price_history_for_listing(self, listing_id):
        listing = self.get_listing(listing_id)
        if not listing:
            return None, []
        with self.conn() as c:
            rows = c.execute(
                """SELECT * FROM marketplace_price_history
                   WHERE logical_listing_id=? ORDER BY observed_utc,id""",
                (listing["logical_listing_id"],),
            ).fetchall()
        return listing, rows

    def stats(self, chat_scope=None):
        args = []
        where = ""
        if chat_scope is not None:
            where = " WHERE chat_id=?"
            args.append(chat_scope)
        with self.conn() as c:
            totals = c.execute(
                "SELECT COUNT(*) total, SUM(status='available') available, "
                "SUM(listing_type='wanted') wanted FROM marketplace_listings" + where,
                args,
            ).fetchone()
            categories = c.execute(
                "SELECT category,COUNT(*) count FROM marketplace_listings" + where +
                " GROUP BY category ORDER BY count DESC,category LIMIT 8",
                args,
            ).fetchall()
        return totals, categories

    def rebuild_from_index(self, limit=None):
        sql = "SELECT chat_id,message_id,sender_id,date_utc,text FROM indexed_messages ORDER BY date_utc"
        args = []
        if limit is not None:
            sql += " LIMIT ?"
            args.append(max(1, int(limit)))
        with self.conn() as c:
            rows = c.execute(sql, args).fetchall()
        indexed = 0
        for row in rows:
            if self.ingest(
                row["chat_id"], row["message_id"], row["sender_id"], row["date_utc"], row["text"]
            ):
                indexed += 1
        return indexed
