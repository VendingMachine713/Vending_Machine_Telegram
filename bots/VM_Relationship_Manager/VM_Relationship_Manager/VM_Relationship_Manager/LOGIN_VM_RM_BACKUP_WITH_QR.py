from __future__ import annotations

import asyncio
import getpass
import os
from pathlib import Path
import subprocess
import sys
import time

from config import load_settings
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError


BOT_DIR = Path(__file__).resolve().parent
RUNTIME_DIR = BOT_DIR / "runtime"
RUNTIME_DIR.mkdir(parents=True, exist_ok=True)


def ensure_qrcode():
    try:
        import qrcode  # type: ignore
        return qrcode
    except ImportError:
        print("[!] QR renderer is not installed. Installing qrcode + Pillow...")
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "install", "qrcode[pil]>=7.4,<9"],
            check=False,
        )
        if proc.returncode != 0:
            print("[X] Could not install the QR renderer automatically.")
            print('Run: py -m pip install "qrcode[pil]>=7.4,<9"')
            raise SystemExit(proc.returncode)
        import qrcode  # type: ignore
        return qrcode


def cleanup_qr_files():
    for p in RUNTIME_DIR.glob("vm_rm_backup_login_qr_*.png"):
        try:
            p.unlink()
        except OSError:
            pass


def render_qr(qrcode_module, url: str, sequence: int) -> Path:
    cleanup_qr_files()
    path = RUNTIME_DIR / f"vm_rm_backup_login_qr_{sequence}.png"
    img = qrcode_module.make(url)
    img.save(path)
    return path


def open_image(path: Path):
    try:
        os.startfile(str(path))  # Windows
    except AttributeError:
        print(f"[!] Open this image manually: {path}")
    except OSError as exc:
        print(f"[!] Could not open QR image automatically: {exc}")
        print(f"[!] Open manually: {path}")


async def main() -> int:
    settings = load_settings()
    qrcode_module = ensure_qrcode()

    print("=" * 66)
    print(" VM RELATIONSHIP MANAGER - BACKUP ACCOUNT QR LOGIN")
    print("=" * 66)
    print(f"[+] Configured phone ending: {settings.phone[-4:]}")
    print(f"[+] Session: {settings.session_name}")
    print("[+] Existing main-account session will not be touched.")
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
            print("[+] Backup monitoring session is already authorised.")
            print(
                f"[+] Signed in as: {getattr(me, 'first_name', '')} "
                f"(@{getattr(me, 'username', None) or '-'})"
            )
            print("[+] Start the normal Relationship Manager.")
            return 0

        print("On the BACKUP Telegram account:")
        print("  1. Open Telegram on your phone.")
        print("  2. Go to Settings > Devices.")
        print("  3. Choose Link Desktop Device / Scan QR Code.")
        print("  4. Scan the QR image that opens on this computer.")
        print()
        print("[!] Keep this PowerShell window running while scanning.")
        print("[!] QR tokens expire quickly; this helper will refresh them automatically.")
        print()

        sequence = 0
        while not await client.is_user_authorized():
            sequence += 1
            qr = await client.qr_login()

            qr_path = render_qr(qrcode_module, qr.url, sequence)
            print(f"[+] QR #{sequence} generated: {qr_path}")
            open_image(qr_path)

            try:
                # Telegram login QR tokens are short-lived. Wait slightly below
                # the typical expiry so we can regenerate cleanly.
                await qr.wait(timeout=25)
            except SessionPasswordNeededError:
                password = getpass.getpass(
                    "Telegram 2FA password for the BACKUP account (input hidden): "
                )
                await client.sign_in(password=password)
                break
            except asyncio.TimeoutError:
                print("[!] QR expired before approval. Generating a fresh QR...")
                continue

        me = await client.get_me()
        print()
        print("[+] SUCCESS — backup monitoring session is authorised.")
        print(
            f"[+] Signed in as: {getattr(me, 'first_name', '')} "
            f"(@{getattr(me, 'username', None) or '-'})"
        )
        print(f"[+] Saved session: {settings.session_name}")
        print("[+] You can now run .\\START_VM_RELATIONSHIPS.bat")
        return 0

    except KeyboardInterrupt:
        print("\n[!] Cancelled cleanly.")
        return 130
    finally:
        cleanup_qr_files()
        try:
            await client.disconnect()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
