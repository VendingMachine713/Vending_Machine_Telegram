VM Relationship Manager — Backup Account QR Login

Use this when Telegram reports SentCodeTypeApp but the login code is not visible.

Run from the permanent Relationship Manager folder:

py .\LOGIN_VM_RM_BACKUP_WITH_QR.py

The helper:
- uses the configured backup Telethon session,
- does not touch the main-account session,
- installs the small QR renderer automatically if needed,
- opens a temporary QR image on Windows,
- automatically refreshes expired QR tokens,
- removes temporary QR images after login,
- supports Telegram 2FA with hidden password input.

On the backup Telegram phone:
Settings > Devices > Link Desktop Device / Scan QR Code

Keep the PowerShell helper running while scanning.

After success:
.\START_VM_RELATIONSHIPS.bat
