# Smart Auto Poster V6.0.0 - Self-Managing Production Control Plane

- Added V6 destination intelligence with reliability, timing-risk, format-confidence and preferred-account scoring.
- Added explainable delivery-confidence materialisation; UNCERTAIN outcomes remain explicitly non-confirmed and never auto-retry.
- Added predictive destination timing holds that reuse the same queue row and avoid contacting Telegram before learned safe windows.
- Added V6 production objectives, health scoring, predictive routing plan and recovery recommendations.
- Added `v6-control`, `v6-intelligence`, `v6-confidence`, `v6-plan` and `v6-recovery` CLI surfaces.
- Added Telegram Admin Bot `/v6` / `/control` view and V6 Control button.
- Added recovery safety logic that will not recommend automatic runtime restart while a send is in flight.
- Added schema v20 tables for destination intelligence, delivery confidence, recovery incidents and production objectives.
- Fixed duplicate legacy destination migration map that could omit protection/last-seen columns on very old upgrade paths.
- Preserves V5 evidence-safe queue hygiene, per-account routing, one-post/group guards, multi-pass deferral, history scanning and fail-closed production gate.
- Main production activation is not performed by the release installer.

# Smart Auto Poster V5.0.3 - Evidence Recovery Hardening

- Infer legacy missing account keys from delivery-attempt and phase history before Telegram evidence scans.
- When no durable account is known, scan every authorised Telegram account and require a unique exact match across all candidates before automatic SENT reconciliation.
- Add a broader 120-minute diagnostic-only history window to surface nearby outgoing history without granting it automatic reconciliation authority.
- Preserve the strict bounded exact-match window as the only automated SENT authority; absence still never means NOT_SENT.
- Report account source, account candidates, broader-window candidate counts, nearest-message distance, and scan errors for evidence review.

# Smart Auto Poster V5.0.2 - Telegram Evidence Reconciliation

- Adds `uncertain-scan` using the existing authorized Telegram sessions.
- Searches a bounded history window around UNCERTAIN delivery attempts.
- Auto-reconciles SENT only for one unique exact outgoing payload match.
- Photo evidence requires the expected caption and exact media-group item count.
- Ambiguous/missing history remains UNCERTAIN; NOT_SENT is never inferred automatically.
- Designed to run while the managed runtime is stopped to avoid Telethon session contention.

# Smart Auto Poster V5.0.1 - Queue Guard Live Hotfix

- Fixes V5 launch failure when multiple historical UNCERTAIN rows exist for the same group.
- Explicitly classifies multiple UNCERTAIN rows as review-required delivery evidence.
- Adds read-only unresolved-group conflict inventory before SQLite UNIQUE guard installation.
- If historical ambiguous evidence prevents the database guard, V5 continues in degraded safe mode with application-level admission/worker guards active.
- SQLite guard installation now catches late uniqueness races and reports them safely instead of aborting the runtime launch.
- No UNCERTAIN, SENDING, Telegram message IDs, or ambiguous attempt history are mutated by this hotfix.

# Smart Auto Poster V5.0.0 - Autonomous Production Controller

## Queue integrity and anti-spam
- Adds evidence-aware queue hygiene that suppresses only provably-unsent redundant rows.
- UNCERTAIN, SENDING and ambiguous delivery-attempt evidence are never silently rewritten.
- Installs a SQLite partial UNIQUE guard after safe cleanup so concurrent paths cannot create two unresolved obligations for one Telegram group.
- Startup automatically performs the same narrow safe cleanup and reports any evidence that still needs review.

## Routing and timing intelligence
- Stores text/photo capability per Telegram account and destination.
- Account-specific format rejection fails over to another capable account before changing the destination-wide delivery mode.
- Learns SlowMode/FloodWait timing profiles and next-safe timestamps for operational visibility and pacing intelligence.

## Production control
- Adds a persistent production-run ledger and V5 production gate.
- Gate blocks production on UNCERTAIN evidence, in-flight sends, unsafe queue overlap, unresolved delivery modes, or database-integrity failure.
- Mission Control distinguishes overlap groups from safely suppressible unsent rows and evidence/review rows.
- Telegram Admin Bot adds `/gate` and `/hygiene` read-only production safety views.

## Release safety
- Existing queue IDs, SENT/UNCERTAIN evidence, schedules, sessions, credentials and campaign state are preserved.
- No generic UNCERTAIN retry. No automatic production activation during upgrade.

# Smart Auto Poster V4.0.1 - Windows Console Safety Hotfix

- Prevents Mission Control, progress and post-timeline commands from crashing on Windows PowerShell 5.1 legacy console encodings when Telegram destination names contain unsupported Unicode symbols.
- Adds one centralized console-safety boundary: UTF-8 consoles preserve Unicode; legacy consoles replace only characters they cannot encode.
- Telegram Admin Bot rendering remains Unicode-rich and unchanged.
- Adds CP1252, ASCII and UTF-8 regression coverage.
- No queue, campaign, schedule, delivery-evidence or reconciliation semantics changed.

# Smart Auto Poster V4.0.0 - Round Engine, Adaptive Routing & Mission Control

## Production model
- Enforces one unresolved post per Telegram group globally across campaigns and scheduled cycles; new runs skip an already-unresolved group instead of stacking another post.
- Reuses the same queue row for retry/defer work. SlowMode, FloodWait, quiet hours, account cooldowns and other retry-safe waits move that row into a later pass; they never create a duplicate post.
- Implements a pass barrier: all untouched Pass 1 destinations are attempted before Pass 2 retry/deferred work from the same run can be claimed.
- A definitive successful send suppresses legacy pre-send duplicate rows as `duplicate_suppressed`, protecting upgrades that already contain stacked queue entries.
- Any existing `SENDING` or `UNCERTAIN` row blocks other work for that group. Ambiguous Telegram delivery remains fail-closed and never auto-retries.

## Mixed text/photo delivery
- Campaign content is selected against each destination's delivery mode: text groups receive caption-compatible content; photo groups require valid 1..10-media content.
- Telegram scans now infer conservative text/photo permissions where Telegram exposes them, merge observations across both accounts, and automatically align a destination when only one format is supported.
- If Telegram definitively rejects the current format, the same queue row can switch to the opposite compatible format in the next pass.
- If neither format is allowed the destination is disabled for review; if the campaign lacks the required fallback format, the job becomes terminal `no_compatible_fallback` rather than looping retries.

## Live per-post pipeline
- Durable queue phase history records destination validation, timing checks, content validation, account selection, payload preparation, Telegram request boundary, upload progress, acknowledgement and final outcome.
- Photo uploads expose byte-level progress in throttled 5% buckets without changing queue semantics.
- `progress` shows overall run progress, current pass, first-pass remaining, ETA, stuck detection, outcome counts and one bar per group.
- `job-timeline <id>` shows the selected post's current bar, current-pass checklist, durable phase history and delivery attempts.
- ASCII-safe local rendering avoids Windows console mojibake; Telegram retains rich buttons/emoji.

## Mission Control & reliability
- `mission-control` combines current run, queue, accounts, schedule, destination modes, attention jobs and global anti-spam overlap detection.
- Telegram Admin Bot exposes `/mission`, `/progress` and `/post <id>` with refresh/navigation buttons.
- Control Panel adds Mission Control and per-post timeline views.
- Circuit-breaker recovery releases stale automatic holds when the rolling risky-send window has genuinely recovered; manual pauses are never auto-cleared.
- Expected timing/back-pressure continues to stay out of breaker failure counts, while uncertain acknowledgements remain breaker-relevant.
- V3.5.1 five-minute Windows self-healing and duplicate-runtime suppression are retained.

## Database
- Schema v13 adds round/pass metadata, persistent phase/transfer progress and lifecycle history using additive migrations.
- Existing queue rows are migrated conservatively without changing SENT/UNCERTAIN delivery evidence.
- No live post is created by the update itself.

# Smart Auto Poster V3.5.2 - Live Auto-Post Progress

- Added a read-only per-run progress engine with an overall processing bar and one stage line per destination.
- Per-post stages now expose QUEUED, DEFERRED, RETRY, SENDING, SENT, VERIFY/UNCERTAIN, FAILED, QUARANTINED, CANCELLED and EXPIRED states.
- Deferred/retry rows show the next due time and the relevant timing/error reason; active/sent rows show the selected Telegram account when known.
- Added `py .\app.py progress` plus `--campaign`, `--run-key`, `--json-only`, and live `--watch --interval` modes.
- Telegram Admin Bot adds `/progress`, a Progress home button, a refresh button, and latest-run progress on `/status` and `/queue`.
- Control Panel adds option 89 for a live five-second progress/stage view.
- Progress reporting is derived from the existing queue and delivery-attempt ledger and performs no enqueue, retry, reconciliation, campaign-state or scheduling mutation.
- Cumulative v3.5.2 release retains all v3.5.1 circuit-breaker and Windows self-healing fixes so a v3.5.0 installation needs only one update.

# Smart Auto Poster V3.5.1 - Runtime Safety / Self-Heal Hotfix

- Fixed false global circuit-breaker trips caused by expected SlowMode, FloodWait and short worker-busy timing events being recorded as `send_failure`.
- Timing/back-pressure events now retain specific event types and do not count as failed sends.
- Ambiguous Telegram acknowledgement events now contribute to the breaker risk count while remaining permanently blocked from generic retry.
- Added a five-minute Windows Scheduled Task liveness trigger with `MultipleInstances=IgnoreNew` so external process termination recovers automatically without duplicate runtimes.
- Autostart status now exposes trigger count, repetition interval, next run and multiple-instance policy for incident diagnosis.
- Preserves existing queue, schedule, reconciliation ledger and fail-closed UNCERTAIN behaviour.

# Smart Auto Poster V3.5.0 - Auditable Delivery Reconciliation

- Added schema v8 `delivery_reconciliations` ledger with queue, actor, outcome, evidence and resulting-state history.
- Added `uncertain-list`, `uncertain-reconcile` and `reconciliation-history` commands.
- UNCERTAIN jobs can no longer use generic Retry or Mark Sent operations.
- Confirmed delivery requires `TELEGRAM_HISTORY_CONFIRMED_SENT`; confirmed absence requires `TELEGRAM_HISTORY_CONFIRMED_NOT_SENT` before one job can re-enter retry.
- Unresolved reviews record evidence without mutating or retrying the job.
- Telegram Admin Bot removes the dangerous generic Retry button from UNCERTAIN jobs.
- Control Panel adds read-only uncertain listing and guided evidence-backed reconciliation.
- Includes the v3.4.1 battery-safe autostart and network-aware runtime verifier.

# Smart Auto Poster V3.4.1 - Runtime Readiness Hotfix

- Windows autostart now starts on battery and remains running after switching to battery.
- Added `VERIFY_RUNTIME.ps1`, which waits for the lock and fresh core heartbeats instead of treating lock creation alone as readiness.
- Confirmed Telegram/network outages now produce a safe degraded result while the worker remains paused and queue state is preserved.
- Admin Bot staleness during a confirmed network outage no longer misclassifies a successful update as a code/startup failure.
- Task metadata now accurately declares managed autostart and bounded automatic restart.

# Smart Auto Poster V3.4.0 - Delivery Intelligence

## Goal
Turn retry and uncertain queue states into durable, explainable operational data while keeping ambiguous Telegram deliveries fail-closed.

## Changes
- Added schema v7 `delivery_attempts` history with outcome, account, error kind, retry time, duration and Telegram message IDs.
- Successful, retry, failed, quarantined and uncertain send outcomes now retain per-attempt evidence instead of only the latest queue error.
- Added an actionable failure taxonomy: uncertain, timing, account, permanent destination, transient and terminal/retry other.
- Added `delivery-intelligence` for read-only campaign/destination diagnosis and machine-safe JSON output.
- Added `delivery-recovery`, which previews every action by default and requires `--apply` before closing impossible or exhausted retries.
- UNCERTAIN deliveries remain permanently excluded from automatic retry and are explicitly held for Telegram-history reconciliation.
- Added migration, worker-history, diagnosis and recovery safety regression coverage.

## Commands
```powershell
py .\app.py delivery-intelligence --campaign main_production_01
py .\app.py delivery-intelligence --campaign main_production_01 --json-only
py .\app.py delivery-recovery --campaign main_production_01
py .\app.py delivery-recovery --campaign main_production_01 --apply
```

# Smart Auto Poster V3.3.0 - Fast Pass Production

## Goal
Post to healthy production destinations as quickly as Telegram safely allows, while moving slow/error destinations out of the clean first pass instead of letting one problem hold up the whole cycle.

## Changes
- Production campaign spread defaults to **0 minutes** instead of 20 minutes.
- Queue claim order is now **pending first**, then deferred/retry problem work.
- Successful sends use the configured `MIN_SEND_GAP_SECONDS` (default **3 seconds**) as an intentional inter-send pace rather than causing the next healthy destination to be deferred for pacing.
- Added `SEND_TIMEOUT_SECONDS` (default **45 seconds**). If Telegram does not return a conclusive acknowledgement inside the bound, the job becomes `UNCERTAIN` and the worker continues with untouched destinations.
- Send-timeout uncertainty never auto-retries and does not penalize destination/account health.
- Existing FloodWait, SlowMode, ambiguous acknowledgement, quarantine, circuit-breaker and authorization protections remain active.
- Production bootstrap and `SETUP_MAIN_PRODUCTION.ps1` now use zero spread by default.

## Operating behavior
A normal cycle is queued immediately. Healthy destinations are attempted one after another with a few seconds of pacing. Slow mode, cooldown, retry, deferred or ambiguous destinations leave the clean fast lane and are handled after untouched destinations according to their safe due times.

### V6.0.0 REV2 - Command Prompt Live Dashboard
- Replaced the watch-mode progress report with a terminal-width-aware live dashboard.
- Added high-resolution ASCII overall/pass/current-post progress bars safe for Windows cmd.exe and PowerShell.
- Added focused current-post stage, next destinations, ETA, remaining count, and outcome summary.
- Added compact destination pipeline rows with DEFERRED/RETRY/UNCERTAIN reasons and due times.
- Added stable refresh presentation while preserving JSON and Telegram progress renderers.

## 6.0.1 - Full Coverage Live Run Controller
- Added `live-coverage-run` for an explicit one-post-per-eligible-destination live qualification run.
- Added durable per-destination coverage ledger and JSON/CSV result reports.
- SlowMode/FloodWait/quiet-hour destinations are deferred to later passes rather than skipped.
- Retry-safe failures retain the same queue obligation and remain visible until resolved.
- Existing historical UNCERTAIN/SENDING evidence is never blindly retried or deleted.
- Normal campaign scheduling is disabled during the one-shot run and restored afterwards.
- Added focused troubleshooting reasons for failed/blocked destinations.
- Added `live-coverage-status` terminal dashboard/report export.
