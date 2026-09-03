VM Relationship Manager — temporary monitoring-account switch

Purpose:
- Switch Telethon monitoring from the currently configured main Telegram account
  to a backup Telegram account when the main account cannot be accessed.
- Preserve the existing main-account Telethon session.
- Optionally add the backup account to ADMIN_IDS.

Run from the permanent VM Relationship Manager folder:

powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\SWITCH_VM_RM_TO_BACKUP.ps1"

Then restart:
.\START_VM_RELATIONSHIPS.bat

The first backup-account startup will ask for the Telegram login code sent to that
backup account. If the backup account uses Telegram 2FA, its password may also
be requested.

The script creates a local .env backup before changing anything and uses:
SESSION_NAME=runtime/vm_relationship_backup

It does not contain credentials.
