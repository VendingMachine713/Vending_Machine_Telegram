from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Callable, Iterable


def fingerprint(paths: Iterable[str]) -> str:
    h = hashlib.sha256()
    for raw in paths:
        p = Path(raw)
        h.update(p.name.encode("utf-8", "ignore"))
        h.update(str(p.stat().st_size).encode())
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
    return h.hexdigest()

class MediaCache:
    """Per-account persistent staging-message cache.

    State contains message IDs only. Telegram sessions remain local and are never copied.
    """
    def __init__(self, account_key: str, client, staging_chat_id: int | None, state_dir: Path = Path(".")):
        self.account_key = account_key
        self.client = client
        self.staging_chat_id = staging_chat_id
        self.path = state_dir / f"telegram_media_cache_v2_{account_key}.json"
        self._memory: dict[str, list] = {}
        self._lock = asyncio.Lock()

    def _load_state(self) -> dict:
        if not self.path.exists(): return {"version": 1, "items": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) and isinstance(data.get("items"), dict) else {"version": 1, "items": {}}
        except Exception:
            return {"version": 1, "items": {}}

    def _save_state(self, data: dict):
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    async def get(self, media: list[str], progress_callback: Callable[[float, float], None] | None = None):
        if not self.staging_chat_id or not media:
            return None
        fp = fingerprint(media)
        if fp in self._memory:
            return self._memory[fp]
        async with self._lock:
            if fp in self._memory:
                return self._memory[fp]
            state = self._load_state()
            item = state["items"].get(fp)
            if item and int(item.get("staging_chat_id", 0)) == int(self.staging_chat_id):
                ids = [int(x) for x in item.get("message_ids", [])]
                if ids:
                    msgs = await self.client.get_messages(self.staging_chat_id, ids=ids)
                    if not isinstance(msgs, list): msgs = [msgs]
                    if len(msgs) == len(ids) and all(m is not None and getattr(m, "media", None) is not None for m in msgs):
                        refs = [m.media for m in msgs]
                        self._memory[fp] = refs
                        return refs
            messages = await self.client.send_file(
                self.staging_chat_id,
                media,
                progress_callback=progress_callback,
            )
            if not isinstance(messages, list): messages = [messages]
            refs = [m.media for m in messages]
            state["items"][fp] = {
                "staging_chat_id": int(self.staging_chat_id),
                "message_ids": [m.id for m in messages],
                "count": len(messages),
            }
            self._save_state(state)
            self._memory[fp] = refs
            return refs
