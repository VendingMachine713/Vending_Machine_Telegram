# VM Relationship Manager v6.0.0

Private Telegram CRM, relationship intelligence and admin-by-exception operations layer for the Vending Machine Telegram ecosystem.

## Operating model

**Monitor passively -> learn safely -> maintain metadata -> surface only exceptions -> recover automatically.**

SAFE autonomy may perform reversible metadata maintenance and high-confidence safe relationship classification. It does **not** send messages to contacts automatically and does not make external commercial decisions.

## v6 core

- Permanent Telegram ID identity with alias history.
- Relationship, trust, health, momentum, lifecycle, reciprocity and network intelligence.
- Goals, opportunity pipeline, risk/verification review, dynamic segments and metadata-only conversation-session analytics.
- Confidence-aware relationship forecasts and data-quality scores.
- Feedback-calibrated automatic relationship classification with abstention, manual locks and per-type quarantine.
- Deduplicated recommended-action queue with dismissal/done cooldowns.
- Workload-budgeted exception inbox where critical actions bypass normal limits.
- Executive brief, daily/weekly digests and privacy-safe exports.
- Integration event contract v6 with UUIDs, idempotency, priorities and bounded JSONL outbox.
- Operational SLO snapshots, `/ops`, `/doctor` and self-healing maintenance.
- Verified SQLite backups and additive migrations.
- Single-instance process lock, Windows watchdog/autostart helpers and safe future-update rollback tooling.

## Main admin commands

- `/rm` - control centre
- `/brief` - executive exception brief
- `/exceptions` - policy-budgeted exception inbox
- `/today` - full ranked relationship priorities
- `/person ID|@username` - contact profile
- `/autonomy [observe|assist|safe]` - autonomy mode
- `/classify [ID]` - classifier/review backlog
- `/calibration` - feedback calibration and quarantines
- `/policy` - exception budget/cooldown policy
- `/actions [ID]` - recommended actions
- `/actiondismiss ACTION_ID` - dismiss with cooldown
- `/maintain` - safe local maintenance
- `/ops` - operational SLO health
- `/doctor` - integrity/backup/runtime doctor
- `/diagnostics` - deeper system diagnostics

## Runtime state that updates must never replace

- `.env`
- `runtime/*.session`
- `runtime/*.session-journal`
- live shared SQLite database
- shared exports/backups/logs

## Windows passive operation

After live verification:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\INSTALL_VM_RM_AUTOSTART.ps1"
```

Status:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\VM_RM_BACKGROUND_STATUS.ps1"
```

See `VM_RM_OPERATIONS.md` for watchdog/update/rollback details.
