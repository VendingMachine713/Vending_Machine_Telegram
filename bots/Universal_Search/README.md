# VM Universal Search

Universal Search indexes Telegram messages into a local SQLite database and provides ranked search, passive saved-search alerts, historical backfill, structured marketplace intelligence, and passive demand/supply matching.

## Current version

**v1.6.0 — Match Engine v2 checkpoint**

## Architecture

Universal Search keeps proven capabilities separated so search, indexing, backfill, matching, and notifications can recover independently:

- `main.py` — Bot API live indexing, search, marketplace commands, saved-search alerts, and admin Match Engine v2 commands;
- `backfill.py` — read-only Telethon historical indexing;
- `marketplace.py` — conservative structured listing extraction and search;
- `match_engine.py` — v1.5 pair scoring, durable match state, feedback, and alert queue;
- `match_runtime.py` — v1.5 alert lifecycle hardening and recovery;
- `match_engine_v2.py` — durable marketplace-change events, incremental two-way reconciliation, WTB lifecycle state, demand analytics, and calibration;
- `match_engine_v2_runtime.py` — canonical v2 runtime hardening for budget filters, historical no-flood handling, candidate-window safety, and portable SQLite cleanup;
- `match_daemon_v2.py` — outbound-only event-driven passive worker;
- `match_commands_v2.py` — admin-only Telegram match/demand command registration;
- `match_cli_v2.py` — local v2 diagnostics and maintenance;
- `migrations/0007_match_feedback.py` — idempotent v2 event/reminder migration.

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
- never generates saved-search alerts for old messages.

When v1.6 has already established its WTB reminder baseline, a later-imported historical WTB whose original message timestamp predates that baseline is also treated as historical for expiry reminders. It remains searchable and matchable, but an overdue historical reminder is not suddenly queued.

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

## Demand / WTB Match Engine

Wanted posts become demand. Active sale/trade/service listings become supply.

The shared scorer combines:

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

### v1.6 event-driven matching

The v2 migration installs durable SQLite change events for marketplace listing insert/update/delete activity.

The passive worker consumes those events in both directions:

- new/changed supply is compared with likely active WTB demand;
- new/changed WTB demand is compared with likely active supply;
- changed/inactive logical listings revalidate their existing matches;
- the v1.5 full matcher remains a periodic reconciliation/backstop.

The default passive cadence is:

- marketplace-event consumption: every **15 seconds**;
- WTB expiry-state reconciliation: every **10 minutes**;
- full demand/supply reconciliation: every **60 minutes**.

These intervals are configurable through `RUN_MATCH_ENGINE.ps1`.

### SQL candidate pre-filtering

Before semantic scoring, v2 uses SQL to reject obvious candidate mismatches such as incompatible concrete categories, the same seller, and explicit WTB budgets that cannot afford a priced supply listing.

Candidate limits bound discovery cost only. Existing unresolved matches are directly revalidated before inactivation, so an older valid match cannot disappear merely because it fell outside a bounded newest-first candidate window.

### Match lifecycle

Match states include `baseline`, `new`, `notified`, `accepted`, `dismissed`, and `inactive`.

The durable match-alert queue uses pending/retry/sent/failed/cancelled states. Pending or retrying alerts are automatically cancelled when the underlying match becomes inactive, accepted, dismissed, or belongs to a superseded admin.

Terminal delivery failures can be requeued only while the underlying match is still active and `new`.

### WTB expiry reminders

v1.6 maintains an independent WTB expiry/reminder lifecycle with durable scheduling and delivery state.

Defaults:

- WTB lifecycle window: **30 days**;
- reminder lead: **7 days** before expiry;
- delivery retry: bounded exponential backoff;
- old historical WTBs present at baseline: no reminder flood;
- old WTBs imported after the v2 baseline: also no reminder flood;
- stale/superseded-admin reminder deliveries: cancelled before send.

The reminder system does not alter reputation or moderation state.

### Relevance feedback and threshold calibration

The admin can explicitly label matches as good/relevant, bad/not relevant, accepted, or ignored.

v2 aggregates those labels into a conservative threshold recommendation. Calibration is intentionally advisory:

- it requires a minimum evidence sample;
- it moves at most one small threshold step at a time;
- it reports precision at the current threshold;
- it **never changes the production alert threshold automatically**.

This keeps learning observable and reversible.

### Demand intelligence

`/demandstats` and the v2 CLI expose:

- active WTB count;
- matched versus unmatched WTB demand;
- average stated budget where available;
- top demand categories;
- WTBs approaching expiry;
- overdue reminder state;
- event backlog;
- reminder queue state;
- feedback/calibration status.

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

/matches [min_score] [limit]                         admin only
/match <id>                                          admin only
/matchfeedback <id> good|bad|accepted|ignore [note] admin only
/demandstats                                         admin only
/matchalerts                                         admin only

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

Match commands run inside the existing main Bot API polling process. The passive sidecar remains outbound-only.

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

Existing v1.5 full baseline/reconciliation controls remain available:

```powershell
.\MATCH_ENGINE.ps1 -Mode Bootstrap
.\MATCH_ENGINE.ps1 -Mode Refresh
```

v1.6 controls:

```powershell
.\MATCH_ENGINE.ps1 -Mode BootstrapV2
.\MATCH_ENGINE.ps1 -Mode ProcessEvents -Limit 250 -CandidateLimit 500
.\MATCH_ENGINE.ps1 -Mode EventBacklog
.\MATCH_ENGINE.ps1 -Mode ExpiryRefresh
.\MATCH_ENGINE.ps1 -Mode DemandStats
.\MATCH_ENGINE.ps1 -Mode DemandStats -Json
.\MATCH_ENGINE.ps1 -Mode Calibration -AlertScore 65 -Limit 20
```

Inspect matches and queues:

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

Optional tuning:

```powershell
.\RUN_MATCH_ENGINE.ps1 `
  -IntervalSeconds 15 `
  -EventLimit 250 `
  -CandidateLimit 500 `
  -FullRefreshMinutes 60 `
  -ExpiryRefreshMinutes 10
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

The status surface shows task/daemon state, engine mode, event backlog, demand coverage, match queue, WTB reminder queue, and advisory calibration when available.

Remove auto-start while preserving the database, match history, feedback, reminder state, and configuration:

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

Database upgrades are additive and idempotent when the relevant stores/engine open the existing database.

v1.6 preserves existing:

- raw indexed messages;
- chats and sender history;
- saved watches and alert history;
- marketplace listings and price history;
- v1.5 match state and feedback;
- match alert delivery state.

It adds durable marketplace change events, WTB expiry/reminder state, WTB reminder delivery state, and v2 runtime state. The migration does not delete or rewrite existing marketplace/search records.

## Safety and privacy

- Historical Telegram access is read-only.
- Backfill never creates historical saved-search alerts.
- Cross-chat raw search and global marketplace access require the claimed admin.
- Search and marketplace pagination sessions are user-bound.
- Saved watches remain admin-only.
- Match commands and match/demand statistics are admin-only.
- Match and WTB reminder alerts are private and admin-only.
- The match daemon is outbound-only and does not poll Telegram updates.
- Existing historical matches are baselined rather than mass-alerted at initial match-engine bootstrap.
- Historical WTB expiry reminders are baselined even when old posts are imported after the v2 baseline.
- Self-matches and explicit over-budget matches are rejected.
- Bounded candidate discovery cannot by itself inactivate an existing valid match.
- Stale and wrong-admin alerts are cancelled before delivery.
- Delivery failures back off instead of busy-looping Telegram.
- Threshold calibration is advisory only.
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

`VALIDATE.ps1`:

- compiles the bot;
- runs all `test_*.py` tests;
- verifies the v1.6 manifest/capabilities and required files;
- creates a temporary SQLite database to verify v2 tables/triggers and integrity;
- parses all supported PowerShell launchers;
- performs a read-only SQLite integrity/foreign-key check when the local production database exists;
- never starts Telegram polling and never sends Telegram messages.

GitHub-hosted CI is still subject to repository/account runner allocation. A workflow failure where the job receives no runner and executes zero steps is infrastructure failure, not a passing or failing application test result.
