"""Conservative, passive marketplace intelligence for Universal Search.

This module never sends Telegram messages.  It converts indexed text into a
small canonical listing record suitable for owner-only read APIs and Brain
aggregate signals.  Low-confidence text stays searchable but is not treated as
an actionable listing.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone

PRICE_RE = re.compile(r"(?P<currency>AUD|AU\$|\$)\s*(?P<amount>\d{2,7}(?:[,.]\d{1,2})?)", re.I)
STATUS_RE = {
    "sold": re.compile(r"\b(sold|no longer available|gone)\b", re.I),
    "pending": re.compile(r"\b(pending|on hold|deposit taken)\b", re.I),
    "available": re.compile(r"\b(available|still available|back available)\b", re.I),
}
KIND_CUES = {
    "wanted": re.compile(r"\b(wtb|wanted|looking for|in search of)\b", re.I),
    "trade": re.compile(r"\b(wtt|swap|trade)\b", re.I),
    "service": re.compile(r"\b(service|repair|install|mechanic|plumber|cleaning)\b", re.I),
}
CONDITION_RE = re.compile(r"\b(new|used|excellent condition|good condition|parts only|reconditioned)\b", re.I)
LOCATION_RE = re.compile(r"\b(?:located? in|pickup in|pick up in|at)\s+([A-Za-z][A-Za-z .'-]{2,40})", re.I)


@dataclass(frozen=True)
class Listing:
    listing_key: str
    group_key: str
    kind: str
    status: str
    price_cents: int | None
    currency: str | None
    condition: str | None
    location: str | None
    confidence: float


def _normal(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", text.lower())).strip()


def _price(text: str):
    match = PRICE_RE.search(text)
    if not match:
        return None, None
    amount = match.group("amount").replace(",", "")
    try:
        cents = round(float(amount) * 100)
    except ValueError:
        return None, None
    return cents, "AUD"


def extract_listing(chat_id: int, message_id: int, text: str) -> Listing | None:
    """Extract a listing only when at least two marketplace cues are present."""
    raw = (text or "").strip()
    if not raw:
        return None
    normalized = _normal(raw)
    price_cents, currency = _price(raw)
    kind = "sale"
    for candidate, pattern in KIND_CUES.items():
        if pattern.search(raw):
            kind = candidate
            break
    cues = int(price_cents is not None) + sum(bool(p.search(raw)) for p in KIND_CUES.values())
    cues += int(bool(re.search(r"\b(selling|for sale|available|wanted|swap|trade|service)\b", raw, re.I)))
    if cues < 2:
        return None
    status = "available" if STATUS_RE["available"].search(raw) else "active"
    if STATUS_RE["pending"].search(raw):
        status = "pending"
    if STATUS_RE["sold"].search(raw):
        status = "sold"
    condition_match = CONDITION_RE.search(raw)
    location_match = LOCATION_RE.search(raw)
    # Group reposts by seller-independent normalized content, excluding price.
    no_price = PRICE_RE.sub(" ", normalized)
    no_price = re.sub(r"\b\d{2,7}\b", " ", no_price)
    no_price = re.sub(r"\b(sold|available|still available|back available|pending|on hold|deposit taken)\b", " ", no_price)
    group_key = hashlib.sha256(no_price.encode("utf-8")).hexdigest()[:24]
    listing_key = hashlib.sha256(f"{chat_id}:{message_id}".encode()).hexdigest()[:32]
    confidence = min(0.99, 0.55 + (0.12 * cues) + (0.08 if price_cents is not None else 0))
    return Listing(listing_key, group_key, kind, status, price_cents, currency,
                   condition_match.group(1).lower() if condition_match else None,
                   location_match.group(1).strip() if location_match else None,
                   round(confidence, 2))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
