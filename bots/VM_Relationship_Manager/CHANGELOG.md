# VM Relationship Manager Changelog

## 1.2.0 — Relationship Intelligence + Passive Attention

- Added Relationship Health (0–100), separate from relationship strength and trust.
- Added momentum detection: Learning, Stable, Growing, Surging, Cooling, Fading.
- Added lifecycle intelligence: Discovered, New, Developing, Established, Strong, VIP Candidate, VIP, Cooling, Dormant, Returned.
- Added learned-cycle overdue detection based on each contact's own activity cadence.
- Added smart suggested actions without auto-messaging contacts.
- Added `/today` ranked admin-by-exception inbox.
- Added `/insights`, `/growing`, and `/slipping`.
- Added Intelligence profile button with 7-day vs previous-7-day activity comparison.
- Added passive attention categories for smart follow-up, relationship slipping, critical health and active-unclassified contacts.
- Added daily relationship snapshots for future longer-term trend analysis.
- Dashboard now prioritises Today, Insights, Growing and Slipping.
- Daily/weekly digests now include intelligence and top priorities.
- Intelligence refresh runs locally every 6 hours; database backup remains daily.
- Continues metadata-first privacy: no message-body archive is introduced.
- Existing `.env`, Telegram session and relationship database are not included in this direct update.

## Historical releases recovered from legacy nested copy

The entries below were preserved from the older nested Relationship Manager folder during the Phase 0 source-of-truth reconciliation. They document valid historical work and are retained here so the canonical changelog is complete before the legacy copy is eventually archived.

### 1.0.2 — 2026-08-27

- Added `tzdata` as an explicit dependency for reliable IANA timezone support on Windows.
- Fixed the `ZoneInfoNotFoundError: Australia/Adelaide` startup failure seen on Windows Python.
- Launcher checks dependencies and Adelaide timezone support before starting the bot.
- Added `preflight.py` to validate required configuration without displaying secrets.
- Added `START_VM_RELATIONSHIPS.bat` so normal Windows launching no longer requires manually changing PowerShell execution policy.
- Reordered startup checks so missing dependencies are repaired before smoke-test/startup stages.

### 1.0.1 — 2026-08-27

- Moved the bot into its permanent master-project folder.
- Routed database exports, backups and logs into the master shared folders.
- Added rotating file logging.
- Added startup/task supervision so monitoring failures cannot silently leave a half-running service.
- Corrected weekly digest weekday mapping for python-telegram-bot.
- Added `START_VM_RELATIONSHIPS.ps1` launcher.
- Added smoke testing before launch.
- Kept metadata-first monitoring; raw message bodies are not archived by default.

## Update policy

Future releases update the permanent canonical folder in place. Only changed/new files should be distributed unless a full rebuild is genuinely required.
