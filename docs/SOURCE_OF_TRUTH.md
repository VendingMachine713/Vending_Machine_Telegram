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

## One-run Windows reconciliation

The long-term workflow must not require repeated PowerShell/download/report cycles. The repository therefore includes a guarded one-run local source surfacing path:

```text
SYNC_WINDOWS_TO_GITHUB.bat
        ↓
SYNC_WINDOWS_TO_GITHUB.ps1
        ↓
source audit
        ↓
secret guard
        ↓
source-only safety snapshot
        ↓
create isolated sync/windows-* branch
        ↓
stage working tree
        ↓
remove generated/runtime paths from staged commit
        ↓
secret scan staged content
        ↓
commit source snapshot
        ↓
push private sync branch
```

The process **never pushes directly to `main`**. Once the branch exists, ChatGPT/GitHub tooling can inspect and reconcile the Windows source remotely without requiring the user to repeatedly export reports.

A result marker is written to:

```text
%USERPROFILE%\Downloads\VM_GITHUB_SYNC_RESULT.txt
```

but normally the branch itself is sufficient evidence because it can be discovered directly through the connected GitHub account.

## Safety layers

Local reconciliation uses multiple independent protections:

1. root `.gitignore` prevents common runtime/secret additions;
2. `tools/vm_core/git/git_guard.py` scans trackable/staged content for obvious credentials;
3. `shared/vm_core/source_of_truth.py` classifies sensitive and generated paths;
4. `tools/ci/staged_source_policy.py` removes generated/runtime paths from the staged source snapshot and blocks sensitive filenames;
5. `git diff --cached --check` runs before commit;
6. the commit is pushed to a temporary reconciliation branch rather than `main`;
7. merge to `main` remains a separate reviewed action.

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

After Phase 0, the preferred development loop is:

```text
request
  ↓
GitHub development branch
  ↓
large coherent implementation
  ↓
automated tests / review
  ↓
merge-ready milestone
  ↓
one local runtime validation when genuinely needed
```
