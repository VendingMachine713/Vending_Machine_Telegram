# Autonomous Operations

`START_VM_MANAGED.bat` starts only services whose manifests explicitly opt into `auto_start`.

v1.3 opts in:
- Admin Command Centre
- Universal Search
- VM Guard

VM Guard checks the ecosystem every 60 seconds and can restart only services whose manifests
explicitly set auto-start/auto-restart.

Windows logon startup is implemented by the scheduled task `VendingMachineTelegram`.
It can be removed at any time with `DISABLE_VM_AUTOSTART.bat`.

Smart Auto Poster and Relationship Manager are not automatically started by v1.3 because their
existing lifecycle policies are preserved.
