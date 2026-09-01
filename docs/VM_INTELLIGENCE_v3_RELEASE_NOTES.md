# VM Intelligence v5.0.0 Release Notes

## v5.0.0 nested runtime compatibility hotfix

The live v3.0.4 installation successfully restored VM Core, passed all canonical bot
regression suites, patched Admin safely and completed the first six-source Brain cycle.
Deployment then rolled back only because the restored VM Core v1.4.0 service layer saw
the outer `Admin_Command_Centre` manifest as `entrypoint=None`, while the validated
canonical runtime was in a deeper nested directory.

v5.0.0 repairs that platform/runtime mismatch before installing v3 features:

1. discover the best canonical nested manifest whose entrypoint physically exists
2. preserve the outer manifest's existing lifecycle/custom metadata
3. update only unresolved runtime fields to relative canonical paths
4. dry-run VM Core service resolution for Admin, Universal Search and VM Guard
5. atomically restore the old manifests if verification fails
6. capture Admin's pre-install process state and lifecycle `auto_start`
7. after patching, use VM Core first and then a direct validated-entrypoint fallback only
   when Admin is supposed to be running
8. preserve an intentionally stopped Admin if lifecycle and pre-install state say it
   should remain stopped

The runtime-manifest repair is treated as an independently validated platform repair and
is retained if a later v3 feature gate rolls back.

Live-install tests are also shortened: expensive synthetic VM Core recovery simulations
remain mandatory during release qualification but are skipped during installed-runtime
verification after the real VM Core has already passed its recovery gates.


## v5.0.0 bounded recovery hotfix

v5.0.0 hardens the VM Core recovery stage after the live v3.0.4 run showed that a broad
OneDrive/backup search could provide no console feedback while traversing recovery assets.

Recovery is now deterministic and staged:

1. exact `pre_v1_4_3`, `pre_v1_4_2`, `pre_v1_4_1` ecosystem snapshots
2. shallow project-local recovery directories
3. verified known official release ZIPs
4. Git history
5. bounded project-local recursive fallback
6. bounded external Downloads/OneDrive/LOCALAPPDATA fallback

Every stage prints `[VMCORE]` progress messages. Recursive fallback is capped by
directory count, ZIP count and wall-clock duration. A successful preferred/local candidate
returns immediately; external scanning never runs after an earlier candidate passes.

Qualification: 75/75 tests pass, including all 12 VM Core recovery tests.


## Platform recovery + Integrated Autonomous Brain

v5.0.0 changes the installation strategy after the live v3.0.3 preflight proved that
`shared\vm_core` is physically absent from the current master project.

This release does not manufacture replacement VM Core source.

### VM Core recovery

When `shared\vm_core\__init__.py` is absent, the installer automatically searches the
user's existing project-owned history:

- Git history for `shared/vm_core`
- `backups\` including versioned pre-maintenance snapshots
- `archive\`
- `releases\`
- `updates\backups\`
- `state\support\`
- `state\recovery_candidates\`
- Downloads/Desktop release ZIPs
- LOCALAPPDATA Vending Machine recovery backups

Known official release filenames are SHA-256 checked before use. A known filename with
unexpected bytes is rejected rather than trusted by name.

Candidate preference is provenance-aware. Exact known official release ZIPs rank first;
the known `pre_v1_4_3_ecosystem` snapshot class ranks above older platform snapshots;
Git history and generic recovery backups remain fallbacks.

### Recovery acceptance gate

A recovered VM Core candidate is retained only if all applicable checks succeed:

1. every VM Core module required by current Admin/Search/Guard source exists
2. no `.env`, database, session, private-key, bytecode, symlink or unexpected binary is present
3. ZIP extraction cannot escape the staging directory
4. the VM Core source compiles
5. required modules import in an isolated staging package
6. current Admin Command Centre tests pass
7. current Universal Search tests pass
8. current VM Guard tests pass
9. surviving root platform tests pass when available

Rejected candidates are removed before the next candidate is tried.

An accepted candidate receives a deterministic source-tree SHA-256 fingerprint and the
recovery provenance is stored in:

- `Downloads\VM_CORE_RECOVERY_RESULT.json`
- `Downloads\VM_CORE_RECOVERY_RESULT.txt`
- `state\vm_core_recovery.json`

If no candidate passes, the installer stops before v3 bot integration.

### Previous v3 hotfixes retained

v5.0.0 also retains all prior hardening:

- Windows case-insensitive release path collision rejection
- unexpected release-file rejection
- final SHA-256 manifest generated only after release freeze
- package-only vs installed-runtime test separation
- canonical manifest/entrypoint-aware bot test discovery
- foreign nested development-source rejection
- explicit project import roots for test execution
- rollback-time Admin restart only when Admin was actually patched
- consistent SQLite Intelligence backup before schema upgrade
- automatic v3 feature rollback while retaining a separately validated VM Core recovery

## Integrated Brain milestone

After VM Core is healthy, v3 installs the integrated intelligence operating layer:

- read-only Smart Auto Poster operational intelligence
- read-only Relationship Manager operational intelligence
- Universal Search metrics
- VM Guard/runtime intelligence
- authenticated Admin Command Centre Brain cockpit
- historical metrics and scorecards
- incidents and evidence-based root cause
- postmortems
- recommendations and automation-opportunity discovery
- technical debt, efficiency and code/dependency analysis
- security/config drift intelligence
- predictive maintenance and capacity planning
- operational goals
- experiments, causal labeling and improvement ledger
- release learning and impact-aware test planning
- meta-intelligence and alert usefulness feedback
- Intelligence Inbox and CTO priorities
- safe simulation
- daily/weekly briefs and exception notifications
- bounded self-healing only within VM Core's existing managed-service policy

## Safety boundary

VM Intelligence still does not autonomously delete master data, expose credentials,
change Telegram identities, weaken security, remove backups, perform irreversible
migrations or rewrite Smart Auto Poster / Relationship Manager business logic.
