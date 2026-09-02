from marketplace import (
    PENDING_CUES,
    SOLD_CUES,
    MarketplaceStore,
    extract_listing,
    is_marketplace_candidate,
)
from core import utc_now


STRONG_AVAILABLE_RELISTING_CUES = (
    "for sale",
    "selling",
    "asking",
    "price",
    "ono",
    "firm",
    "delivery",
    "dm me",
    "pm me",
    "wtb",
    "wanted",
    "wtt",
    "swap",
    "trade for",
    "service available",
    "services available",
)


def _has_any(text, cues):
    lowered = (text or "").lower()
    return any(cue in lowered for cue in cues)


def _existing_for_message(store: MarketplaceStore, chat_id, message_id):
    with store.conn() as c:
        return c.execute(
            "SELECT * FROM marketplace_listings WHERE chat_id=? AND message_id=?",
            (chat_id, message_id),
        ).fetchone()


def _is_status_only_update(text, extraction):
    """Return True only for a short lifecycle edit, not a replacement listing.

    SOLD/pending edits are treated as lifecycle-only when they do not introduce
    a new price. Availability-only edits are also preserved unless they contain
    strong relisting language. Genuine price/relisting edits are fully parsed.
    """
    value = (text or "").strip()
    words = value.split()
    if not value or len(words) > 12 or extraction.price_cents is not None:
        return False

    if _has_any(value, SOLD_CUES) or _has_any(value, PENDING_CUES):
        return True

    lowered = value.lower()
    if "available" not in lowered and "back available" not in lowered:
        return False
    if _has_any(value, STRONG_AVAILABLE_RELISTING_CUES):
        return False
    return True


def reconcile_marketplace_message(
    store: MarketplaceStore,
    chat_id,
    message_id,
    sender_id,
    date_utc,
    text,
):
    """Reconcile one current Telegram message into structured marketplace state.

    Full listing text is parsed normally. Short lifecycle-only edits such as
    ``SOLD`` or ``pending pickup`` preserve previous listing metadata and update
    only lifecycle state. Genuine price/relisting edits are fully re-extracted.
    Messages that no longer represent a listing remove their stale structured
    record.
    """
    text = text or ""
    existing = _existing_for_message(store, chat_id, message_id)
    extraction = extract_listing(text, sender_id=sender_id)

    if existing and _is_status_only_update(text, extraction):
        lowered = text.lower()
        if _has_any(text, SOLD_CUES):
            status = "sold"
        elif _has_any(text, PENDING_CUES):
            status = "pending"
        elif "available" in lowered or "back available" in lowered:
            status = "available"
        else:
            status = existing["status"]
        with store.conn() as c:
            c.execute(
                """UPDATE marketplace_listings
                   SET status=?,last_seen_utc=?
                   WHERE chat_id=? AND message_id=?""",
                (status, date_utc or utc_now(), chat_id, message_id),
            )
            return c.execute(
                "SELECT * FROM marketplace_listings WHERE chat_id=? AND message_id=?",
                (chat_id, message_id),
            ).fetchone()

    if is_marketplace_candidate(extraction):
        return store.ingest(chat_id, message_id, sender_id, date_utc, text)

    if existing:
        store.remove_for_message(chat_id, message_id)
    return None


def rebuild_marketplace_index(core_store, market_store: MarketplaceStore, limit=None):
    sql = "SELECT chat_id,message_id,sender_id,date_utc,text FROM indexed_messages ORDER BY date_utc"
    args = []
    if limit is not None:
        sql += " LIMIT ?"
        args.append(max(1, int(limit)))
    with core_store.conn() as c:
        rows = c.execute(sql, args).fetchall()

    indexed = 0
    for row in rows:
        result = reconcile_marketplace_message(
            market_store,
            row["chat_id"],
            row["message_id"],
            row["sender_id"],
            row["date_utc"],
            row["text"],
        )
        if result:
            indexed += 1
    return indexed
