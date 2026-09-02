# VM Universal Search

Universal Search indexes Telegram messages into a local SQLite database and provides searchable access through the Telegram bot.

## Current version

**v1.2.0**

## Core capabilities

### Live indexing

The Bot API process indexes new messages it receives into the local SQLite database.

### Historical backfill

A separate read-only Telethon worker can progressively index historical messages from groups and channels accessible to the configured Telegram user account.

The worker:

- uses its own Telegram session file;
- does not send, edit or delete Telegram messages;
- does not download media files;
- stores message text/caption and media-presence metadata;
- checkpoints progress so interrupted scans can resume;
- uses the same Bot API-style marked chat IDs (`-100...`) as the live index;
- upserts by `(chat_id, message_id)` so live and historical indexing do not duplicate records.

### Search Engine v2

v1.2 adds SQLite FTS5 search and a safe LIKE fallback when FTS5 is unavailable.

Search now supports:

- ranked full-text results;
- exact phrases;
- OR queries;
- excluded terms;
- sender filtering;
- date windows;
- media-only filtering;
- relevance/newest/oldest sorting;
- Previous/Next pagination;
- persistent 24-hour pagination sessions;
- recent search history;
- links back to the original Telegram message when a link can be constructed.

## Bot commands

```text
/search <query>
/crosssearch <query>     admin only
/findads <query>         admin only
/recentsearches
/searchhelp
/health
/backfillstatus          admin only
```

Cross-chat search is deliberately restricted to the claimed Universal Search admin. This prevents the bot-owned index from exposing messages from one indexed group to arbitrary users in another context.

## Query examples

Basic search:

```text
/search iphone 15
```

Exact phrase:

```text
/search "iphone 15 pro"
```

OR search:

```text
/search iphone OR samsung
```

Exclude a term:

```text
/search hilux -wanted
```

Sender and date filter:

```text
/search wheels --user @seller --days 30
```

Media-only results:

```text
/search exhaust --media
```

Sorting:

```text
/search iphone --sort relevant
/search iphone --sort newest
/search iphone --sort oldest
```

Result size and explicit page:

```text
/search iphone --limit 10 --page 2
```

The Telegram result message also provides Previous/Next buttons when additional pages are available.

## Configuration

Copy `.env.example` to `.env`.

Required for the Bot API process:

```text
BOT_TOKEN=
```

Required only for historical backfill:

```text
TELEGRAM_API_ID=
TELEGRAM_API_HASH=
TELEGRAM_PHONE=
```

Never commit `.env` or Telegram `.session` files. The project `.gitignore` excludes them.

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

## Database migration behaviour

The v1.2 database upgrade is automatic when `Store` opens the existing database.

It:

- preserves existing indexed messages;
- preserves v1.1 live/backfill source metadata;
- creates the FTS5 index when supported;
- backfills the FTS index from existing messages once when required;
- installs triggers so later inserts, edits and deletes stay synchronised;
- creates search-session and search-history tables idempotently.

If the local SQLite build does not provide FTS5, search remains available through the slower LIKE fallback and `/health` reports the fallback mode.

## Safety and privacy

- Historical backfill is isolated from Bot API polling.
- Telegram history access is read-only.
- Media files are not downloaded by the backfill worker.
- Cross-chat searches require the claimed admin.
- Pagination sessions are bound to the user who initiated the search and expire after 24 hours.
- Bot tokens, API hashes and Telegram sessions remain local-only.

## Testing

```powershell
py -m unittest discover -s tests -q
py -m compileall -q .
```

The repository GitHub Actions workflow also compiles Universal Search and runs its unit tests on Windows with Python 3.12 before merge.
