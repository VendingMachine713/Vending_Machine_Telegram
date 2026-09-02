# Smart Auto Poster V3.0.3

## Admin credential loading hotfix
- Project-local `.env` now overrides inherited Windows environment variables for Smart Auto Poster settings.
- Settings are reloaded from the project `.env` on each `Settings.load()` call.
- Invalid/revoked Telegram Admin Bot tokens now return a concise operator error instead of a full traceback.
- Admin status reports which `.env` file is authoritative without exposing the token.
- Added regression coverage for stale environment-variable override and invalid-token handling.

# Changelog

## 3.0.0 — Production Platform Release

### Platform and targeting
- Additive database schema v6 with preservation of legacy campaigns, destinations, queue history and content references.
- Added reusable dynamic destination collections with include/exclude tags, account-access filters, photo/text filters, forum-only filters and explicit protected-destination inclusion.
- Campaigns can target normal tags, reusable collections, or the union of both. Hard `NEVER_AUTO_POST` remains authoritative.
- Added campaign categories, maximum cycle limits and completed-cycle accounting. Cycle-limited campaigns stop scheduling at the limit and archive only after their active queue drains.
- Added a central destination automation-rules engine for safe operational settings such as minimum intervals, quiet hours, tags, protection and valid account affinity. Rules cannot silently auto-enable destinations still awaiting review.

### Intelligence and reporting
- Added persistent, reviewable recommendations generated from real queue/error history rather than opaque autonomous marketing decisions.
- Recommendations cover uncertain sends, destination review, recurring reliability problems, repeated slow-mode pressure, account-load imbalance and variant distribution.
- Only narrowly safe/reversible recommendation actions can be applied automatically from the UI; other recommendations remain decision support.
- Expanded analytics with queue-state totals, global/campaign/account/destination success rates, content-variant usage, error categories and UTC time-of-day distribution.
- Fixed the legacy weekly-report queue-status mismatch and added V3 daily/weekly report output.

### Account routing and autonomy
- Destinations explicitly configured for dual-account use can be balanced by authorization, cooldown/pacing, health score and least-recent account usage. Explicit Primary/Secondary affinity is still respected.
- Retained duplicate Telegram-user detection, FloodWait/SlowMode backoff, reconnect recovery, circuit breaker, watchdog, runtime lock, destination quarantine and uncertain-send duplicate protection.
- Automatic rescans can optionally evaluate user-created destination rules after synchronization; this remains off by default.

### Telegram and local control centres
- Telegram Admin Control Centre supports separate full-control and read-only allowlists. Read-only admins can inspect dashboards/reports but cannot mutate posting state.
- Added Telegram views for collections, recommendations and daily/weekly reports, plus safe recommendation apply/dismiss controls.
- Campaign wizard now includes collection targeting, category and cycle limits.
- Expanded Windows Control Panel with V3 collection management, campaign V3 configuration, rule management/preview/apply, recommendations, daily/weekly reports and a one-action release-verification suite.

### Updates, rollback and diagnostics
- Master updater manifest format v3 validates safe bot targets, exact payload membership and per-file SHA-256 hashes before modifying the installed bot.
- Same/older update packages are rejected; downgrade is handled only through rollback.
- Updater now performs a consistent SQLite online backup alongside source backups before migrations. Failed post-update verification restores both source and database automatically.
- Explicit `ROLLBACK_LAST_UPDATE.ps1` also restores the corresponding database snapshot when available.
- Safe diagnostics continue to exclude `.env`, Telegram sessions, database credentials, bot tokens and login secrets.

### Validation
- Expanded automated regression suite to **117 tests**: the original 71 V2.4 tests plus 46 V3/control-panel/release checks.
- Reconstructed V2.2.3 exactly from its historical bootstrap + delta packages, seeded a live-shaped legacy database, upgraded directly from schema v3 → v6, and preserved an active campaign and sent queue-history/message-ID record.
- Post-migration compile/tests/preflight/SQLite integrity all pass.
- Final live Telegram validation remains a controlled `LIVE_TEST` on the user's own authenticated sessions.

## 2.3.0-alpha — Production Campaign Rollout

### Campaigns and content
- Added multi-content campaigns with queue-level content selection.
- Added rotation modes: `sequential`, `random`, `least_recent`, and `weighted`.
- Added per-destination content history so successful sends influence the next variant choice.
- Added minimum content reuse windows and protection against immediate same-variant repetition.
- Added campaign include + exclude tags.
- Added campaign cloning; clones remain disabled until explicitly activated.
- Added campaign preview with destination/account/mode counts and skipped-reason totals.
- Added interactive campaign creation wizard.
- Added content inbox workflow: drop a folder containing `caption.txt` and media into `content/inbox`, then import it into the permanent content library.
- Added campaign-content management for adding/removing/listing variants and setting weight/position.

### Destination safety and smart lists
- Added hard `protected` destination state; campaigns skip protected destinations unless explicitly configured to allow them.
- Added hard `never_auto_post` destination state that cannot be bypassed by campaign tags.
- Added automatic system tags after live scans: `auto_primary_only`, `auto_secondary_only`, `auto_both_accounts`, `auto_photo`, `auto_text`, `auto_forum`, `auto_review`, `auto_protected`, and `auto_never_post`.
- Retained V2.2.3 live account-routing reconciliation.

### Scheduling and conflict management
- Added queue conflict spacing per destination. New campaign jobs can be automatically spaced behind already-pending work for the same destination.
- Existing per-destination and campaign minimum intervals remain enforced and participate in spacing calculations.
- Added non-mutating schedule simulation for future windows (default 24 hours).
- Added `Post Now` that still routes through normal campaign targeting, queue, duplicate, safety, and account rules.

### Operations and unattended running
- Added automatic Telegram destination re-scan while the long-running service is active (`AUTO_RESCAN_MINUTES`, default 360).
- Added automatic daily operational summary event/output.
- Added queue/failure dashboard and bulk failed-job retry.
- Added optional Windows logon auto-start installer/remover. Installing auto-start does not immediately start the service.
- Added hidden service runner that writes to daily log files.
- Expanded Control Panel to include campaign/content operations, simulation, summaries, Post Now, and auto-start controls.

### Database and compatibility
- Additive schema migration to version 4; existing V2 queue history, campaigns, destinations, and runtime data remain usable.
- Legacy one-content campaigns are normalized into the new campaign-content relationship automatically.
- Existing pre-V2.3 queue jobs inherit their campaign's legacy content reference during migration.
- Queue jobs now store the exact selected `content_id`, making retries deterministic.

### Validation
- Expanded automated suite to 33 tests.
- Added regression coverage for multi-content rotation, worker-selected content, usage history, protected/never-post destinations, exclude tags, conflict spacing, content inbox import, cloning, smart tags, schedule simulation, and fail-closed destination synchronization.
- Full non-Telegram CLI integration flow passed.

## 2.2.3-alpha
- Added live routing-preference reconciliation after every Telegram destination scan.
- If an old config prefers Secondary but only Primary currently has access, the destination is automatically moved to Primary; the reverse is also repaired.
- Destinations visible to both accounts keep their chosen preference.
- Validation detects stale impossible account preferences before unattended operation.

## 2.2.2-alpha
- Fixed the Secondary reset/re-login path missing `datetime`/`timezone` imports.
- Added a regression test that exercises session backup/reset without a live Telegram connection.

## 2.2.1-alpha
- Added Telegram user ID to live authorization state.
- Added duplicate-account guard so scan/worker/service refuse to run when Primary and Secondary authenticate as the same Telegram user.
- Added live account identity check and safe Secondary re-login with session backup.

## 2.2.0-alpha
- Added single-instance Telegram runtime lock.
- Added persistent manual pause/resume safety state and automatic circuit breaker.
- Added periodic Telegram account authorization refresh.
- Added WAL-safe online SQLite backups and automatic backup retention.
- Added account pacing and safety/runtime health reporting.

## 2.1.0-alpha
- Added organised bot-local runtime/config/data folders.
- Added recurring interval and daily/day-of-week schedules.
- Added combined scheduler + queue service.
- Added persistent queue idempotency, quiet hours, account cooldown/pacing, routing, backups, exports, and Windows Control Panel.

## 3.0.1 - Windows runtime-lock hotfix

- Replaced the exclusive runtime lock file with an atomic lock directory to avoid
  interrupted Windows file handles blocking temporary-directory cleanup.
- Added native Windows PID liveness probing instead of relying on `os.kill(pid, 0)`.
- Preserved compatibility with stale V3.0 lock files.
- Added fail-closed grace handling for a lock directory whose owner metadata is
  still being written.
- Added regression coverage for stale legacy lock files, fresh incomplete locks,
  old incomplete locks, duplicate runtime blocking, and deterministic cleanup.


## 3.0.2 - Master updater parser repair
- Replaced fragile parent-traversal regex checks with segment-based path validation safe on Windows PowerShell.
- Includes the 3.0.1 atomic runtime-lock hotfix.
- Adds direct repair installer path so this update does not depend on the broken V3.0 updater.

## 3.0.4
- Fixed a Windows-sensitive release-verification test for deterministic campaign spread windows.
- The test now freezes the scheduler reference clock, so it validates the deterministic spread offset itself instead of failing when two equivalent enqueue calls cross a one-second wall-clock boundary.
- Carries forward the V3.0.1 Windows runtime-lock repair, V3.0.2 master-updater repair, and V3.0.3 project-local `.env` precedence/admin-token diagnostics.
