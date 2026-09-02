from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable

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

    async def connect(self):
        self.media_cache_dir.mkdir(parents=True, exist_ok=True)
        for key, session in self.sessions.items():
            c = TelegramClient(session, self.api_id, self.api_hash, flood_sleep_threshold=0)
            await c.connect()
            self.clients[key] = c
            self.media_caches[key] = MediaCache(key, c, self.staging_chats.get(key), self.media_cache_dir)

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
            try: out[key] = bool(c.is_connected())
            except Exception: out[key] = False
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

    async def send(
        self,
        account_key: str,
        group_id: int,
        caption: str,
        media: Iterable[str],
        mode: str,
        topic_id: int | None = None,
        progress_callback: Callable[[float, float], None] | None = None,
    ):
        """Send one post and optionally report real Telegram transfer progress."""
        c = self.clients[account_key]
        entity = await c.get_entity(group_id)
        kwargs = {}
        if topic_id:
            # Telethon accepts reply_to for the message/topic root when posting in forums.
            kwargs["reply_to"] = int(topic_id)
        if mode == "text":
            msg = await c.send_message(entity, caption, **kwargs)
            if progress_callback is not None:
                progress_callback(1.0, 1.0)
            return [msg.id]
        files = [str(Path(x)) for x in media]
        if not files:
            raise RuntimeError("Photo-mode destination has no media files")
        cached = await self.media_caches[account_key].get(files, progress_callback=progress_callback)
        send_files = cached if cached else files
        # Cached media has already been uploaded (or restored from Telegram), so a
        # second callback can restart from zero and make a visual bar move backward.
        # Only track destination send progress when raw files are being uploaded here.
        send_callback = None if cached else progress_callback
        messages = await c.send_file(
            entity,
            send_files,
            caption=caption or None,
            progress_callback=send_callback,
            **kwargs,
        )
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
