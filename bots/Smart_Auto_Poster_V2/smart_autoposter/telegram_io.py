from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from telethon import TelegramClient, errors

from .media_cache import MediaCache

FloodWaitError = errors.FloodWaitError
SlowModeWaitError = errors.SlowModeWaitError

# Keep the runtime tolerant of minor Telethon error-class catalogue changes.
_PERMANENT_NAMES = (
    "ChatWriteForbiddenError",
    "ChatSendMediaForbiddenError",
    "ChatSendPhotosForbiddenError",
    "ChatSendPlainForbiddenError",
    "UserBannedInChannelError",
    "ChannelPrivateError",
    "ChatAdminRequiredError",
    "PeerIdInvalidError",
    "TopicDeletedError",
    "MessageIdInvalidError",
)
PERMANENT = tuple(getattr(errors, name) for name in _PERMANENT_NAMES if hasattr(errors, name))


def album_timeout_seconds(media_count: int) -> int:
    """Bound album delivery time while giving large Telegram albums enough headroom."""
    count = max(1, int(media_count))
    return min(180, max(60, 18 * count))


def is_file_reference_expired(exc: Exception) -> bool:
    """Recognise Telethon/Telegram expired cached media-reference failures."""
    name = type(exc).__name__.lower()
    text = str(exc).lower().replace("-", "_")
    if "filereferenceexpired" in name or "file_reference_expired" in name:
        return True
    if "file_reference" in text and "expired" in text:
        return True
    return "file reference" in text and "expired" in text


class TelegramPool:
    def __init__(self, api_id: int, api_hash: str, sessions: dict[str, str], staging_chats: dict[str, int | None] | None = None,
                 media_cache_dir: Path = Path("data/cache")):
        self.api_id = api_id
        self.api_hash = api_hash
        self.sessions = sessions
        self.clients: dict[str, TelegramClient] = {}
        self.staging_chats = staging_chats or {}
        self.media_caches: dict[str, MediaCache] = {}
        self.media_cache_dir = Path(media_cache_dir)
        self._send_locks: dict[str, asyncio.Lock] = {}

    def _send_lock(self, account_key: str) -> asyncio.Lock:
        lock = self._send_locks.get(account_key)
        if lock is None:
            lock = asyncio.Lock()
            self._send_locks[account_key] = lock
        return lock

    def account_busy(self, account_key: str) -> bool:
        lock = self._send_locks.get(account_key)
        return bool(lock and lock.locked())

    async def connect(self):
        self.media_cache_dir.mkdir(parents=True, exist_ok=True)
        for key, session in self.sessions.items():
            c = TelegramClient(session, self.api_id, self.api_hash, flood_sleep_threshold=0)
            await c.connect()
            self.clients[key] = c
            self.media_caches[key] = MediaCache(key, c, self.staging_chats.get(key), self.media_cache_dir)
            self._send_lock(key)

    async def disconnect(self):
        if self.clients:
            await asyncio.gather(*(c.disconnect() for c in self.clients.values()), return_exceptions=True)

    async def reconnect(self):
        """Best-effort reconnect of both user clients without touching session files."""
        for key, c in list(self.clients.items()):
            try:
                if c.is_connected():
                    await c.disconnect()
            except Exception:
                pass
            try:
                await c.connect()
            except Exception:
                # Leave the client in the pool; authorization refresh will surface the fault.
                pass

    def connection_state(self) -> dict[str, bool]:
        out = {}
        for key, c in self.clients.items():
            try:
                out[key] = bool(c.is_connected())
            except Exception:
                out[key] = False
        return out

    async def authorization(self) -> dict[str, dict]:
        out = {}
        for key, c in self.clients.items():
            auth = await c.is_user_authorized()
            identity = None
            user_id = None
            if auth:
                me = await c.get_me()
                user_id = int(getattr(me, "id")) if getattr(me, "id", None) is not None else None
                identity = getattr(me, "username", None) or getattr(me, "first_name", None) or str(user_id or "")
            out[key] = {"authorized": auth, "identity": identity, "user_id": user_id}
        return out

    async def dialogs(self, account_key: str):
        c = self.clients[account_key]
        rows = []
        for d in await c.get_dialogs():
            if not (d.is_group or d.is_channel):
                continue
            e = d.entity
            rows.append({
                "group_id": int(d.id),
                "group_name": getattr(e, "title", None) or d.name or str(d.id),
                "chat_type": "channel" if getattr(e, "broadcast", False) else ("supergroup" if getattr(e, "megagroup", False) else "group"),
                "username": getattr(e, "username", None),
                "forum": bool(getattr(e, "forum", False)),
            })
        return rows

    async def forum_topics(self, account_key: str, group_id: int) -> list[dict]:
        """Discover visible forum topics without performing a Telegram mutation."""
        from telethon.tl.functions.messages import GetForumTopicsRequest
        from telethon.tl.types import ForumTopic

        client = self.clients[account_key]
        entity = await client.get_entity(group_id)
        peer = await client.get_input_entity(entity)
        rows: list[dict] = []
        seen: set[int] = set()
        offset_date = None
        offset_id = 0
        offset_topic = 0
        for _page in range(50):
            response = await client(
                GetForumTopicsRequest(
                    peer=peer,
                    offset_date=offset_date,
                    offset_id=offset_id,
                    offset_topic=offset_topic,
                    limit=100,
                    q=None,
                )
            )
            topics = list(getattr(response, "topics", None) or [])
            usable = [topic for topic in topics if isinstance(topic, ForumTopic)]
            added = 0
            for topic in usable:
                topic_id = int(topic.id)
                if topic_id in seen:
                    continue
                seen.add(topic_id)
                added += 1
                rows.append(
                    {
                        "topic_id": topic_id,
                        "title": str(getattr(topic, "title", "") or ""),
                        "closed": bool(getattr(topic, "closed", False)),
                        "hidden": bool(getattr(topic, "hidden", False)),
                        "pinned": bool(getattr(topic, "pinned", False)),
                    }
                )
            if len(topics) < 100 or not usable or added == 0:
                break
            last = usable[-1]
            offset_topic = int(last.id)
            offset_id = int(getattr(last, "top_message", 0) or last.id)
            offset_date = getattr(last, "date", None)
        return rows

    @staticmethod
    def _history_message_row(account_key: str, msg) -> dict:
        date = getattr(msg, "date", None)
        if date is not None and getattr(date, "tzinfo", None) is None:
            date = date.replace(tzinfo=timezone.utc)
        reply = getattr(msg, "reply_to", None)
        return {
            "account_key": account_key,
            "id": int(getattr(msg, "id")),
            "date": date.isoformat() if date is not None else None,
            "text": getattr(msg, "message", None) or "",
            "out": bool(getattr(msg, "out", False)),
            "grouped_id": getattr(msg, "grouped_id", None),
            "has_media": getattr(msg, "media", None) is not None,
            "reply_to_msg_id": getattr(reply, "reply_to_msg_id", None) if reply is not None else None,
            "reply_to_top_id": getattr(reply, "reply_to_top_id", None) if reply is not None else None,
        }

    async def message_evidence_by_ids(self, account_key: str, group_id: int, message_ids: Iterable[int]):
        """Read specific message IDs from one destination without sending anything."""
        c = self.clients[account_key]
        entity = await c.get_entity(group_id)
        ids = [int(x) for x in message_ids]
        if not ids:
            return []
        messages = await c.get_messages(entity, ids=ids)
        if messages is None:
            return []
        if not isinstance(messages, (list, tuple)):
            messages = [messages]
        return [
            self._history_message_row(account_key, msg)
            for msg in messages
            if msg is not None and getattr(msg, "id", None) is not None
        ]

    async def history_window(self, account_key: str, group_id: int, start: datetime, end: datetime, *, limit: int = 300):
        """Return outbound message metadata in a bounded UTC time window.

        Message bodies are read only for exact payload comparison. Media bytes are
        never downloaded and this method performs no Telegram mutation.
        """
        c = self.clients[account_key]
        entity = await c.get_entity(group_id)
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        rows = []
        async for msg in c.iter_messages(entity, limit=max(1, int(limit)), offset_date=end):
            date = getattr(msg, "date", None)
            if date is None:
                continue
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
            if date < start:
                break
            if date > end:
                continue
            if not bool(getattr(msg, "out", False)):
                continue
            rows.append(self._history_message_row(account_key, msg))
        return rows

    async def _send_photo_album(self, account_key: str, entity, files: list[str], caption: str, kwargs: dict):
        cache = self.media_caches.get(account_key)
        timeout = album_timeout_seconds(len(files))
        cached = await asyncio.wait_for(cache.get(files), timeout=timeout) if cache else None
        send_files = cached if cached else files
        try:
            return await asyncio.wait_for(
                self.clients[account_key].send_file(entity, send_files, caption=caption or None, **kwargs),
                timeout=timeout,
            )
        except Exception as exc:
            # Telegram's persisted media references eventually expire. Invalidate only
            # this album, restage the original local files once, then make one retry.
            if not cached or not cache or not is_file_reference_expired(exc):
                raise
            await cache.invalidate(files)
            refreshed = await asyncio.wait_for(cache.get(files), timeout=timeout)
            retry_files = refreshed if refreshed else files
            return await asyncio.wait_for(
                self.clients[account_key].send_file(entity, retry_files, caption=caption or None, **kwargs),
                timeout=timeout,
            )

    async def send(self, account_key: str, group_id: int, caption: str, media: Iterable[str], mode: str, topic_id: int | None = None):
        """Send with at most one in-flight Telegram delivery per account."""
        async with self._send_lock(account_key):
            c = self.clients[account_key]
            entity = await c.get_entity(group_id)
            kwargs = {}
            if topic_id:
                # Telethon accepts reply_to for the message/topic root when posting in forums.
                kwargs["reply_to"] = int(topic_id)
            if mode == "text":
                msg = await c.send_message(entity, caption, **kwargs)
                return [msg.id]
            files = [str(Path(x)) for x in media]
            if not files:
                raise RuntimeError("Photo-mode destination has no media files")
            messages = await self._send_photo_album(account_key, entity, files, caption, kwargs)
            if not isinstance(messages, list):
                messages = [messages]
            return [m.id for m in messages]


def retry_time(seconds: int, buffer: int = 5) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=max(1, int(seconds)) + buffer)).isoformat(timespec="seconds")


def classify_exception(exc: Exception) -> tuple[str, str | None, bool]:
    if isinstance(exc, FloodWaitError):
        return "flood_wait", retry_time(exc.seconds), False
    if isinstance(exc, SlowModeWaitError):
        return "slow_mode", retry_time(exc.seconds), False
    if isinstance(exc, PERMANENT):
        return type(exc).__name__, None, True
    if is_file_reference_expired(exc):
        # TelegramPool already performs one targeted cache refresh. If that retry also
        # fails, keep the queue retryable rather than misclassifying the media as bad.
        return "file_reference_expired", retry_time(30), False
    name = type(exc).__name__
    text = str(exc).lower()
    lname = name.lower()
    if "workerbusy" in lname or "worker busy" in text:
        return "worker_busy", retry_time(60), False
    if any(x in lname for x in ("authkey", "sessionrevoked", "sessionpasswordneeded")) or "unauthorized" in text:
        return "auth_session", retry_time(300), False
    if any(x in lname for x in ("topicdeleted", "messageidinvalid")) or "topic" in text and "invalid" in text:
        return "invalid_topic", None, True
    if any(x in lname for x in ("file", "media")) and any(x in text for x in ("invalid", "empty", "too large", "unsupported")):
        return "invalid_media", None, True
    if isinstance(exc, (ConnectionError, TimeoutError, OSError)) or any(x in text for x in ("connection reset", "server closed the connection", "timed out")):
        return "network", retry_time(60), False
    return name, retry_time(120), False
