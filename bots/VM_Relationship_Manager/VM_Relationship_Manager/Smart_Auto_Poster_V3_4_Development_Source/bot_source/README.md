# Smart Auto Poster V3.3.0

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
