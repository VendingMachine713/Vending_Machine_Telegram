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
        self.self_user_id: int | None = None
        self._bootstrap_lock = asyncio.Lock()
        self._bootstrap_task: asyncio.Task | None = None

    async def start(self):
        await self.client.start(phone=self.settings.phone)
        me = await self.client.get_me()
        self.self_user_id = me.id
        self.engine.db.set_meta("monitor_self_user_id", str(me.id))
        # Never treat the authorised monitoring account as one of its own CRM contacts.
        if self.engine.db.one("SELECT 1 FROM contacts WHERE telegram_id=?", (me.id,)):
            self.engine.privacy.set_excluded(me.id, True, "monitoring account self-record")
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
                if self.self_user_id is not None and sender.id == self.self_user_id:
                    return
                if self.engine.privacy.is_excluded(sender.id):
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

                if getattr(event, "is_private", False):
                    self.engine.record_private_interaction(
                        telegram_id=sender.id,
                        chat_id=chat_id,
                        message_id=event.id,
                        direction="incoming",
                        occurred_at=event.date,
                    )
            except Exception:
                log.exception("Failed processing Telegram event")

        @self.client.on(events.NewMessage(outgoing=True))
        async def outgoing_handler(event):
            try:
                if not getattr(event, "is_private", False):
                    return
                chat = await event.get_chat()
                if not isinstance(chat, User) or chat.bot:
                    return
                if self.engine.privacy.is_excluded(chat.id):
                    return
                chat_id = getattr(event, "chat_id", None)
                if chat_id is None:
                    return
                # Seed identity if this is a private contact not yet known, then
                # record direction/timing metadata only. Message content is not stored.
                self.engine.upsert_identity(
                    telegram_id=chat.id,
                    username=getattr(chat, "username", None),
                    display_name=_display_name(chat),
                    observed_at=event.date,
                    chat_id=chat_id,
                    chat_title=getattr(chat, "username", None) or _display_name(chat),
                    source="private_outgoing",
                )
                # Private outgoing messages are genuine relationship activity too.
                self.engine.upsert_interaction(
                    telegram_id=chat.id,
                    username=getattr(chat, "username", None),
                    display_name=_display_name(chat),
                    chat_id=chat_id,
                    chat_title=getattr(chat, "username", None) or _display_name(chat),
                    occurred_at=event.date,
                )
                self.engine.record_private_interaction(
                    telegram_id=chat.id,
                    chat_id=chat_id,
                    message_id=event.id,
                    direction="outgoing",
                    occurred_at=event.date,
                )
            except Exception:
                log.exception("Failed processing outgoing private Telegram event")

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
        if self.engine.privacy.is_excluded(entity.id):
            return self.engine.db.one("SELECT * FROM contacts WHERE telegram_id=?", (entity.id,))

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
        force: bool = False,
    ):
        """Seed identities from accessible dialogs/recent history.

        This is deliberately conservative to reduce Telegram API load. It can be
        run again manually from the admin bot with /rescan.
        """
        if not force:
            last = self.engine.db.one(
                "SELECT created_at FROM bot_health WHERE component='contact_bootstrap' AND status='ok' ORDER BY id DESC LIMIT 1"
            )
            if last:
                try:
                    age = datetime.now(timezone.utc) - datetime.fromisoformat(last["created_at"])
                    if age.total_seconds() < 21600:
                        log.info("Relationship bootstrap skipped: successful refresh was less than 6 hours ago")
                        return {"dialogs": 0, "contacts": 0, "status": "recent"}
                except Exception:
                    pass

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
                    if (isinstance(entity, User) and not entity.bot
                            and entity.id != self.self_user_id
                            and not self.engine.privacy.is_excluded(entity.id)):
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
                            if self.self_user_id is not None and sender.id == self.self_user_id:
                                continue
                            if self.engine.privacy.is_excluded(sender.id):
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
                self.engine.db.execute(
                    "INSERT INTO bot_health(component,status,details,created_at) VALUES ('contact_bootstrap','ok',?,?)",
                    (f"dialogs={dialogs_scanned} contacts={len(seeded_ids)}", datetime.now(timezone.utc).isoformat()),
                )

        return {"dialogs": dialogs_scanned, "contacts": len(seeded_ids)}

    async def stop(self):
        if self._bootstrap_task and not self._bootstrap_task.done():
            self._bootstrap_task.cancel()
            await asyncio.gather(self._bootstrap_task, return_exceptions=True)
        await self.client.disconnect()
