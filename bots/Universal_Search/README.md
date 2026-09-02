# VM Universal Search

Universal Search indexes Telegram messages into a local SQLite database and provides searchable access, passive match alerts, historical backfill, and structured marketplace intelligence through Telegram.

## Current version

**v1.4.0**

## Core capabilities

### Live indexing

The Bot API process indexes new messages it receives into the local SQLite database. New live messages are also evaluated for passive watches and structured marketplace extraction.

### Historical backfill

A separate read-only Telethon worker can progressively index historical messages from groups and channels accessible to the configured Telegram user account.

The worker:

- uses its own Telegram session file;
- does not send, edit or delete Telegram messages;
- does not download media files;
- stores message text/caption and media-presence metadata;
- checkpoints progress so interrupted scans can resume;
- uses the same Bot API-style marked chat IDs (`-100...`) as the live index;
- upserts by `(chat_id, message_id)` so live and historical indexing do not duplicate records;
- extracts structured marketplace metadata while historical messages are indexed.

Historical backfill does **not** generate passive watch alerts, preventing old-message alert floods.

### Search Engine v2

SQLite FTS5 is used for ranked full-text search, with a safe LIKE fallback when FTS5 is unavailable.

Search supports:

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
- original-message links when constructible.

### Passive saved-search alerts

Durable saved watches reuse the search query grammar and evaluate newly indexed live messages.

The alert pipeline includes:

- admin-managed local-chat or global watches;
- duplicate suppression per watch/message pair;
- durable pending/retry/sent/failed state;
- bounded exponential retry backoff;
- five delivery attempts per alert;
- automatic watch pause after repeated terminal failures;
- pause/resume/delete controls;
- queue status reporting;
- automatic retention cleanup.

Saved watches remain admin-only until membership-safe per-user delivery checks are implemented.

### Marketplace intelligence

v1.4 adds a structured marketplace layer beside the raw message index.

It automatically extracts conservative marketplace signals from both live and historical messages, including:

- listing type: sale, wanted, trade, service;
- lifecycle state: available, wanted, pending, sold, unavailable;
- AUD prices including `$900`, `$1,250`, `AUD 850`, and `1.5k`-style values;
- category;
- condition;
- location hints;
- confidence score;
- seller identity when available;
- logical listing identity across exact/safe reposts;
- repost counts;
- price history.

Marketplace data is stored in separate SQLite tables so the proven FTS search engine remains independent.

Structured marketplace searches support:

- text terms;
- listing type;
- category;
- lifecycle status;
- seller username;
- minimum and maximum price;
- relevance/newest/oldest/price sorting;
- user-bound 24-hour Previous/Next pagination;
- local-chat scope by default;
- admin-only `--global` scope.

## Bot commands

```text
/search <query>
/crosssearch <query>     admin only
/findads <query>         admin only
/recentsearches

/market <query>
/listing <id>
/pricehistory <id>
/marketstats [--global]

/watch name :: query              admin only
/watch name :: query --global     admin only
/watches
/pausewatch <id>
/resumewatch <id>
/deletewatch <id>
/alertstatus

/searchhelp
/health
/backfillstatus          admin only
```

Cross-chat raw search and global marketplace search are restricted to the claimed Universal Search admin.

## Search examples

```text
/search iphone 15
/search "iphone 15 pro"
/search iphone OR samsung
/search hilux -wanted
/search wheels --user @seller --days 30
/search exhaust --media --sort newest
```

## Marketplace examples

Available marketplace listings in the current chat:

```text
/market
```

Search current-chat sale listings:

```text
/market iphone --type sale --status available
```

Price range and sorting:

```text
/market hilux --min 500 --max 5000 --sort price-asc
```

Filter by category or seller:

```text
/market wheels --category vehicles_parts --user @seller
```

Search all indexed chats as admin:

```text
/market iphone --global
```

Inspect one structured listing:

```text
/listing 12
```

View price history for that logical listing:

```text
/pricehistory 12
```

Marketplace statistics:

```text
/marketstats
/marketstats --global
```

## Saved-watch examples

```text
/watch iphone-deals :: "iphone 15" --ads
/watch hilux-global :: hilux -wanted --global
/watches
/pausewatch 3
/resumewatch 3
/deletewatch 3
/alertstatus
```

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

```powershell
.\BACKFILL.ps1 -Mode Status
.\BACKFILL.ps1 -Mode ListChats
.\BACKFILL.ps1 -Mode Chat -Chat "-1001234567890" -Limit 5000
.\BACKFILL.ps1 -Mode All -Limit 5000
.\BACKFILL.ps1 -Mode All -Limit 10000 -Days 90
```

On first Telethon login, Telegram may require an interactive login code. Later backfills reuse the dedicated ignored local session.

## Marketplace maintenance

Rebuild structured marketplace data from the existing raw message index:

```powershell
.\MARKETPLACE.ps1 -Mode Rebuild
```

Search from PowerShell:

```powershell
.\MARKETPLACE.ps1 -Mode Search -Query "iphone --type sale --max 1000"
```

Statistics:

```powershell
.\MARKETPLACE.ps1 -Mode Stats
```

The rebuild is idempotent by `(chat_id, message_id)` and is useful after upgrading an existing v1.3 database so already-indexed historical messages gain v1.4 marketplace metadata without repeating Telegram history downloads.

## Database migration behaviour

Database upgrades are automatic and idempotent when stores open the existing database.

They preserve existing data and add, as required:

- live/backfill source metadata;
- FTS5 index and synchronisation triggers;
- search sessions and recent-search history;
- saved-search definitions;
- durable alert queue and retry metadata;
- structured marketplace listings;
- marketplace price history;
- marketplace pagination sessions.

## Safety and privacy

- Historical Telegram access is read-only.
- Media files are not downloaded by backfill.
- Historical backfill never creates passive alerts.
- Cross-chat raw searches require the claimed admin.
- Global marketplace searches/statistics require the claimed admin.
- `/listing` and `/pricehistory` only expose another chat's record to the claimed admin.
- Search and marketplace pagination sessions are user-bound and expire after 24 hours.
- Saved watches remain admin-only.
- Alert delivery failures back off instead of busy-looping Telegram.
- Bot tokens, API hashes and Telegram sessions remain local-only.

## Testing

```powershell
py -m unittest discover -s tests -q
py -m compileall -q .
```

Repository CI compiles and tests Universal Search on Python 3.12. A dedicated Linux Universal Search workflow is also present to provide a second execution path when the repository's Windows runner pool is unavailable.
