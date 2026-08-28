from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from telethon import TelegramClient, events
from telethon.errors import FloodWaitError
from telethon.tl.types import User

from config import Settings
from relationship_engine import RelationshipEngine

log = logging.getLogger(__name__)


def _display_name(user: User) -> str | None:
    return " ".join(
        p for p in [getattr(user, "first_name", None), getattr(user, "last_name", None)] if p
    ).strip() or None


class TelegramMonitor:
    def __init__(self, settings: Settings, engine: RelationshipEngine):
        self.settings = settings
        self.engine = engine
        self.client = TelegramClient(
            settings.session_name,
            settings.api_id,
            settings.api_hash,
            auto_reconnect=True,
            connection_retries=None,
            retry_delay=5,
        )
        self.ready = asyncio.Event()
        self._bootstrap_lock = asyncio.Lock()
        self._bootstrap_task: asyncio.Task | None = None

    async def start(self):
        await self.client.start(phone=self.settings.phone)
        me = await self.client.get_me()
        log.info(
            "Telethon monitor authorised as %s (%s)",
            getattr(me, "username", None),
            me.id,
        )
        self.ready.set()

        @self.client.on(events.NewMessage(incoming=True))
        async def handler(event):
            try:
                sender = await event.get_sender()
                if not isinstance(sender, User) or sender.bot:
                    return

                chat = await event.get_chat()
                chat_id = getattr(event, "chat_id", None)
                chat_title = (
                    getattr(chat, "title", None)
                    or getattr(chat, "username", None)
                )

                self.engine.upsert_interaction(
                    telegram_id=sender.id,
                    username=getattr(sender, "username", None),
                    display_name=_display_name(sender),
                    chat_id=chat_id,
                    chat_title=chat_title,
                    occurred_at=event.date,
                )
            except Exception:
                log.exception("Failed processing Telegram event")

        # Populate useful existing contacts in the background without blocking
        # the live event listener. Historical bootstrap seeds identities and
        # group links but does not inflate interaction counters.
        self._bootstrap_task = asyncio.create_task(
            self.bootstrap_recent_history(),
            name="relationship-bootstrap",
        )

        await self.client.run_until_disconnected()

    async def resolve_contact(self, query: str):
        """Resolve @username or a known Telegram ID and seed it into the DB."""
        if not self.ready.is_set():
            return None

        raw = query.strip()
        target = raw
        if raw.startswith("@"):
            target = raw
        elif raw.isdigit():
            target = int(raw)
        else:
            # Global Telegram entity resolution is reliable for usernames/IDs,
            # not arbitrary display-name text.
            target = f"@{raw}"

        try:
            entity = await self.client.get_entity(target)
        except Exception as exc:
            log.info("Telegram contact resolve failed for %r: %s", query, exc)
            return None

        if not isinstance(entity, User) or entity.bot:
            return None

        row = self.engine.upsert_identity(
            telegram_id=entity.id,
            username=getattr(entity, "username", None),
            display_name=_display_name(entity),
            observed_at=datetime.now(timezone.utc),
            source="direct_username_lookup",
        )
        self.engine.recalculate_contact(entity.id)
        log.info(
            "Resolved contact %r -> %s (@%s)",
            query,
            entity.id,
            getattr(entity, "username", None),
        )
        return row

    async def bootstrap_recent_history(
        self,
        max_dialogs: int = 60,
        messages_per_dialog: int = 20,
    ):
        """Seed identities from accessible dialogs/recent history.

        This is deliberately conservative to reduce Telegram API load. It can be
        run again manually from the admin bot with /rescan.
        """
        if not self.ready.is_set():
            try:
                await asyncio.wait_for(self.ready.wait(), timeout=60)
            except asyncio.TimeoutError:
                log.warning("Bootstrap skipped: Telethon monitor not ready")
                return {"dialogs": 0, "contacts": 0}

        if self._bootstrap_lock.locked():
            return {"dialogs": 0, "contacts": 0, "status": "already_running"}

        dialogs_scanned = 0
        seeded_ids: set[int] = set()

        async with self._bootstrap_lock:
            log.info(
                "Relationship bootstrap started: up to %s dialogs, %s messages each",
                max_dialogs,
                messages_per_dialog,
            )

            try:
                async for dialog in self.client.iter_dialogs(limit=max_dialogs):
                    dialogs_scanned += 1
                    entity = dialog.entity
                    chat_id = getattr(dialog, "id", None)
                    chat_title = (
                        getattr(dialog, "name", None)
                        or getattr(entity, "title", None)
                        or getattr(entity, "username", None)
                    )

                    # Private-user dialogs can be seeded immediately.
                    if isinstance(entity, User) and not entity.bot:
                        self.engine.upsert_identity(
                            telegram_id=entity.id,
                            username=getattr(entity, "username", None),
                            display_name=_display_name(entity),
                            observed_at=datetime.now(timezone.utc),
                            chat_id=chat_id,
                            chat_title=chat_title,
                            source="dialog_bootstrap",
                        )
                        seeded_ids.add(entity.id)

                    try:
                        async for message in self.client.iter_messages(
                            entity,
                            limit=messages_per_dialog,
                        ):
                            sender = await message.get_sender()
                            if not isinstance(sender, User) or sender.bot:
                                continue

                            observed_at = message.date or datetime.now(timezone.utc)
                            self.engine.upsert_identity(
                                telegram_id=sender.id,
                                username=getattr(sender, "username", None),
                                display_name=_display_name(sender),
                                observed_at=observed_at,
                                chat_id=chat_id,
                                chat_title=chat_title,
                                source="recent_history_bootstrap",
                            )
                            seeded_ids.add(sender.id)
                    except FloodWaitError as exc:
                        wait_for = min(int(exc.seconds) + 1, 120)
                        log.warning(
                            "Telegram flood wait during bootstrap: sleeping %ss",
                            wait_for,
                        )
                        await asyncio.sleep(wait_for)
                    except Exception as exc:
                        # Some chats may restrict history/participants. Skip
                        # those without killing the whole monitor.
                        log.debug(
                            "Bootstrap skipped dialog %r: %s",
                            chat_title,
                            exc,
                        )

                    await asyncio.sleep(0.05)

            except Exception:
                log.exception("Relationship bootstrap failed")
            finally:
                for telegram_id in seeded_ids:
                    try:
                        self.engine.recalculate_contact(telegram_id)
                    except Exception:
                        log.exception(
                            "Failed recalculating seeded contact %s",
                            telegram_id,
                        )

                log.info(
                    "Relationship bootstrap complete: dialogs=%s contacts=%s",
                    dialogs_scanned,
                    len(seeded_ids),
                )

        return {"dialogs": dialogs_scanned, "contacts": len(seeded_ids)}

    async def stop(self):
        if self._bootstrap_task and not self._bootstrap_task.done():
            self._bootstrap_task.cancel()
            await asyncio.gather(self._bootstrap_task, return_exceptions=True)
        await self.client.disconnect()
