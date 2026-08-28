# Smart Auto Poster V3.0

Smart Auto Poster V3.0 is the production-platform release for the Vending Machine Telegram ecosystem. It consolidates the live-tested V2 sender/routing core, campaign/content engine and autonomous recovery layer, then adds reusable destination collections, deterministic automation rules, cycle-limited campaigns, reviewable operational recommendations, richer analytics/reporting, dual-account health-aware balancing, read-only Telegram admins and a hardened manifest/hash/database-rollback update system.

The release is designed to upgrade directly from **V2.2.3 or newer** while preserving local sessions, secrets, database history, destination configuration and content.

## V3.0 highlights

- persistent multi-account Telegram sender with account identity guard, pacing, cooldowns and safe dual-access balancing
- multi-variant campaigns, reusable content library, rotation, schedule simulation, Post Now through the queue, start/end dates and cycle limits
- dynamic destination collections plus include/exclude tags, protected groups and hard `NEVER_AUTO_POST`
- deterministic destination rules for quiet hours, minimum intervals, safe account affinity, tags and protection
- persistent queue, duplicate protection, conflict spacing, capacity limits, retry/defer/cancel/uncertain states
- FloodWait/SlowMode-aware backoff, network reconnect, quarantine, circuit breaker, runtime lock and watchdog
- automatic destination scans, routing reconciliation, backups, maintenance and reports
- private Telegram Admin Control Centre with full-control/read-only roles
- operational recommendations derived from real queue/error history; no opaque automatic marketing decisions
- safe diagnostics and admin audit/update history
- master-folder update system with exact manifest membership, SHA-256 verification, source + SQLite backup and automatic rollback on failed verification
- schema v6 additive migration and **117-test** regression suite

## Start locally

```powershell
powershell -ExecutionPolicy Bypass -File ".\CONTROL_PANEL.ps1"
```

The V3 Control Panel exposes core status/safety/campaign/content/queue operations plus destination collections, rules, recommendations and release verification. Routine operation can move to the optional Telegram Admin Control Centre after local setup.

See:

- `docs\UPGRADE_FROM_2.2.3.md`
- `docs\V3_PLATFORM.md`
- `docs\TELEGRAM_ADMIN_SETUP.md`
- `docs\OPERATIONS.md`
- `docs\LIVE_TEST_CHECKLIST.md`
- `docs\RELEASE_3_0_CHECKLIST.md`

## Content inbox workflow

Create a folder per advertisement:

```text
content\inbox\South_Ad_01\
├── caption.txt
├── 01.jpg
└── 02.jpg
```

Then choose **23. Import content inbox**, or run:

```powershell
py .\app.py import-content
```

The item is copied into the permanent `content\library\...` folder, registered in SQLite, and removed from the inbox after a successful import. Existing library content is not silently overwritten.

Supported inbox media extensions include JPG/JPEG, PNG, WEBP, GIF, MP4, MOV, and M4V.

## Multi-ad campaigns

A campaign can now contain multiple reusable content items.

Create a campaign with its first content item:

```powershell
py .\app.py add-campaign CAMP_A "Main Rotation" ad_01 --tags main --rotation sequential --conflict-gap-minutes 60
```

Add more variants:

```powershell
py .\app.py campaign-content CAMP_A --add ad_02 --position 1
py .\app.py campaign-content CAMP_A --add ad_03 --position 2
```

List variants:

```powershell
py .\app.py campaign-content CAMP_A
```

Rotation modes:

- `sequential`
- `random`
- `least_recent`
- `weighted`

The queue stores the exact `content_id` selected for each destination. Retries therefore keep the same selected content rather than unexpectedly switching variants.

## Preview before activation/posting

```powershell
py .\app.py preview CAMP_A
```

Preview shows:

- selected destination count
- Primary-only / Secondary-only / dual-access counts
- photo/text counts
- campaign variants
- include/exclude tags
- protected/never-post exclusions

Dry-run enqueue remains available:

```powershell
py .\app.py enqueue CAMP_A --dry-run
```

## Hard destination safety

Mark a destination protected:

```powershell
py .\app.py destination -100123456789 --protect
```

Protected destinations are excluded unless a campaign was explicitly created with `--allow-protected`.

Hard-block a destination from all automatic campaigns:

```powershell
py .\app.py destination -100123456789 --never-auto-post
```

This rule is stronger than tags and cannot be bypassed by broad campaign targeting.

Undo it with:

```powershell
py .\app.py destination -100123456789 --allow-auto-post
```

## Automatic smart tags

Live destination scans rebuild these system tags automatically:

```text
auto_primary_only
auto_secondary_only
auto_both_accounts
auto_photo
auto_text
auto_forum
auto_review
auto_protected
auto_never_post
```

Your manually assigned tags are preserved.

## Conflict spacing

`--conflict-gap-minutes` prevents multiple campaigns already in the queue from stacking too closely for the same destination.

Example:

```powershell
py .\app.py add-campaign CAMP_A "Main" ad_01 --tags main --conflict-gap-minutes 60
```

If another eligible job for the same group is already queued, the new job is placed at least 60 minutes behind it. Existing destination/campaign minimum intervals are also included in the spacing calculation.

## Schedules and simulation

Interval:

```powershell
py .\app.py schedule CAMP_A --interval-minutes 360
```

Daily times:

```powershell
py .\app.py schedule CAMP_A --daily-times 09:00,19:00
```

Selected weekdays:

```powershell
py .\app.py schedule CAMP_A --daily-times 10:00,18:30 --days mon,wed,fri
```

Preview future scheduled runs without queuing anything:

```powershell
py .\app.py simulate --hours 24
```

## Post Now

Post Now is not a direct Telegram bypass. It still uses campaign targeting, protected/never-post rules, account routing, queue persistence, duplicate safeguards, pacing, and worker safety.

Preview only:

```powershell
py .\app.py post-now CAMP_A --dry-run
```

Queue now:

```powershell
py .\app.py post-now CAMP_A
```

The Control Panel requires typing `SEND` after preview before it queues the campaign.

## Queue/failure operations

```powershell
py .\app.py queue-summary
py .\app.py queue --status failed
py .\app.py retry-failed --campaign CAMP_A
py .\app.py job 123 --retry
py .\app.py job 123 --cancel
```

Interrupted in-flight sends still become `uncertain` and are never blindly retried.

## Automatic destination re-scan

The long-running service can rescan Telegram periodically while it is running:

```text
AUTO_RESCAN_MINUTES=360
```

New groups remain REVIEW + disabled. Lost access fails closed. Routing preferences are reconciled to the accounts that really have access.

## Optional Windows auto-start

Choose **32. Install Windows auto-start** from the Control Panel, or run:

```powershell
.\INSTALL_AUTOSTART.ps1
```

This installs a Windows scheduled task for the current user. It does **not** immediately start the service; the task triggers at the next Windows logon. The hidden runner writes service output to `logs\service_YYYYMMDD.log`.

Remove it with Control Panel option 33 or:

```powershell
.\REMOVE_AUTOSTART.ps1
```

Do not install auto-start until a V2.3 `LIVE_TEST` one-job send has passed and the intended production campaigns have been reviewed.

## Safe rollout sequence after applying V2.3

```text
1. Setup / upgrade environment
2. Run self-tests (expect 33/33)
3. Health check
4. Validate
5. Scan destinations
6. Preview LIVE_TEST campaign
7. Enqueue one LIVE_TEST job
8. Run one queue job
9. Confirm sent status in Telegram + queue
10. Only then configure/enable production campaigns
11. Optional: install Windows auto-start last
```

## Security / local secrets

Keep `.env`, Telegram `.session` files, login codes, 2FA passwords, API hashes, and bot tokens local. Never paste them into chat. Live sessions remain under `runtime\sessions` inside this bot's permanent folder to avoid concurrent SQLite session locking with other bots.
