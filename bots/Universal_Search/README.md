# VM Universal Search

Universal Search indexes Telegram messages into a local SQLite database and provides ranked search, passive saved-search alerts, historical backfill, structured marketplace intelligence, and passive demand/supply matching.

## Current version

**v1.5.0**

## Architecture

Universal Search deliberately keeps proven capabilities separated:

- `main.py` — Bot API live indexing, search, marketplace commands, and saved-search alert delivery;
- `backfill.py` — read-only Telethon historical indexing;
- `marketplace.py` — conservative structured listing extraction and search;
- `match_engine.py` — demand/supply scoring and durable match state;
- `match_runtime.py` — alert lifecycle hardening and recovery;
- `match_daemon.py` — outbound-only passive WTB match worker.

The match daemon does **not** call Telegram `getUpdates`, so it does not compete with the main bot polling process.

## Search engine

SQLite FTS5 provides ranked full-text search with a safe LIKE fallback.

Search supports exact phrases, OR queries, excluded terms, sender/date/media filters, relevance/newest/oldest sorting, persistent user-bound pagination, recent search history, and original-message links when constructible.

## Historical backfill

The dedicated Telethon worker progressively indexes historical groups/channels accessible to the configured Telegram user account.

It:

- uses its own ignored Telegram session file;
- never sends, edits, or deletes Telegram messages;
- does not download media files;
- checkpoints progress for resume;
- upserts by `(chat_id, message_id)`;
- enriches the structured marketplace index;
- never generates passive old-message alerts.

## Passive saved-search alerts

Saved watches reuse the raw search grammar and evaluate newly indexed live messages.

The watch pipeline includes durable pending/retry/sent/failed state, duplicate suppression, bounded exponential retry, automatic retention cleanup, pause/resume/delete controls, and queue status reporting.

Saved watches remain admin-only until membership-safe per-user delivery checks are implemented.

## Marketplace intelligence

The structured marketplace layer extracts conservative signals from live and historical messages:

- type: sale, wanted, trade, service;
- lifecycle: available, wanted, pending, sold, unavailable;
- AUD price;
- category;
- condition;
- location hint;
- confidence;
- seller identity when available;
- logical listing identity across safe reposts;
- repost count;
- price history.

Lifecycle reconciliation preserves the original structured listing when sellers replace a full post with edits such as `SOLD`, `pending pickup`, or `back available`, while genuine relists and price changes are fully re-extracted.

Structured search supports type/category/status/seller/min/max filters plus relevance/newest/oldest/price sorting. Marketplace pagination is user-bound for 24 hours. Current-chat scope is the default; global scope is admin-only.

## v1.5 Demand / WTB Match Engine

v1.5 turns structured wanted posts into demand records and available sale/trade/service listings into supply.

The match scorer combines:

- concrete category compatibility;
- product-term overlap;
- WTB budget compatibility;
- location overlap when available;
- freshness;
- listing-extraction confidence;
- a small preference for direct sale supply.

Hard safety rules reject:

- inactive demand or supply;
- the same logical listing;
- the same sender matching themselves;
- concrete category mismatches;
- supply priced above an explicit WTB budget.

Reposts collapse to logical listings so the same seller reposting the same item does not generate duplicate opportunities.

### No-alert historical baseline

On first start, existing matches are classified as `baseline`. They are searchable and inspectable but are not automatically queued as new private alerts.

Only genuinely new qualifying pairs after the baseline become `new` and alertable. This prevents installing v1.5 on an established database from flooding the admin with historical matches.

### Match lifecycle

Match states include `baseline`, `new`, `notified`, `accepted`, `dismissed`, and `inactive`.

The durable match-alert queue uses pending/retry/sent/failed/cancelled states. Pending or retrying alerts are automatically cancelled when the underlying match becomes inactive, accepted, or dismissed.

Terminal delivery failures can be requeued only while the underlying match is still active and `new`.

### Passive daemon

`match_daemon.py` is an outbound-only sidecar. It:

- refreshes demand/supply matches on a bounded interval;
- maintains a SQLite singleton lease so duplicate daemons cannot run concurrently;
- queues only new high-score matches;
- sends private alerts only to the claimed Universal Search admin;
- retries failures with bounded exponential backoff;
- cancels stale alerts;
- prunes retained queue history;
- writes `state/match_engine_status.json` for passive health inspection.

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

The v1.5 match engine currently uses its dedicated PowerShell/Python operator surface while the main bot polling path remains isolated and stable.

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

```text
/market
/market iphone --type sale --status available
/market hilux --min 500 --max 5000 --sort price-asc
/market wheels --category vehicles_parts --user @seller
/market iphone --global
/listing 12
/pricehistory 12
/marketstats
/marketstats --global
```

## Match Engine operations

Initial no-alert baseline / refresh:

```powershell
.\MATCH_ENGINE.ps1 -Mode Bootstrap
.\MATCH_ENGINE.ps1 -Mode Refresh
```

Inspect matches:

```powershell
.\MATCH_ENGINE.ps1 -Mode List -MinScore 65 -Limit 20
.\MATCH_ENGINE.ps1 -Mode Show -Id 12
.\MATCH_ENGINE.ps1 -Mode Stats
.\MATCH_ENGINE.ps1 -Mode Queue
```

Record feedback:

```powershell
.\MATCH_ENGINE.ps1 -Mode Feedback -Id 12 -Verdict accepted -UserId 123456789 -Note "good lead"
.\MATCH_ENGINE.ps1 -Mode Feedback -Id 14 -Verdict not_relevant -UserId 123456789
```

Control passive notifications:

```powershell
.\MATCH_ENGINE.ps1 -Mode Notifications -State status
.\MATCH_ENGINE.ps1 -Mode Notifications -State off
.\MATCH_ENGINE.ps1 -Mode Notifications -State on
```

Recovery / cleanup:

```powershell
.\MATCH_ENGINE.ps1 -Mode Cleanup
.\MATCH_ENGINE.ps1 -Mode RetryFailed -Limit 50
```

## Passive Match Engine operation

Foreground/manual run:

```powershell
.\RUN_MATCH_ENGINE.ps1
```

Install or refresh current-user Windows auto-start:

```powershell
.\INSTALL_MATCH_ENGINE_AUTOSTART.ps1 -StartNow
```

Inspect passive health:

```powershell
.\MATCH_ENGINE_STATUS.ps1
.\MATCH_ENGINE_STATUS.ps1 -Json
```

Remove auto-start while preserving the database, match history, feedback, and configuration:

```powershell
.\UNINSTALL_MATCH_ENGINE_AUTOSTART.ps1 -StopRunning
```

The scheduled task is battery-safe, hidden, restart-enabled, and configured to ignore duplicate task instances. The SQLite daemon lease adds a second duplicate-process guard.

## Configuration

Copy `.env.example` to `.env`.

Required for the Bot API process and passive match daemon:

```text
BOT_TOKEN=
```

Required only for historical backfill:

```text
TELEGRAM_API_ID=
TELEGRAM_API_HASH=
TELEGRAM_PHONE=
```

Never commit `.env` or Telegram `.session` files.

## Install

From `bots/Universal_Search`:

```powershell
py -m pip install -r requirements.txt
```

## Run the main bot

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

## Marketplace maintenance

```powershell
.\MARKETPLACE.ps1 -Mode Rebuild
.\MARKETPLACE.ps1 -Mode Search -Query "iphone --type sale --max 1000"
.\MARKETPLACE.ps1 -Mode Stats
```

Marketplace rebuild is idempotent by `(chat_id, message_id)` and enriches already-indexed data without repeating Telegram history downloads.

## Database migration behaviour

Database upgrades are automatic and idempotent when the relevant stores open the existing database. Existing raw messages, saved watches, marketplace listings, price history, match state, feedback, and queue state are preserved.

## Safety and privacy

- Historical Telegram access is read-only.
- Backfill never creates historical passive alerts.
- Cross-chat raw search and global marketplace access require the claimed admin.
- Search and marketplace pagination sessions are user-bound.
- Saved watches remain admin-only.
- Match alerts are private and admin-only.
- The match daemon is outbound-only and does not poll Telegram updates.
- Existing historical matches are baselined rather than alerted.
- Self-matches and explicit over-budget matches are rejected.
- Stale match alerts are cancelled before delivery.
- Delivery failures back off instead of busy-looping Telegram.
- Bot tokens, API hashes, and Telegram sessions remain local-only.

## Testing

Run the complete local no-send quality gate:

```powershell
.\VALIDATE.ps1
```

Or run the underlying Python checks directly:

```powershell
py -m unittest discover -s tests -p "test_*.py" -v
py -m compileall -q .
```

`VALIDATE.ps1` also parses all supported PowerShell launchers, validates the manifest, and performs a read-only SQLite integrity check when the local database exists. It does not start Telegram polling or send Telegram messages.
