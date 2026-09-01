# Smart Auto Poster V6.0.0

V6 is the self-managing production control-plane release. It keeps the existing one-post-per-group and evidence-preservation rules while adding destination intelligence, predictive timing, explainable delivery confidence, objective-based production health and recovery planning.

Key commands:

```powershell
py .\app.py v6-control --campaign main_production_01
py .\app.py v6-intelligence
py .\app.py v6-confidence --campaign main_production_01
py .\app.py v6-plan --campaign main_production_01
py .\app.py v6-recovery
```

Telegram Admin Bot: `/v6` or `/control`.

Safety invariants remain unchanged: one unresolved obligation per group, no generic UNCERTAIN retry, no NOT_SENT inference from missing history, and production stays fail-closed while evidence blockers remain.

# Smart Auto Poster V5.0.0

V5 is the autonomous production-controller milestone. It preserves the V4 round/pass engine and per-post pipeline, then adds evidence-aware legacy queue cleanup, a database-level one-unresolved-post-per-group guard, account-specific format routing, learned destination timing profiles, persistent run ledgers and a strict production gate.

Core V5 commands:

```powershell
py .\app.py queue-hygiene
py .\app.py queue-hygiene --apply
py .\app.py v5-readiness --campaign main_production_01
py .\app.py mission-control --campaign main_production_01
py .\app.py progress --campaign main_production_01 --watch --interval 5
```

Telegram Admin Bot: `/mission`, `/progress`, `/post <id>`, `/gate`, `/hygiene`.

V5 never generically retries UNCERTAIN sends. Queue hygiene only cancels rows whose local state and attempt ledger prove that no Telegram acknowledgement or ambiguity exists.

# Smart Auto Poster V4.0.1

## One-post-per-group round engine

V4 executes each auto-post cycle as passes. Every selected group receives exactly one queue row for the cycle. Healthy groups move through Pass 1 immediately; SlowMode, FloodWait, account cooldown, quiet-hours and other retry-safe waits defer that **same row** to a later pass so the worker moves on to untouched groups. Pass 2 cannot begin until Pass 1 for that run has drained.

A group cannot accumulate another unresolved post from a later schedule or another campaign. `SENDING` and `UNCERTAIN` states block all other rows for that group until the outcome is resolved. This is the primary anti-spam invariant.

## Mixed text and photo groups

Destination mode is authoritative at send time. A media-bearing ad with a caption can satisfy both modes: photo destinations receive the media group, while text-only destinations receive the caption without media. Telegram scan/failure evidence can learn definitive format restrictions and safely switch future delivery mode without creating another queue row.

## Progress and Mission Control

```powershell
py .\app.py progress --campaign main_production_01 --watch --interval 5
py .\app.py mission-control --campaign main_production_01
py .\app.py job-timeline 36
```

`progress` provides overall and per-group bars, pass number, due time, account, format, defer/retry reason, ETA and stuck detection. `job-timeline` provides a step checklist and durable history for one post. `mission-control` provides an operational summary plus the global anti-spam overlap check.

Private Telegram Admin Bot commands:

```text
/progress
/mission
/post <queue_id>
```

## Safety invariants

- No generic automatic retry for `UNCERTAIN` Telegram delivery.
- SlowMode/FloodWait do not consume the normal retry budget.
- Timing waits do not poison the global circuit breaker.
- Definitive format errors may fall back only when non-delivery is proven and compatible content exists.
- Permanent permission/content failures do not loop forever.
- A successful post suppresses legacy unresolved duplicates for that group.
- Windows managed runtime remains self-healing with duplicate-instance suppression.

# Smart Auto Poster V3.5.2

## Live auto-post progress and stages

V3.5.2 adds a read-only progress view for the latest posting cycle. It shows an overall progress bar plus the current stage of each destination, including explicit SENT and DEFERRED outcomes, account selection, retry/defer due times and safe failure/UNCERTAIN states.

```powershell
py .\app.py progress
py .\app.py progress --campaign main_production_01
py .\app.py progress --campaign main_production_01 --watch --interval 5
```

From the private Telegram Admin Bot use `/progress` or tap **ðŸ“Š Progress**. The progress message includes a **ðŸ”„ Refresh progress** button. `/status` and `/queue` also show the latest run's overall bar.

Progress is observational only: it does not create jobs, retry sends, reconcile UNCERTAIN jobs, change campaign state or modify the production schedule.

# Smart Auto Poster V3.5.1

## V3.5.1 runtime safety hotfix

V3.5.1 separates expected Telegram timing/back-pressure from true send failures so SlowMode, FloodWait and short worker-busy deferrals cannot falsely trip the global circuit breaker. Ambiguous Telegram acknowledgements now count toward the breaker as risky outcomes while remaining blocked from automatic retry. Windows unattended startup also has a five-minute liveness trigger with `MultipleInstances=IgnoreNew`, so an externally terminated managed runtime is automatically restarted without creating a second bot process. `AUTOSTART_STATUS.ps1` reports the trigger count, repetition interval and next run for liveness diagnosis.

## Delivery intelligence

V3.4 records every delivery attempt and explains unresolved work by failure family, destination, account and recommended action. Diagnosis is read-only. Recovery planning is also read-only unless `--apply` is explicitly supplied, and uncertain Telegram acknowledgements are never automatically retried.

```powershell
py .\app.py delivery-intelligence --campaign main_production_01
py .\app.py delivery-recovery --campaign main_production_01
```

## Fast Pass production

V3.3.0 changes production delivery from deliberately spread-out posting to a fast clean-first pass. New production cycles have zero spread, untouched pending destinations are always attempted before retry/deferred problem jobs, successful sends are paced by `MIN_SEND_GAP_SECONDS` (default 3 seconds), and any Telegram request without a conclusive acknowledgement within `SEND_TIMEOUT_SECONDS` (default 45 seconds) is moved to UNCERTAIN rather than blocking or being blindly resent. Existing Telegram FloodWait/SlowMode, duplicate-prevention, quarantine and circuit-breaker safeguards remain active.

## V3.2.2 test-isolation hardening

## V3.2.6 guarded go-live state recovery

V3.2.6 makes go-live idempotent after a failed rollout. If production is marked ACTIVE but the managed runtime is stopped and there are zero unresolved queue jobs, the go-live script first proves that the only failing readiness conditions are the ACTIVE lifecycle flags, normalizes the campaign to READY/inactive, and only then creates the rollback snapshot. Any additional safety problem aborts normalization. Failed activation verifies the restored lifecycle is READY/inactive.


Go-live regression tests now run with project `.env` loading disabled so temporary test fixtures cannot be overwritten by the live bot configuration. Normal production `.env` precedence remains unchanged outside explicit test mode.

# Smart Auto Poster V3.2.2

Production-handoff release for the verified 32-destination, five-variant 10-photo album campaign.

The final guarded path is `GO_LIVE.ps1`. It performs strict readiness checks, verifies Telegram account sessions without sending, takes an off-OneDrive recovery snapshot, re-arms the 4-hour schedule from activation time, activates only with the explicit `ACTIVATE_32_ALBUM_PRODUCTION_4H` token, installs/starts the managed Windows service, and verifies service/scheduler/worker heartbeats. It performs no immediate `Post Now`.

If any post-activation safety invariant fails, the managed service is stopped and the pre-go-live SQLite snapshot is restored.


## V3.2.3 managed Admin Bot startup
The private Admin Bot uses an in-memory Telethon session by default (`ADMIN_BOT_PERSIST_SESSION=0`). Bot-token login does not require a persistent SQLite session, so this avoids file-lock/stale-session failures during unattended Windows startup. Set `ADMIN_BOT_PERSIST_SESSION=1` only if you explicitly need the legacy persistent session behavior.

## V3.2.5 go-live stability
The guarded Windows go-live now accounts for the scheduler's normal 15-second tick cadence. Scheduler heartbeat freshness is accepted up to 45 seconds while service, queue worker and Telegram Admin Bot remain capped at 20 seconds. Failed starts also clean verified stale runtime locks so a fail-closed rollback does not block the next safe activation attempt.


## V3.2.5 runtime-lock recovery
If Windows Scheduled Task shutdown leaves the child Smart Auto Poster Python runtime alive, go-live recovery verifies the lock owner's PID, recorded start timestamp, live process start time, and runtime executable before terminating it. This avoids both stale-lock loops and unsafe PID-reuse kills.


## Windows console safety (v4.0.1)
Mission Control, progress and job timeline output now adapts to the active Windows console encoding so unusual Telegram group-name symbols cannot crash read-only diagnostics. Telegram Admin Bot output remains Unicode-rich.

## V5.0.2 UNCERTAIN history evidence

Use `py app.py uncertain-scan` for a read-only scan or `py app.py uncertain-scan --apply-sent` to reconcile only unique exact positive Telegram-history matches. The scanner never infers NOT_SENT from absence. Run it with the managed runtime stopped to avoid Telegram session contention.


## V5.0.3 evidence recovery hardening

UNCERTAIN history scanning now recovers missing legacy account attribution from durable attempt/phase history and, when necessary, checks all authorised accounts. Automatic SENT reconciliation still requires one unique exact match in the strict evidence window. A wider diagnostic window is report-only and can never auto-reconcile a delivery. Absence of history is never interpreted as NOT_SENT.

## V6 Command Prompt live dashboard
Run `py app.py progress --campaign main_production_01 --watch --interval 2` for the enhanced Windows-safe live dashboard. It shows overall and pass progress, the current post and stage, next destinations, ETA, outcome counts, and compact per-destination progress bars.

### Full-coverage live qualification
`py app.py live-coverage-run --campaign main_production_01 --poll 2`

This explicit one-shot controller targets every currently eligible destination. Slow/timing-limited groups move to later passes. Every destination remains in the coverage ledger until confirmed SENT or explicitly blocked with a reason. Historical UNCERTAIN sends are evidence-gated and are never blindly retried.
