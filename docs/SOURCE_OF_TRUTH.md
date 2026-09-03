# VM Source of Truth Policy

## Purpose

The Vending Machine Telegram repository is intended to become the canonical source for production-capable source code, tests, manifests, migrations, launchers and documentation.

The local Windows project remains the runtime environment. Runtime state, Telegram sessions, live databases, logs, backups, generated diagnostics and credentials are local-only and must not become part of Git history.

## Canonical flow

```text
Local Windows runtime
        ↕
      GitHub
        ↕
     ChatGPT
```

GitHub becomes authoritative only after local and remote source are reconciled and validated.

## Canonical bot folders

```text
bots/Smart_Auto_Poster_V2/
bots/VM_Guard/
bots/Universal_Search/
bots/Admin_Command_Centre/
bots/VM_Relationship_Manager/
```

Each bot must have one canonical production source directory. Same-name nested bot copies are legacy/reconciliation candidates and must not be deleted until their unique/different files have been reviewed and an archive has been verified.

## Source that belongs in Git

Typical examples:

- Python source
- PowerShell/BAT launchers
- tests
- manifests
- migrations
- documentation
- dependency declarations
- safe configuration templates such as `.env.example`

## Local-only material

Never intentionally commit:

- `.env` or credentials
- Telegram `*.session` files
- API hashes/tokens
- live SQLite/database files
- WAL/SHM database files
- logs
- runtime locks/PIDs
- private exports
- generated support bundles
- backups
- caches
- generated diagnostics containing runtime metadata

`.gitignore` prevents new accidental additions but does not remove already tracked files. Tracked-file auditing is therefore required separately.

## Reconciliation rule

Do not resolve conflicts by timestamp alone.

Prefer evidence in this order:

1. currently working and tested implementation
2. newer validated fix
3. unique valid functionality
4. documentation/history that does not conflict with current behavior

Every reconciliation should identify files as one of:

```text
SAME
LOCAL_NEWER
GITHUB_NEWER
NESTED_ONLY
OUTER_ONLY
CONFLICT
GENERATED
SENSITIVE
OBSOLETE
```

## Relationship Manager first

`VM_Relationship_Manager` is the first bot to be reconciled because the repository currently contains both the canonical outer folder and a same-name nested legacy copy.

The read-only reconciliation tooling lives in:

```text
shared/vm_core/source_of_truth.py
shared/vm_core/reconciliation.py
tools/ci/source_of_truth_report.py
```

It must remain read-only until an explicit destructive cleanup approval is given.

## Validation target

Phase 0 is complete only when:

- one canonical folder exists per bot
- bot version metadata is consistent
- Git contains no credentials, sessions or live databases
- generated runtime material is not tracked
- local and GitHub source are reconciled
- CI passes
- source drift can be detected automatically
- future large changes use a safe development branch and validation gate before `main`

## Operating model

Normal development should use a GitHub development branch, automated tests and large coherent milestones. Local Windows execution should be required only for real runtime/Telegram validation or for reconciling local-only uncommitted work.
