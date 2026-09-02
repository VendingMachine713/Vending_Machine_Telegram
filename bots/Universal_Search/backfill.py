import argparse
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core import Store
from envutil import load_env
from marketplace import MarketplaceStore
from marketplace_reconcile import reconcile_marketplace_message

BASE = Path(__file__).resolve().parent
DB = BASE / "data" / "universal_search.db"


@dataclass(frozen=True)
class BackfillConfig:
    api_id: int
    api_hash: str
    phone: str | None
    session_path: Path


def load_config() -> BackfillConfig:
    env = load_env(BASE / ".env")
    api_id_raw = env.get("TELEGRAM_API_ID", "").strip()
    api_hash = env.get("TELEGRAM_API_HASH", "").strip()
    phone = env.get("TELEGRAM_PHONE", "").strip() or None
    if not api_id_raw or not api_hash:
        raise SystemExit(
            "Historical backfill requires TELEGRAM_API_ID and TELEGRAM_API_HASH in bots/Universal_Search/.env."
        )
    try:
        api_id = int(api_id_raw)
    except ValueError as exc:
        raise SystemExit("TELEGRAM_API_ID must be an integer.") from exc
    session_path = BASE / "state" / "universal_search_backfill"
    session_path.parent.mkdir(parents=True, exist_ok=True)
    return BackfillConfig(api_id, api_hash, phone, session_path)


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Read-only Telegram history backfill for VM Universal Search.")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--list-chats", action="store_true", help="List accessible dialogs without indexing.")
    mode.add_argument("--chat", help="Backfill one chat by marked ID or username.")
    mode.add_argument("--all", action="store_true", help="Backfill all accessible group/channel dialogs.")
    mode.add_argument("--status", action="store_true", help="Show persisted backfill progress only.")
    p.add_argument("--limit", type=int, default=5000, help="Maximum messages per chat for this run (1-100000).")
    p.add_argument("--days", type=int, help="Stop once messages are older than this many days.")
    p.add_argument("--batch-size", type=int, default=250, help="Checkpoint interval (25-1000).")
    return p.parse_args(argv)


def clamp_args(args):
    args.limit = max(1, min(int(args.limit), 100000))
    args.batch_size = max(25, min(int(args.batch_size), 1000))
    if args.days is not None:
        args.days = max(1, min(int(args.days), 3650))
    return args


def sender_fields(sender):
    if sender is None:
        return None, None, None
    sender_id = getattr(sender, "id", None)
    username = getattr(sender, "username", None)
    first = getattr(sender, "first_name", None) or ""
    last = getattr(sender, "last_name", None) or ""
    title = getattr(sender, "title", None)
    display = title or " ".join(x for x in (first, last) if x).strip() or None
    return sender_id, username, display


def status_text(store: Store) -> str:
    rows = store.backfill_status()
    if not rows:
        return "No historical backfill progress recorded."
    lines = []
    for r in rows:
        lines.append(
            f'{r["chat_id"]} | {r["status"]} | scanned={r["scanned_messages"]} '
            f'| oldest={r["oldest_message_id"] or "-"} | {r["chat_title"] or ""}'
        )
    return "\n".join(lines)


async def backfill_chat(
    client,
    store: Store,
    market: MarketplaceStore,
    entity,
    *,
    limit: int,
    days: int | None,
    batch_size: int,
):
    from telethon import utils

    chat_id = utils.get_peer_id(entity)
    title = getattr(entity, "title", None) or getattr(entity, "first_name", None) or str(chat_id)
    username = getattr(entity, "username", None)
    previous = store.get_backfill_progress(chat_id)
    max_id = int(previous["oldest_message_id"]) if previous and previous["oldest_message_id"] else 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=days) if days else None

    store.record_backfill_progress(chat_id, title, username, status="running")
    scanned_since_checkpoint = 0
    total_this_run = 0
    marketplace_this_run = 0
    oldest_seen = max_id or None

    try:
        async for message in client.iter_messages(entity, limit=limit, max_id=max_id):
            if cutoff and message.date and message.date.astimezone(timezone.utc) < cutoff:
                store.record_backfill_progress(
                    chat_id, title, username, status="complete",
                    oldest_message_id=oldest_seen, scanned_delta=scanned_since_checkpoint,
                )
                return total_this_run, marketplace_this_run

            sender = getattr(message, "sender", None)
            if sender is None and getattr(message, "sender_id", None):
                try:
                    sender = await message.get_sender()
                except Exception:
                    sender = None
            sender_id, sender_username, display_name = sender_fields(sender)
            sender_id = sender_id or getattr(message, "sender_id", None)
            date_utc = (
                message.date.astimezone(timezone.utc).isoformat()
                if message.date else datetime.now(timezone.utc).isoformat()
            )
            text = message.message or ""
            store.upsert(
                chat_id, title, username,
                sender_id,
                sender_username, display_name,
                message.id, date_utc,
                text, bool(message.media),
                source="backfill",
            )
            market_row = reconcile_marketplace_message(
                market, chat_id, message.id, sender_id, date_utc, text
            )
            if market_row:
                marketplace_this_run += 1
            total_this_run += 1
            scanned_since_checkpoint += 1
            oldest_seen = message.id if oldest_seen is None else min(oldest_seen, message.id)

            if scanned_since_checkpoint >= batch_size:
                store.record_backfill_progress(
                    chat_id, title, username, status="running",
                    oldest_message_id=oldest_seen, scanned_delta=scanned_since_checkpoint,
                )
                scanned_since_checkpoint = 0

        store.record_backfill_progress(
            chat_id, title, username, status="complete",
            oldest_message_id=oldest_seen, scanned_delta=scanned_since_checkpoint,
        )
        return total_this_run, marketplace_this_run
    except Exception as exc:
        store.record_backfill_progress(
            chat_id, title, username, status="error",
            oldest_message_id=oldest_seen, scanned_delta=scanned_since_checkpoint,
            error=f"{type(exc).__name__}: {exc}"[:1000],
        )
        raise


async def run(args):
    store = Store(DB)
    market = MarketplaceStore(DB)
    if args.status:
        print(status_text(store))
        return

    cfg = load_config()
    try:
        from telethon import TelegramClient
    except ImportError as exc:
        raise SystemExit("Telethon is not installed. Run: py -m pip install -r requirements.txt") from exc

    client = TelegramClient(str(cfg.session_path), cfg.api_id, cfg.api_hash)
    await client.start(phone=cfg.phone)

    if args.list_chats:
        async for dialog in client.iter_dialogs():
            if dialog.is_group or dialog.is_channel:
                username = getattr(dialog.entity, "username", None)
                print(f"{dialog.id}\t{dialog.name}\t@{username}" if username else f"{dialog.id}\t{dialog.name}")
        await client.disconnect()
        return

    if args.chat:
        try:
            target = int(args.chat)
        except ValueError:
            target = args.chat
        entity = await client.get_entity(target)
        count, marketplace_count = await backfill_chat(
            client, store, market, entity,
            limit=args.limit, days=args.days, batch_size=args.batch_size,
        )
        print(
            f"[OK] Indexed {count} historical messages from {args.chat}; "
            f"structured marketplace candidates={marketplace_count}."
        )
        await client.disconnect()
        return

    async for dialog in client.iter_dialogs():
        if not (dialog.is_group or dialog.is_channel):
            continue
        try:
            count, marketplace_count = await backfill_chat(
                client, store, market, dialog.entity,
                limit=args.limit, days=args.days, batch_size=args.batch_size,
            )
            print(
                f"[OK] {dialog.id} {dialog.name}: {count} historical messages; "
                f"marketplace={marketplace_count}"
            )
        except Exception as exc:
            print(f"[WARN] {dialog.id} {dialog.name}: {type(exc).__name__}: {exc}")

    await client.disconnect()


def main(argv=None):
    args = clamp_args(parse_args(argv))
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
