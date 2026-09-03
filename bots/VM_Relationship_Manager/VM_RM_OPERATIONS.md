# VM Relationship Manager v6 Operations

## Normal operation

The bot is designed for admin-by-exception operation. `SAFE` autonomy may maintain reversible metadata and apply only high-confidence safe relationship classifications. It never messages contacts automatically.

Use `/exceptions` for the policy-budgeted work queue, `/brief` for the executive view, `/ops` for process/SLO health, and `/doctor` for integrity/backup diagnostics.

## Background service mode

`INSTALL_VM_RM_AUTOSTART.ps1` registers a current-user Windows Scheduled Task named `VM_Relationship_Manager`. It launches `RUN_VM_RM_WATCHDOG.ps1` at logon. The watchdog restarts the Relationship Manager after unexpected process exits.

A process-level OS lock prevents a background copy and a manually launched copy from polling the same Telegram bot/session simultaneously.

Control scripts:

- `START_VM_RM_BACKGROUND.ps1`
- `STOP_VM_RM_BACKGROUND.ps1`
- `VM_RM_BACKGROUND_STATUS.ps1`
- `REMOVE_VM_RM_AUTOSTART.ps1`

## Safe updates

`APPLY_VM_RM_UPDATE.ps1` can apply future direct-update ZIPs. It rejects update ZIPs containing `.env`, Telethon session files, runtime state, or databases. It snapshots files that will be replaced, applies the update, runs `smoke_test.py`, and automatically restores code if the smoke test fails.

`ROLLBACK_VM_RM_CODE.ps1` restores the most recent code snapshot manually if required. Code rollback never restores `.env`, Telegram sessions, or the CRM database.

Major schema upgrades create verified pre-upgrade and post-upgrade SQLite backups independently of code rollback.
