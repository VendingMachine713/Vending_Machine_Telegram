
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
    admins_raw = os.getenv("ADMIN_IDS", "").strip()

    print("============================================================")
    print(" VM RELATIONSHIP MANAGER - BOT DIAGNOSTIC")
    print("============================================================")

    if not token:
        print("[X] BOT_TOKEN is missing from .env")
        return

    admin_ids = []
    for part in admins_raw.split(","):
        part = part.strip()
        if part:
            try:
                admin_ids.append(int(part))
            except ValueError:
                print(f"[X] Invalid ADMIN_IDS entry: {part!r}")
                return

    print(f"[+] Configured admin IDs: {admin_ids if admin_ids else 'NONE'}")

    bot = Bot(token=token)

    try:
        me = await bot.get_me()
    except Exception as exc:
        print(f"[X] Telegram rejected BOT_TOKEN or network request failed: {exc}")
        return

    print("[+] BOT_TOKEN is valid")
    print(f"[+] Token belongs to bot: @{me.username}")
    print(f"[+] Bot display name: {me.first_name}")
    print(f"[+] Bot numeric ID: {me.id}")

    try:
        webhook = await bot.get_webhook_info()
        print(f"[+] Webhook URL: {webhook.url or 'NONE'}")
        if webhook.url:
            print("[!] A webhook is configured. Polling may not receive updates until the webhook is removed.")
    except Exception as exc:
        print(f"[!] Could not read webhook info: {exc}")

    print("")
    print("NEXT:")
    print(f"1. In Telegram, open exactly @{me.username}")
    print("2. Press Start if shown.")
    print("3. Send: /rm")
    print("4. If still no reply, leave the main bot running and run diagnose_updates.py in another PowerShell window.")


if __name__ == "__main__":
    asyncio.run(main())
