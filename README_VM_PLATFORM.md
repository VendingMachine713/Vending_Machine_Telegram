# VM Ecosystem v1.4.3

v1.4.3 is a cumulative maintenance patch for the installed v1.4 platform.

## Why this release exists

The live v1.4.2 maintenance transcript showed Smart Auto Poster had already advanced to v3.2.2.
Its required `GO_LIVE.ps1` and `master_updater/APPLY_UPDATE.ps1` files were present, but the
maintenance repair still tried to run two historical v3.0 unittest method names that no longer
exist in the v3.2.2 suite. That caused valid current files to be rejected and the installer
correctly rolled back.

v1.4.3 makes maintenance version-adaptive:
- existing required Auto Poster files are preserved;
- local snapshot/ZIP recovery runs only if an artifact is actually missing;
- historical exact test methods are used only when the installed test suite still contains them;
- acceptance is governed by the installed Auto Poster's complete current test suite plus
  `app.py validate` and `app.py integrity`;
- no Auto Poster production activation, new canary enqueue or Telegram send occurs.

## Other retained hardening

- VM Guard warning-burst alerts use a 15-minute window rather than historical warnings forever.
- maintenance always writes a success/failure transcript to Downloads;
- pre-install rollback snapshots are created before extraction;
- managed services are stopped before platform code reload and restarted afterward;
- Relationship Manager nested-folder cleanup remains preview-only during maintenance.
