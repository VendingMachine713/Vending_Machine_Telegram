# VM Universal Search

Universal Search indexes Telegram messages into a local SQLite database and provides searchable access and passive match alerts through Telegram.

## Current version

**v1.4.0**

v1.4 adds passive, read-only marketplace intelligence. Indexed messages are
conservatively classified as sale, wanted, trade, or service listings. Status,
AUD price, condition, location, confidence, repost grouping, and append-only
price history are stored locally. No marketplace command sends or edits a
Telegram message.

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

Historical backfill does **not** generate passive watch alerts. Alerts are generated from new live messages only, preventing a newly configured bot from flooding the admin with old historical matches.

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
- links back to the original Telegram message when a link can be constructed.

### Passive saved-search alerts

v1.3 adds durable saved watches. A watch reuses the same query syntax as `/search` and evaluates each newly indexed live message.

Matching messages are placed into a durable SQLite alert queue and delivered privately through the bot.

The alert pipeline includes:

- configure-once saved searches;
- local-chat or global scope;
- duplicate suppression per watch/message pair;
- persistent pending/retry/sent/failed delivery state;
- exponential retry backoff;
- five delivery attempts per alert before terminal failure;
- watch-level consecutive failure tracking;
- automatic watch pause after repeated terminal delivery failures;
- pause/resume/delete controls;
- queue status reporting;
- original-message links in alerts when available;
- automatic retention cleanup for old sent/failed delivery records.

A successful alert resets the watch failure counter.

**v1.3 keeps saved watches admin-only.** Per-user group subscriptions are intentionally deferred until membership-safe delivery checks are implemented, so a former group member cannot continue receiving private alerts from a group after losing access.

## Bot commands

```text
/search <query>
/crosssearch <query>     admin only
/findads <query>         admin only
/recentsearches

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
/market [kind] [--status active|available|pending|sold] [--min 100] [--max 5000]
/listing CHAT_ID MESSAGE_ID
/pricehistory GROUP_KEY
/marketstats
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

## Saved-watch examples

Create an admin watch scoped to the group where the command is sent:

```text
/watch iphone-deals :: "iphone 15" --ads
```

Create a global admin watch across all indexed chats:

```text
/watch hilux-global :: hilux -wanted --global
```

When the claimed admin creates a watch from the bot's private chat, the scope defaults to global.

List watches:

```text
/watches
```

Pause and resume without deleting the configuration:

```text
/pausewatch 3
/resumewatch 3
```

Delete permanently:

```text
/deletewatch 3
```

View delivery queue counts:

```text
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

The passive alert worker starts and stops with the normal polling application. It does not require APScheduler or the optional `python-telegram-bot[job-queue]` dependency.

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

Database upgrades are automatic and idempotent when the stores open the existing database.

They preserve existing data and add, as required:

- live/backfill source metadata;
- FTS5 index and synchronisation triggers;
- search sessions and recent-search history;
- saved-search definitions;
- durable alert queue and retry metadata.

If the local SQLite build does not provide FTS5, search remains available through the slower LIKE fallback and `/health` reports the fallback mode.

## Safety and privacy

- Historical backfill is isolated from Bot API polling.
- Telegram history access is read-only.
- Media files are not downloaded by the backfill worker.
- Historical backfill does not create old-message alerts.
- Cross-chat searches require the claimed admin.
- Saved watches are admin-only in v1.3.
- Pagination sessions are bound to the user who initiated the search and expire after 24 hours.
- Saved-watch delivery records prevent duplicate alerts for the same watch/message pair.
- Delivery failures back off exponentially instead of busy-looping Telegram.
- Old sent delivery records are pruned after 30 days and old failed records after 90 days on startup.
- Bot tokens, API hashes and Telegram sessions remain local-only.

## Testing

```powershell
py -m unittest discover -s tests -q
py -m compileall -q .
```

The repository GitHub Actions workflow also compiles Universal Search and runs its unit tests on Windows with Python 3.12 before merge.
