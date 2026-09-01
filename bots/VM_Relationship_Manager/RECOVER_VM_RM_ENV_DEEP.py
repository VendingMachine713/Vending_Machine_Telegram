from __future__ import annotations

import os
import re
import shutil
import sqlite3
import sys
import urllib.request
import urllib.error
import zipfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

BOT_USERNAME = "VMRelationshipManagerBot"
REQUIRED = (
    "TELEGRAM_API_ID",
    "TELEGRAM_API_HASH",
    "TELEGRAM_PHONE",
    "BOT_TOKEN",
    "ADMIN_IDS",
)
KEYS = set(REQUIRED) | {"SESSION_NAME"}

BOT_DIR = Path(__file__).resolve().parent
ENV_PATH = BOT_DIR / ".env"
RUNTIME_DIR = BOT_DIR / "runtime"

print("=" * 68)
print(" VM RELATIONSHIP MANAGER - DEEP CREDENTIAL RECOVERY")
print("=" * 68)
print("[+] No secret values will be displayed.")
print("[+] Nothing will be written unless the recovered identity validates.")
print()

candidates: dict[str, list[tuple[str, str]]] = defaultdict(list)
source_maps: list[tuple[str, dict[str, str]]] = []


def add_candidate(key: str, value: str, source: str) -> None:
    value = value.strip().strip('"').strip("'")
    if not value or value.lower() in {"changeme", "your_value_here", "none", "null"}:
        return
    if value.startswith("<") and value.endswith(">"):
        return
    candidates[key].append((value, source))


def parse_envish(text: str, source: str) -> dict[str, str]:
    text = text.lstrip("\ufeff")
    found: dict[str, str] = {}

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        # Standard dotenv / export KEY=value / PowerShell $env:KEY=value.
        patterns = [
            r'^(?:export\s+)?([A-Z][A-Z0-9_]+)\s*=\s*(.+?)\s*$',
            r'^\$env:([A-Z][A-Z0-9_]+)\s*=\s*(.+?)\s*$',
            r'^\[Environment\]::SetEnvironmentVariable\(\s*["\']([A-Z][A-Z0-9_]+)["\']\s*,\s*["\'](.+?)["\']',
        ]
        for pattern in patterns:
            m = re.match(pattern, line, flags=re.I)
            if not m:
                continue
            key = m.group(1).upper()
            value = m.group(2).strip().rstrip(");")
            value = value.strip().strip('"').strip("'")
            if key in KEYS and value:
                found[key] = value
                add_candidate(key, value, source)
            break

    # Also recover embedded assignments from shell-history lines.
    for key in KEYS:
        regexes = [
            rf'(?i)(?:^|[\s;"\']){re.escape(key)}\s*=\s*["\']?([^"\'\s;]+)',
            rf'(?i)\$env:{re.escape(key)}\s*=\s*["\']([^"\']+)["\']',
        ]
        for rgx in regexes:
            m = re.search(rgx, text)
            if m:
                value = m.group(1).strip()
                if value:
                    found.setdefault(key, value)
                    add_candidate(key, value, source)
                break

    if found:
        source_maps.append((source, found))
    return found


def read_text(path: Path) -> str | None:
    try:
        if path.stat().st_size > 4_000_000:
            return None
        return path.read_text(encoding="utf-8-sig", errors="ignore")
    except Exception:
        return None


# 1) Current process/user environment.
for key in KEYS:
    value = os.environ.get(key)
    if value:
        add_candidate(key, value, "process environment")

# 2) Current active .env (even if partial).
if ENV_PATH.exists():
    text = read_text(ENV_PATH)
    if text is not None:
        parse_envish(text, str(ENV_PATH))

# Locate project root.
project_root = BOT_DIR
while project_root.parent != project_root and project_root.name != "Vending_Machine_Telegram":
    project_root = project_root.parent

roots: list[Path] = [BOT_DIR]
if project_root.name == "Vending_Machine_Telegram":
    roots.append(project_root)

localapp = Path(os.environ.get("LOCALAPPDATA", ""))
if localapp:
    roots.append(localapp / "Vending_Machine_Telegram" / "recovery_backups")

downloads = Path.home() / "Downloads"
desktop = Path.home() / "OneDrive" / "Desktop"

# 3) Dotenv-like files in relevant roots.
seen_files: set[Path] = set()
for root in roots:
    if not root.exists():
        continue
    try:
        iterator = root.rglob("*")
        for path in iterator:
            try:
                if not path.is_file():
                    continue
            except OSError:
                continue

            lname = path.name.lower()
            ptext = str(path).lower()
            is_envish = (
                lname.startswith(".env")
                or lname.endswith(".env")
                or lname in {"env.txt", "environment.txt"}
            )
            relationship_context = (
                "relationship" in ptext
                or "vm_rm" in ptext
                or root == BOT_DIR
            )

            if not is_envish or not relationship_context:
                continue
            if path in seen_files:
                continue
            seen_files.add(path)

            text = read_text(path)
            if text:
                parse_envish(text, str(path))
    except Exception:
        pass

# 4) PowerShell history (search assignments, never print values).
history_paths = [
    Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "PowerShell" / "PSReadLine" / "ConsoleHost_history.txt",
    Path(os.environ.get("APPDATA", "")) / "Microsoft" / "PowerShell" / "PSReadLine" / "ConsoleHost_history.txt",
]
for hp in history_paths:
    if hp.exists():
        text = read_text(hp)
        if text:
            parse_envish(text, str(hp))

# 5) Relationship Manager ZIPs â€” inspect only env-like entries.
zip_roots = [downloads]
if project_root.name == "Vending_Machine_Telegram":
    zip_roots.append(project_root)

seen_zips: set[Path] = set()
for root in zip_roots:
    if not root.exists():
        continue
    try:
        for zp in root.rglob("*.zip"):
            if zp in seen_zips:
                continue
            seen_zips.add(zp)
            if "relationship" not in zp.name.lower() and "vm_rm" not in zp.name.lower():
                continue
            try:
                with zipfile.ZipFile(zp) as zf:
                    for name in zf.namelist():
                        lname = Path(name).name.lower()
                        if not (lname.startswith(".env") or lname.endswith(".env") or lname in {"env.txt", "environment.txt"}):
                            continue
                        try:
                            data = zf.read(name)
                            text = data.decode("utf-8-sig", errors="ignore")
                            parse_envish(text, f"{zp}!{name}")
                        except Exception:
                            pass
            except Exception:
                pass
    except Exception:
        pass

# 6) Recover phone/admin identity evidence from authorised Telethon session SQLite.
session_id_candidates: list[str] = []
session_phone_candidates: list[str] = []
expected_usernames = {"phoenix_plugs_backup", "phoenix_vendingmachine", "phoenix_plugs"}

if RUNTIME_DIR.exists():
    for session_path in RUNTIME_DIR.glob("*.session"):
        try:
            con = sqlite3.connect(f"file:{session_path}?mode=ro", uri=True)
            con.row_factory = sqlite3.Row
            rows = con.execute("SELECT id, username, phone, name FROM entities").fetchall()
            con.close()
        except Exception:
            continue

        for row in rows:
            username = str(row["username"] or "").strip().lower()
            phone = str(row["phone"] or "").strip()
            rid = str(row["id"] or "").strip()

            if username in expected_usernames:
                if phone:
                    if not phone.startswith("+"):
                        phone = "+" + phone
                    session_phone_candidates.append(phone)
                    add_candidate("TELEGRAM_PHONE", phone, f"authorised session entity {session_path.name}")
                if rid.isdigit():
                    session_id_candidates.append(rid)

# Use unique known Phoenix session IDs as an ADMIN_IDS recovery candidate.
session_ids = []
for x in session_id_candidates:
    if x not in session_ids:
        session_ids.append(x)
if session_ids:
    add_candidate("ADMIN_IDS", ",".join(session_ids), "authorised Phoenix Telethon sessions")

print(f"[+] Candidate sources examined: {len(source_maps) + len(seen_zips)}")
print("[+] Local secret search complete.")

# Helpers for unique/consensus selection without displaying values.
def values_for(key: str) -> list[tuple[str, str]]:
    return candidates.get(key, [])


def unique_values(key: str) -> list[str]:
    result: list[str] = []
    for value, _source in values_for(key):
        if value not in result:
            result.append(value)
    return result


# Validate BotFather tokens against the expected bot username.
def validate_bot_token(token: str) -> bool:
    url = f"https://api.telegram.org/bot{token}/getMe"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "VM-RM-Recovery/5.0.1"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            import json
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
        username = str((data.get("result") or {}).get("username") or "")
        return bool(data.get("ok")) and username.lower() == BOT_USERNAME.lower()
    except Exception:
        return False


valid_tokens = []
for token in unique_values("BOT_TOKEN"):
    if validate_bot_token(token):
        valid_tokens.append(token)

if len(valid_tokens) == 1:
    bot_token = valid_tokens[0]
    print(f"[+] Bot token identity verified as @{BOT_USERNAME}.")
elif len(valid_tokens) > 1:
    # Multiple historical valid tokens for the same bot should be unusual;
    # prefer the one seen in the newest/highest-priority source only if identical
    # selection is unambiguous by frequency.
    counts = Counter(v for v, _s in values_for("BOT_TOKEN") if v in valid_tokens)
    top = counts.most_common()
    bot_token = top[0][0] if len(top) == 1 or top[0][1] > top[1][1] else None
    if bot_token:
        print(f"[+] Bot token identity verified as @{BOT_USERNAME}.")
    else:
        print("[X] Multiple different currently valid tokens were found; refusing to guess.")
else:
    bot_token = None
    print(f"[X] No locally recovered BOT_TOKEN validated as @{BOT_USERNAME}.")

# Build API ID/hash pairs only from the same parsed source where possible.
api_pairs: list[tuple[str, str, str]] = []
for source, mapping in source_maps:
    api_id = str(mapping.get("TELEGRAM_API_ID", "")).strip()
    api_hash = str(mapping.get("TELEGRAM_API_HASH", "")).strip()
    if api_id.isdigit() and api_hash:
        pair = (api_id, api_hash, source)
        if (api_id, api_hash) not in [(a, h) for a, h, _s in api_pairs]:
            api_pairs.append(pair)

# Fallback: if IDs/hashes independently have only one unique value, pair them.
if not api_pairs:
    ids = [x for x in unique_values("TELEGRAM_API_ID") if x.isdigit()]
    hashes = unique_values("TELEGRAM_API_HASH")
    if len(ids) == 1 and len(hashes) == 1:
        api_pairs.append((ids[0], hashes[0], "unique local consensus"))

# Validate API pair by connecting with the already-authorised backup session.
def validate_api_pair(api_id: str, api_hash: str) -> bool:
    session_base = RUNTIME_DIR / "vm_relationship_backup"
    session_file = Path(str(session_base) + ".session")
    if not session_file.exists():
        return False
    try:
        import asyncio
        from telethon import TelegramClient

        async def check():
            client = TelegramClient(str(session_base), int(api_id), api_hash)
            try:
                await asyncio.wait_for(client.connect(), timeout=10)
                if not await asyncio.wait_for(client.is_user_authorized(), timeout=10):
                    return False
                me = await asyncio.wait_for(client.get_me(), timeout=10)
                return bool(me) and str(getattr(me, "username", "") or "").lower() == "phoenix_plugs_backup"
            finally:
                try:
                    await client.disconnect()
                except Exception:
                    pass

        return bool(asyncio.run(check()))
    except Exception:
        return False


valid_pairs: list[tuple[str, str]] = []
for api_id, api_hash, _source in api_pairs:
    if validate_api_pair(api_id, api_hash):
        valid_pairs.append((api_id, api_hash))

# Remove duplicates.
valid_pairs = list(dict.fromkeys(valid_pairs))
if len(valid_pairs) == 1:
    api_id, api_hash = valid_pairs[0]
    print("[+] Telegram API ID/hash validated against the authorised backup session.")
else:
    api_id = api_hash = None
    if len(valid_pairs) > 1:
        print("[X] Multiple API credential pairs validated; refusing to choose automatically.")
    else:
        print("[X] No locally recovered API ID/hash pair validated against the backup session.")

# Phone: prefer a phone recovered from the authorised Phoenix backup session.
phones = []
for p in session_phone_candidates + unique_values("TELEGRAM_PHONE"):
    p = p.strip()
    if p and p not in phones:
        phones.append(p)
phone = phones[0] if len(phones) == 1 else None
if phone:
    print("[+] Backup-account phone recovered without displaying it.")
else:
    print("[X] Backup-account phone could not be recovered unambiguously.")

# ADMIN_IDS: prefer explicit complete candidates; otherwise session IDs.
admin_values = unique_values("ADMIN_IDS")
admin_ids = None
if admin_values:
    # Prefer the value with the greatest number of numeric IDs, then frequency.
    def admin_score(value: str):
        ids = [x.strip() for x in re.split(r"[,;\s]+", value) if x.strip().isdigit()]
        freq = sum(1 for v, _s in values_for("ADMIN_IDS") if v == value)
        return (len(set(ids)), freq)

    ordered = sorted(admin_values, key=admin_score, reverse=True)
    if ordered:
        parsed = [x.strip() for x in re.split(r"[,;\s]+", ordered[0]) if x.strip().isdigit()]
        if parsed:
            admin_ids = ",".join(dict.fromkeys(parsed))

if not admin_ids and session_ids:
    admin_ids = ",".join(session_ids)

if admin_ids:
    count = len([x for x in admin_ids.split(",") if x])
    print(f"[+] Admin identity list recovered ({count} ID(s)); values hidden.")
else:
    print("[X] ADMIN_IDS could not be recovered.")

recovered = {
    "TELEGRAM_API_ID": api_id,
    "TELEGRAM_API_HASH": api_hash,
    "TELEGRAM_PHONE": phone,
    "BOT_TOKEN": bot_token,
    "ADMIN_IDS": admin_ids,
}

missing = [k for k, v in recovered.items() if not v]
if missing:
    print()
    print("[X] Deep recovery could not safely recover:", ", ".join(missing))
    print("[X] Active .env was NOT rewritten.")
    print("[!] Next step will require recovering only those missing items from the relevant Telegram/API account.")
    raise SystemExit(20)

# Preserve non-secret/current settings from the partial active .env.
current_map: dict[str, str] = {}
if ENV_PATH.exists():
    text = read_text(ENV_PATH)
    if text:
        for line in text.lstrip("\ufeff").splitlines():
            if "=" not in line or line.lstrip().startswith("#"):
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if key:
                current_map[key] = value.strip()

# Backup even an empty/partial current env.
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup_path = BOT_DIR / f".env.before_deep_recovery_{timestamp}"
if ENV_PATH.exists():
    shutil.copy2(ENV_PATH, backup_path)
else:
    backup_path.write_text("", encoding="utf-8")

current_map.update(recovered)
current_map["SESSION_NAME"] = "runtime/vm_relationship_backup"

# Stable key order.
preferred = [
    "TELEGRAM_API_ID",
    "TELEGRAM_API_HASH",
    "TELEGRAM_PHONE",
    "BOT_TOKEN",
    "ADMIN_IDS",
    "SESSION_NAME",
]
keys = preferred + [k for k in current_map if k not in preferred]
lines = [f"{k}={current_map[k]}" for k in keys if current_map.get(k) is not None]
ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")

print()
print("[+] Active .env reconstructed successfully.")
print("[+] Safety backup created before rewrite.")
print("[+] SESSION_NAME kept on runtime/vm_relationship_backup.")
print("[+] Secret values were not displayed.")

# Final config validation.
from config import load_settings
settings = load_settings()
print("[+] CONFIG VALIDATION PASSED")
print(f"[+] Admin IDs configured: {len(settings.admin_ids)}")
print(f"[+] Session: {settings.session_name}")
print("[+] Deep recovery complete.")
