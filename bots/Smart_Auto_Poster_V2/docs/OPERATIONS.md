# V2.4 Operations Summary

Routine operation should use the Telegram Admin Control Centre once configured. The Windows Control Panel remains the recovery/maintenance interface.

Core safety rules:
- New destinations are REVIEW + disabled.
- `NEVER_AUTO_POST` is a hard block.
- Protected destinations require campaigns that explicitly allow protected targets.
- A paused/draft/archived campaign cannot have queued work claimed by the worker.
- Archived or end-date-expired queued jobs become `expired` during maintenance.
- FloodWait cools the affected account; SlowMode updates destination eligibility; network failures do not blame healthy destinations.
- Repeated permanent destination failures quarantine that destination.
- Interrupted in-flight jobs become `uncertain`.
- Circuit breaker can pause outbound posting globally.

V2.4 performs automatic rescans, backups, maintenance, network checks, account health refresh, watchdog heartbeats, daily summaries and weekly summaries while the full service is running.
