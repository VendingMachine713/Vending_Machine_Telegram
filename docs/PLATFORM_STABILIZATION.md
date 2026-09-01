# Platform stabilization and reconciliation

Use the stabilization gate before releases, Git reconciliation, installation, recovery, or enabling production delivery.

```powershell
py -m shared.vm_core.cli backup create
py -m shared.vm_intelligence.cli --root . backup
py -m shared.vm_core.cli stabilize
```

The command is fail-closed and does not start, stop, restart, install, restore, post, or change Telegram sessions. It checks runtime liveness, configuration, live SQLite integrity, both platform and Intelligence backup families, Git/v6 drift, PowerShell syntax, and the required v6 installer, bootstrap, and release manifest.

Reports are written to `diagnostics/stabilization_report.json` and `diagnostics/stabilization_report.txt`.

## Release gate

`release_ready` is true only when there are no warnings or failures. A stopped runtime, dirty working tree, v6 difference, corrupt database, corrupt backup, or invalid recovery script blocks release readiness.

Do not merge or pull over a dirty production checkout. Reconcile in an isolated Git worktree, run the complete test suite there, and retain the production checkout only for runtime data until the candidate is accepted.

## Safe reconciliation sequence

1. Create both backups and verify the resulting ZIP archives.
2. Run `stabilize` and retain its report.
3. Classify working-tree paths as source, configuration template, runtime state, generated diagnostic, or accidental duplicate.
4. Copy source-only changes into an isolated branch/worktree based on the selected GitHub v6 reference.
5. Run compile, lint, unit, integration, installer parser, and recovery dry-run checks.
6. Commit focused changes. Never commit `.env`, Telegram sessions, live databases, logs, locks, PIDs, or credentials.
7. Deploy through the installer only after backup and rollback previews pass.
8. Re-run `stabilize`; preserve the pre- and post-deployment reports.

## Runtime recovery boundary

Do not automatically restart Smart Auto Poster when its Telegram session reports wrong-session-ID, concurrent-runtime, uncertain-send, or acknowledgement-timeout evidence. Pause delivery, identify the single session owner, reconcile delivery history, and only then perform a controlled restart. This prevents duplicate posting.
