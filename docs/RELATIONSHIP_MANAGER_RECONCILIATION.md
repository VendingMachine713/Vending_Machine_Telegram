# VM Relationship Manager Reconciliation Record

## Status

**Phase 0 / read-only reconciliation in progress.**

No nested Relationship Manager file has been deleted, moved or replaced by this work. The purpose of this record is to preserve the evidence needed for an eventual approval-gated cleanup after the Windows working tree is reconciled.

## GitHub-side structure observed

Canonical candidate:

```text
bots/VM_Relationship_Manager/
```

Legacy nested candidate:

```text
bots/VM_Relationship_Manager/VM_Relationship_Manager/
```

## Version evidence

Outer canonical candidate:

```text
VERSION.txt          -> 1.2.0
BOT_MANIFEST.json    -> 1.2.0
```

Nested legacy candidate:

```text
VERSION.txt          -> 1.0.2
```

This establishes that the nested copy is older on the checked-in GitHub branch. It does **not** by itself establish that GitHub contains the newest Windows-local source; local reconciliation is still required before GitHub can be declared authoritative.

## File comparison evidence

Checked-in SHA evidence shows these files are exact outer/nested duplicates:

```text
START_VM_RELATIONSHIPS.bat
preflight.py
requirements.txt
```

These files differ between outer and nested copies:

```text
CHANGELOG.md
README.md
START_VM_RELATIONSHIPS.ps1
VERSION.txt
```

The outer folder also contains the actual application source that does not exist in the nested legacy copy, including:

```text
admin_bot.py
config.py
database.py
diagnose_bot.py
diagnose_updates.py
jobs.py
main.py
monitor.py
relationship_engine.py
smoke_test.py
```

## Reconciliation decisions already safe to make

### Historical changelog

The nested 1.0.1 and 1.0.2 release history was unique historical documentation. Those entries have now been copied into the canonical outer `CHANGELOG.md` so that information will not be lost if the nested copy is archived later.

### Launcher

The outer launcher is the stronger/current checked-in implementation. Unlike the nested v1.0.2 launcher, it:

- reads the displayed build dynamically from `VERSION.txt` rather than hard-coding `v1.0.2`;
- handles native Python stderr without allowing expected dependency-check stderr to become a terminating PowerShell error;
- verifies dependency/timezone support after installation;
- preserves and returns explicit process exit codes.

The nested launcher therefore must not replace the outer launcher.

### Exact duplicates

The exact-duplicate BAT launcher, `preflight.py` and `requirements.txt` carry no unique checked-in content in the nested copy.

## Remaining gates before cleanup

The nested folder must remain untouched until all of the following are true:

1. the Windows-local Relationship Manager source has been surfaced on a safe sync branch;
2. local vs GitHub differences have been reviewed;
3. current version metadata has been resolved;
4. all current Relationship Manager and platform tests pass;
5. an archive of the nested copy is created and SHA-256 verified;
6. explicit destructive cleanup approval is provided.

## Intended end state

```text
bots/
└── VM_Relationship_Manager/
    ├── one canonical production source tree
    ├── tests / smoke checks
    ├── launchers
    ├── documentation
    └── safe config templates
```

No `.env`, Telegram session, live relationship database, log or runtime backup belongs in Git history.
