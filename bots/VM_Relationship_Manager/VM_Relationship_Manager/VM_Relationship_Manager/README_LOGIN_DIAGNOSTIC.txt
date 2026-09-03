VM Relationship Manager — Backup Login Delivery Diagnostic

Run this from the permanent Relationship Manager folder after extracting:

py .\DIAGNOSE_VM_RM_BACKUP_LOGIN.py

The tool:
- uses the already configured backup phone/session,
- requests one fresh Telegram login code,
- reports the delivery method Telegram returned,
- does not print the full phone number, API hash or Telegram code hash,
- lets you complete the login if the code arrives,
- safely exits if no code arrives,
- reports Telegram flood/rate-limit errors clearly.

Do not repeatedly rerun it if Telegram reports a flood/rate-limit wait.
