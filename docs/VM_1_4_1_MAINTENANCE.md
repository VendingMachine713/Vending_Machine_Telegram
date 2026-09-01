# VM Platform v1.4.1 Maintenance

This is an incremental patch over VM Core v1.4.0.

It addresses the live post-v1.4 findings:
- Smart Auto Poster advisory tests missing `GO_LIVE.ps1`
- Smart Auto Poster advisory tests missing `master_updater/APPLY_UPDATE.ps1`
- stale hard-coded Smart Auto Poster control-panel version text
- VM Guard historical warning-burst alert staying open after recovery

Smart Auto Poster repair sources missing files only from existing local pre-v1.3/pre-v1.4 safety snapshots.
The repair is accepted only when the bot's own complete test suite, `app.py validate`, and
`app.py integrity` all pass. Otherwise the files changed by the repair are rolled back.

Relationship Manager nested cleanup is deliberately preview-only in this maintenance installer. The separate APPLY_RELATIONSHIP_CLEANUP script requires explicit typed approval before archive + removal.

## Safety gates

- Smart Auto Poster source repair refuses to run while its runtime lock belongs to a live process.
- Every recovered operational file must pass its exact v3 contract test.
- The full Smart Auto Poster suite, `app.py validate`, and `app.py integrity` must pass or the repair restores its previous files.
- Relationship Manager cleanup is preview-only during maintenance. `APPLY_RELATIONSHIP_CLEANUP.bat` requires the exact local approval phrase before deletion.
- Relationship cleanup archives both the nested copy and potentially touched canonical files, verifies archive entries with SHA-256, then removes only the nested legacy folder.
