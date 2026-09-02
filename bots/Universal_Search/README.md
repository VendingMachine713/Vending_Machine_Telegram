# VM Universal Search

Universal Search indexes Telegram messages into a local SQLite database and provides searchable access through the Telegram bot.

## Current version

**v1.1.0**

### Live search

The bot indexes messages it receives through the Telegram Bot API and supports:

- `/search <words>`
- `/crosssearch <words>` — admin only
- `/findads <words>`
- `/health`
- `/backfillstatus` — admin only

### Historical backfill

v1.1 adds a separate **read-only Telethon history worker**. It can progressively index historical messages from groups and channels accessible to the configured Telegram user account.

The worker:

- uses its own Telegram session file;
- does not send, edit or delete Telegram messages;
- does not download media files;
- stores only message text/caption and media-presence metadata;
- checkpoints progress so interrupted scans can resume;
- uses the same Bot API-style marked chat IDs (`-100...`) as the live index;
- upserts by `(chat_id, message_id)` so live and historical indexing do not duplicate records.

## Configuration

Copy `.env.example` to `.env`.

Required for the bot:

```text
BOT_TOKEN=
```

Required only for historical backfill:

```text
TELEGRAM_API_ID=
TELEGRAM_API_HASH=
TELEGRAM_PHONE=
```

Never commit `.env` or Telegram `.session` files. The project `.gitignore` already excludes them.

## Install

From `bots/Universal_Search`:

```powershell
py -m pip install -r requirements.txt
```

## Run the bot

```powershell
.\START.ps1
```

## Historical backfill

Show current progress without connecting to Telegram:

```powershell
.\BACKFILL.ps1 -Mode Status
```

List accessible groups/channels:

```powershell
.\BACKFILL.ps1 -Mode ListChats
```

Backfill one chat:

```powershell
.\BACKFILL.ps1 -Mode Chat -Chat "-1001234567890" -Limit 5000
```

Backfill accessible groups/channels:

```powershell
.\BACKFILL.ps1 -Mode All -Limit 5000
```

Limit history to a date window:

```powershell
.\BACKFILL.ps1 -Mode All -Limit 10000 -Days 90
```

On the first Telethon login, Telegram may require an interactive login code. After the dedicated local session is authorised, later backfills reuse it.

## Safety

Historical backfill is deliberately isolated from the Bot API polling process. A slow scan, Telegram flood-wait, or interrupted history run does not stop live `/search` operation.

The backfill worker is read-only with respect to Telegram. It only reads accessible history and writes the bot-owned local SQLite index.

## Testing

```powershell
py -m unittest discover -s tests -q
py -m compileall -q .
```
