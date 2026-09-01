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


def infer_destination_capabilities(entity) -> dict:
    """Conservatively infer text/photo posting capability from Telegram entity rights.

    The result is advisory and never fabricates permission: None means unknown.
    Broadcast channels without creator/admin rights are treated read-only. For
    groups/supergroups, default banned rights are interpreted only when the
    current user is not creator/admin.
    """
    broadcast = bool(getattr(entity, "broadcast", False))
    megagroup = bool(getattr(entity, "megagroup", False))
    creator = bool(getattr(entity, "creator", False))
    admin = bool(getattr(entity, "admin_rights", None))
    if broadcast and not megagroup:
        if creator or admin:
            return {"text_allowed": True, "photo_allowed": True, "capability_source": "telegram_admin_rights"}
        return {"text_allowed": False, "photo_allowed": False, "capability_source": "telegram_broadcast_readonly"}
    if creator or admin:
        return {"text_allowed": True, "photo_allowed": True, "capability_source": "telegram_admin_rights"}
    rights = getattr(entity, "default_banned_rights", None)
    if rights is None:
        return {"text_allowed": None, "photo_allowed": None, "capability_source": None}
    send_messages = getattr(rights, "send_messages", None)
    send_media = getattr(rights, "send_media", None)
    send_photos = getattr(rights, "send_photos", None)
    text_allowed = None if send_messages is None else not bool(send_messages)
    if send_photos is not None:
        photo_allowed = not bool(send_photos)
    elif send_media is not None:
        photo_allowed = not bool(send_media)
    else:
        photo_allowed = None
    if text_allowed is False:
        # Telegram cannot deliver a caption-only fallback if plain messages are banned.
        pass
    return {"text_allowed": text_allowed, "photo_allowed": photo_allowed, "capability_source": "telegram_default_rights"}


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
            caps = infer_destination_capabilities(e)
            rows.append({
                "group_id": int(d.id),
                "group_name": getattr(e, "title", None) or d.name or str(d.id),
                "chat_type": "channel" if getattr(e, "broadcast", False) else ("supergroup" if getattr(e, "megagroup", False) else "group"),
                "username": getattr(e, "username", None),
                "forum": bool(getattr(e, "forum", False)),
                **caps,
            })
        return rows

    async def send(self, account_key: str, group_id: int, caption: str, media: Iterable[str], mode: str,
                   topic_id: int | None = None, *, progress_callback=None, stage_callback=None):
        c = self.clients[account_key]
        if stage_callback:
            stage_callback("resolving_destination", 58, "resolving Telegram destination")
        entity = await c.get_entity(group_id)
        kwargs = {}
        if topic_id:
            # Telethon accepts reply_to for the message/topic root when posting in forums.
            kwargs["reply_to"] = int(topic_id)
        if mode == "text":
            if stage_callback:
                stage_callback("sending_text", 72, "sending text post")
            msg = await c.send_message(entity, caption, **kwargs)
            if stage_callback:
                stage_callback("awaiting_ack", 90, "text accepted; recording acknowledgement")
            return [msg.id]
        files = [str(Path(x)) for x in media]
        if not files:
            raise RuntimeError("Photo-mode destination has no media files")
        if stage_callback:
            stage_callback("preparing_media", 62, f"preparing {len(files)} media item(s)")
        cached = await self.media_caches[account_key].get(files)
        send_files = cached if cached else files
        if stage_callback:
            stage_callback("uploading_media", 65, "uploading media group")
        messages = await c.send_file(entity, send_files, caption=caption or None,
                                     progress_callback=progress_callback, **kwargs)
        if stage_callback:
            stage_callback("awaiting_ack", 90, "media uploaded; recording Telegram acknowledgement")
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
    # Format-specific permission failures are definitive non-delivery outcomes and
    # can be retried safely with the opposite supported format by the V4 worker.
    media_forbidden = tuple(
        cls for cls in (
            getattr(errors, "ChatSendMediaForbiddenError", None),
            getattr(errors, "ChatSendPhotosForbiddenError", None),
        ) if cls is not None
    )
    plain_forbidden = getattr(errors, "ChatSendPlainForbiddenError", None)
    if media_forbidden and isinstance(exc, media_forbidden):
        return "media_forbidden", None, False
    if plain_forbidden is not None and isinstance(exc, plain_forbidden):
        return "text_forbidden", None, False
    if isinstance(exc, PERMANENT):
        return type(exc).__name__, None, True
    name = type(exc).__name__
    text = str(exc).lower()
    lname = name.lower()
    # A Telegram worker-busy response during SendMultiMediaRequest is acknowledgement-ambiguous:
    # Telegram may have accepted the album but failed to return the response. Automatic retry can
    # therefore duplicate a successfully delivered media group. Fail closed as UNCERTAIN and
    # require reconciliation instead of scheduling another send.
    if "workerbusylong" in lname:
        return "uncertain_telegram_ack", None, False
    if "workerbusytoolong" in lname or "workers are too busy" in text:
        return "uncertain_telegram_ack", None, False
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
