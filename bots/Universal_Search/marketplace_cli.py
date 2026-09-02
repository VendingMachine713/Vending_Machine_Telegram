import argparse
from pathlib import Path

from core import Store
from marketplace import MarketplaceStore, parse_market_query
from marketplace_reconcile import rebuild_marketplace_index

BASE = Path(__file__).resolve().parent
DB = BASE / "data" / "universal_search.db"


def money(cents, currency):
    if cents is None:
        return "-"
    prefix = "$" if (currency or "AUD") == "AUD" else f"{currency or ''} "
    return f"{prefix}{cents / 100:,.2f}"


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="VM Universal Search marketplace intelligence maintenance.")
    sub = parser.add_subparsers(dest="command", required=True)

    rebuild = sub.add_parser("rebuild", help="Extract listings from the existing Universal Search index.")
    rebuild.add_argument("--limit", type=int)

    search = sub.add_parser("search", help="Search structured marketplace listings.")
    search.add_argument("query", nargs="*")
    search.add_argument("--chat", type=int)

    listing = sub.add_parser("listing", help="Show one structured listing by listing ID.")
    listing.add_argument("id", type=int)

    history = sub.add_parser("price-history", help="Show logical-listing price history.")
    history.add_argument("id", type=int)

    stats = sub.add_parser("stats", help="Show marketplace index statistics.")
    stats.add_argument("--chat", type=int)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    core = Store(DB)
    market = MarketplaceStore(DB)

    if args.command == "rebuild":
        count = rebuild_marketplace_index(core, market, args.limit)
        print(f"[OK] Structured marketplace listings indexed: {count}")
        return

    if args.command == "search":
        q = parse_market_query(" ".join(args.query))
        rows, more = market.search(q, args.chat)
        for row in rows:
            print(
                f"#{row['id']} | {row['listing_type']} | {row['status']} | {row['category']} | "
                f"{money(row['price_cents'], row['currency'])} | {row['chat_title'] or row['chat_id']} | "
                f"{row['title'] or '(untitled)'}"
            )
        if more:
            print(f"[MORE] Additional results exist after page {q.page}.")
        return

    if args.command == "listing":
        row = market.get_listing(args.id)
        if not row:
            raise SystemExit("Listing not found.")
        for key in (
            "id", "listing_type", "status", "category", "title", "price_cents", "currency",
            "condition", "location_hint", "confidence", "logical_listing_id", "repost_count",
            "chat_title", "sender_username", "date_utc", "text",
        ):
            print(f"{key}: {row[key]}")
        return

    if args.command == "price-history":
        listing, rows = market.price_history_for_listing(args.id)
        if not listing:
            raise SystemExit("Listing not found.")
        print(f"Listing #{listing['id']} logical={listing['logical_listing_id']} {listing['title'] or ''}")
        if not rows:
            print("No recorded price history.")
            return
        for row in rows:
            print(
                f"{row['observed_utc']} | {money(row['price_cents'], row['currency'])} | "
                f"chat={row['chat_id']} message={row['message_id']}"
            )
        return

    totals, categories = market.stats(args.chat)
    print(
        f"total={totals['total'] or 0} available={totals['available'] or 0} "
        f"wanted={totals['wanted'] or 0}"
    )
    for row in categories:
        print(f"{row['category']}: {row['count']}")


if __name__ == "__main__":
    main()
