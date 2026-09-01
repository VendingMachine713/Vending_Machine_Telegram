# Upgrade to VM Relationship Manager 6.0.0

v6 is an additive in-place migration from the verified v5 line. It preserves the live CRM database, `.env`, Telethon sessions and shared history.

## First startup safeguards

1. The process-level single-instance lock prevents duplicate polling instances.
2. If the live database schema is older than 6.0.0, `pre_upgrade_backup()` creates a verified `pre_v6_*.db` snapshot tied to the current live database SHA-256.
3. `Database` applies additive v6 tables/columns and updates the schema marker to 6.0.0.
4. A verified `post_v6_upgrade` SQLite backup is created before the v6 policy bootstrap is marked complete.
5. Classifier calibration, safe classification, priority/action policy, segments and integration export are refreshed.

## Credential recovery continuity

v6 includes the v5.0.2 session-first configuration fixes and `RECOVER_VM_RM_ENV_DEEP_R2.*`. `TELEGRAM_PHONE` is optional while the saved authorised `runtime/vm_relationship_backup.session` remains valid.

## Background operation

After live v6 verification, `INSTALL_VM_RM_AUTOSTART.ps1` can install current-user logon autostart and watchdog recovery. This changes Windows Task Scheduler state and should only be run deliberately by the user.

## Rollback safety

`APPLY_VM_RM_UPDATE.ps1` automatically rolls code back if a future package fails its pre-start smoke test. Once a major schema migration has actually run, do not manually roll code back to an older major version without pairing it with the appropriate pre-upgrade database recovery plan.
