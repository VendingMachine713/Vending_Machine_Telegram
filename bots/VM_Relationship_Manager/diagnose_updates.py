
from __future__ import annotations

import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from telegram import Bot


BOT_DIR = Path(__file__).resolve().parent
load_dotenv(BOT_DIR / ".env")


async def main():
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        print("[X] BOT_TOKEN missing.")
        return

    bot = Bot(token=token)
    me = await bot.get_me()
    print(f"Checking pending updates for @{me.username} ...")

    try:
        updates = await bot.get_updates(timeout=3, allowed_updates=["message", "callback_query"])
    except Exception as exc:
        print(f"[X] Could not fetch updates: {exc}")
        print("[!] If the main Relationship Manager is currently polling, stop it with Ctrl+C before running this diagnostic.")
        return

    if not updates:
        print("[!] No pending updates were returned.")
        print(f"Open @{me.username} in Telegram, press Start, send /rm, then run this diagnostic again.")
        return

    print(f"[+] Found {len(updates)} update(s):")
    for u in updates[-10:]:
        if u.message:
            user = u.message.from_user
            print(
                f" - message from user_id={user.id} username=@{user.username or '-'} "
                f"text={u.message.text!r}"
            )
        elif u.callback_query:
            user = u.callback_query.from_user
            print(f" - callback from user_id={user.id} data={u.callback_query.data!r}")


if __name__ == "__main__":
    asyncio.run(main())
