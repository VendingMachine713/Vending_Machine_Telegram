# VM Relationship Manager 6.0.0

## Internal 5.1 -> 5.9 cycle consolidated into v6

### 5.1 - Feedback-calibrated classification
- Added per-type classifier calibration based only on explicit admin acceptance/override feedback.
- Calibration can never lower the global safety threshold.
- Repeated disagreement raises thresholds and can quarantine a relationship type from automatic application.
- Manual classifications remain locked against automation.

### 5.2 - Action fatigue protection
- Dismissed actions receive a configurable cooldown instead of respawning on the next maintenance pass.
- Completed actions receive a shorter cooldown.
- Added action feedback and occurrence tracking.

### 5.3 - Exception workload policy
- Added a daily exception budget and per-contact cap for routine work.
- Critical actions bypass the normal budget and are never hidden because the queue is full.
- `/exceptions`, daily digests and `/brief` now use the policy-selected queue.

### 5.4 - Integration contract v6
- Added event UUIDs, event versions, hourly idempotency keys and priorities.
- Duplicate event emissions in the same contract bucket are suppressed.
- JSONL outbox is bounded/rotated and exports contract version 6.0.
- Contact index exports schema 6.0.0.

### 5.5 - Operational SLO health
- Added persistent operational health snapshots and `/ops`.
- Health tracks process heartbeat, monitor, scheduler, admin bot, backups, integration retries and intelligence freshness.
- `/doctor`, diagnostics, reports and maintenance now include operational health/policy state.

### 5.6 - Single-instance process safety
- Added an OS-backed process lock so background and manual instances cannot poll the same Telegram bot/session concurrently.

### 5.7 - Windows passive-service layer
- Added logon autostart Scheduled Task tooling and a bounded watchdog with restart backoff.
- Added background start, stop, status and removal helpers.

### 5.8 - Transaction-style update tooling
- Added protected-file checks for future direct-update ZIPs.
- Added code snapshots and automatic rollback when a new package fails its smoke test.
- Runtime `.env`, Telegram sessions and databases are outside code rollback.

### 5.9 - Production hardening
- v5 -> v6 additive migration tests.
- Verified pre-v6 safety backup support and post-v6 verified backup on first startup.
- Added retention for action feedback, classifier feedback and operational snapshots.
- Strengthened launcher dependency-version checks and session-first preflight.
- Added v6 release test suite and expanded local doctor.

## 6.0.0 - Passive Autonomy and Operations
The above stages are consolidated into one dependency-closed major release. SAFE mode remains metadata-only and never sends messages to contacts automatically.
