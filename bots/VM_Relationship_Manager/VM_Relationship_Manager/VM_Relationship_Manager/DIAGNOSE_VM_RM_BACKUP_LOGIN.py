from __future__ import annotations

import asyncio
import getpass
import sys

from config import load_settings

try:
    from telethon import TelegramClient
    from telethon.errors import (
        ApiIdInvalidError,
        FloodWaitError,
        PhoneCodeExpiredError,
        PhoneCodeInvalidError,
        PhoneNumberFloodError,
        PhoneNumberInvalidError,
        SessionPasswordNeededError,
    )
except ImportError as exc:
    print(f"[X] Telethon import failed: {exc}")
    print("Run the normal VM Relationship Manager launcher once so requirements are installed.")
    raise SystemExit(1)


def friendly_delivery(name: str | None) -> str:
    if not name:
        return "Unknown"
    n = name.lower()
    if "app" in n:
        return "Telegram app/service chat on an already logged-in device"
    if "firebase" in n and "sms" in n:
        return "SMS (Firebase delivery)"
    if "sms" in n:
        return "SMS"
    if "email" in n:
        return "Email"
    if "call" in n:
        return "Phone call"
    if "fragment" in n:
        return "Fragment/alternative SMS delivery"
    return name


async def main() -> int:
    settings = load_settings()

    print("=" * 64)
    print(" VM RELATIONSHIP MANAGER - BACKUP LOGIN DELIVERY DIAGNOSTIC")
    print("=" * 64)
    print(f"[+] Configured phone ending: {settings.phone[-4:]}")
    print(f"[+] Session: {settings.session_name}")
    print("[!] This tool will request ONE fresh Telegram login code.")
    print("[!] It will NOT print your phone number, API hash, code hash, or password.")
    print()

    client = TelegramClient(
        settings.session_name,
        settings.api_id,
        settings.api_hash,
        auto_reconnect=True,
    )

    try:
        await client.connect()

        if await client.is_user_authorized():
            me = await client.get_me()
            print("[+] Backup session is ALREADY authorised.")
            print(f"[+] Signed in as: {getattr(me, 'first_name', '')} (@{getattr(me, 'username', None) or '-'})")
            print("[+] No login code is required. Start the normal Relationship Manager.")
            return 0

        try:
            sent = await client.send_code_request(settings.phone)
        except FloodWaitError as exc:
            seconds = int(getattr(exc, "seconds", 0) or 0)
            print("[X] Telegram is rate-limiting login-code requests.")
            if seconds:
                print(f"[!] Telegram says to wait about {seconds} seconds before requesting another code.")
            print("[!] Do not repeatedly restart the launcher while this limit is active.")
            return 2
        except PhoneNumberFloodError:
            print("[X] Telegram reports too many login attempts for this phone number.")
            print("[!] Stop requesting codes for now and retry later.")
            return 2
        except PhoneNumberInvalidError:
            print("[X] Telegram says the configured backup phone number is invalid.")
            return 3
        except ApiIdInvalidError:
            print("[X] Telegram rejected the configured API ID/API hash pair.")
            return 4
        except Exception as exc:
            print(f"[X] Telegram code request failed: {type(exc).__name__}: {exc}")
            return 5

        sent_name = type(sent).__name__
        delivery_obj = getattr(sent, "type", None)
        delivery_name = type(delivery_obj).__name__ if delivery_obj is not None else None
        next_obj = getattr(sent, "next_type", None)
        next_name = type(next_obj).__name__ if next_obj is not None else None
        timeout = getattr(sent, "timeout", None)

        print("[+] Telegram accepted the code request.")
        print(f"[+] Response type: {sent_name}")
        print(f"[+] DELIVERY TYPE: {friendly_delivery(delivery_name)}")
        print(f"[+] Telegram internal delivery class: {delivery_name or 'Unknown'}")

        if next_name:
            print(f"[+] Possible fallback after timeout: {friendly_delivery(next_name)}")
            print(f"[+] Fallback class: {next_name}")
        else:
            print("[+] Telegram did not advertise another fallback delivery type.")

        if timeout is not None:
            print(f"[+] Delivery/fallback timeout reported by Telegram: {timeout} seconds")

        print()
        print("Check the delivery location shown above.")
        print("If the code arrives, enter it below.")
        print("If it does NOT arrive, just press Enter. Do not guess codes.")
        code = input("Telegram login code (or Enter to exit): ").strip()

        if not code:
            print()
            print("[!] No code entered. Session remains unauthorised.")
            print("[!] Copy only the DELIVERY TYPE / fallback / timeout lines back to ChatGPT.")
            return 10

        try:
            await client.sign_in(
                phone=settings.phone,
                code=code,
                phone_code_hash=getattr(sent, "phone_code_hash", None),
            )
        except SessionPasswordNeededError:
            password = getpass.getpass("Telegram 2FA password (input hidden): ")
            await client.sign_in(password=password)
        except PhoneCodeInvalidError:
            print("[X] Telegram says that code was invalid.")
            return 11
        except PhoneCodeExpiredError:
            print("[X] Telegram says that code has expired.")
            return 12
        except FloodWaitError as exc:
            seconds = int(getattr(exc, "seconds", 0) or 0)
            print(f"[X] Telegram rate-limited the sign-in attempt. Wait {seconds} seconds." if seconds else "[X] Telegram rate-limited the sign-in attempt.")
            return 13
        except Exception as exc:
            print(f"[X] Sign-in failed: {type(exc).__name__}: {exc}")
            return 14

        me = await client.get_me()
        print()
        print("[+] SUCCESS — backup monitoring session is authorised.")
        print(f"[+] Signed in as: {getattr(me, 'first_name', '')} (@{getattr(me, 'username', None) or '-'})")
        print("[+] The session has been saved to the configured backup session file.")
        print("[+] You can now run .\\START_VM_RELATIONSHIPS.bat")
        return 0

    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        print("\n[!] Cancelled cleanly.")
        raise SystemExit(130)
