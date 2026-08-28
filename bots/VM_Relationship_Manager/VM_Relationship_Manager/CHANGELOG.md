
# VM Relationship Manager Changelog

## 1.0.2 — 2026-08-27

- Added `tzdata` as an explicit dependency for reliable IANA timezone support on Windows.
- Fixed the `ZoneInfoNotFoundError: Australia/Adelaide` startup failure seen on Windows Python.
- Launcher now checks dependencies and Adelaide timezone support before starting the bot.
- Added `preflight.py` to validate required configuration without displaying secrets.
- Added `START_VM_RELATIONSHIPS.bat` so normal Windows launching no longer requires manually changing PowerShell execution policy.
- Reordered startup checks so missing dependencies are repaired before the smoke test/startup stages.
- This is an incremental update: only changed/new files are included.

## 1.0.1 — 2026-08-27

- Moved the bot into its permanent master-project folder.
- Routed database exports, backups and logs into the master shared folders.
- Added rotating file logging.
- Added startup/task supervision so monitoring failures cannot silently leave a half-running service.
- Corrected weekly digest weekday mapping for python-telegram-bot.
- Added `START_VM_RELATIONSHIPS.ps1` launcher.
- Added smoke testing before launch.
- Kept metadata-first monitoring; raw message bodies are not archived by default.

## Update policy

Future releases update this permanent folder in place. Only changed/new files should be distributed unless a full rebuild is genuinely required.
