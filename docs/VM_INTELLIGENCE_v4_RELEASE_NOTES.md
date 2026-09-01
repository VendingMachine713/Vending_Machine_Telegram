# VM Intelligence v5.0.0 Release Notes

## Objective-Driven Autonomous Operations Foundation

v4 moves VM Intelligence from a passive analytics layer toward a governed operations control plane.

### Canonical Runtime Registry
Every bot now receives a stable observed runtime identity with canonical root/entrypoint, compatibility entrypoint, management policy, source hash and topology hash. Runtime Bridge shims are explicitly compatibility surfaces; the nested regression-tested implementation remains canonical.

### Platform Normalisation
Architecture hygiene detects unresolved runtimes, duplicate manifests/candidates, deep nesting and active compatibility bridges. Normalisation remains proposal-only: v4 does not move or delete bot source automatically.

### Reliability Brain
Service-level objectives and error budgets track ecosystem score, SAP delivery success/uncertain queue, Admin/Guard availability, managed-service health and backup integrity. Critical reliability breaches recommend an experiment/optimisation freeze.

### Governed Autonomy
Autonomy levels L0 Observe through L7 Objective-Driven are persisted. Default remains L4 Recover. Safe mode/reliability freezes cap effective authority, and all actions are constrained by a registered minimum level, maximum risk, reversibility, backup requirement and cooldown.

### Bounded Objective Plans
Objectives for platform health, safe automation and attention minimisation now emit only registered action keys. Each step is bound to the live autonomy policy and reports whether execution is allowed and why. No objective step executes merely because it was planned.

### Runbooks / Release Gate / Attention Budget
v4 records runbook outcomes, rejects unsafe/regressing release candidates, and tracks useful-vs-noisy feedback plus estimated manual minutes saved.

### Telegram Control Plane
Admin Command Centre gains the v4 surfaces:
`/registry`, `/drift`, `/slo`, `/errorbudget`, `/objective`, `/autonomy`, `/safe`, `/whyact`, `/runbooks`, `/impact`, `/releasegate`, `/attention`.

### Runtime Compatibility
The v3.0.7 Runtime Bridge is consolidated into v4. Tiny reversible root `main.py` shims restore the contract expected by recovered VM Core while delegating to the already-tested nested canonical source. Shims do not duplicate bot business logic.

Installer ordering is fail-closed: bridge discovery is preview-only before the untouched pre-install regression baseline; the bridge is written and compiled only after that baseline passes.

### Safety Boundary
v4 still does not autonomously delete master data, expose credentials, change Telegram identity, weaken security, remove backups, relocate/delete production architecture, auto-promote releases, or rewrite SAP/RM business logic.


## v5.0.0 â€” Windows process lifecycle hotfix

The first live v4.0.0 installation verified the Runtime Bridge and all production bot
baseline suites, then failed inside a legacy v3.0.6 synthetic unit test. That test
intentionally launched a detached temporary Admin process. On Windows the process still
held its temporary working directory when `TemporaryDirectory.cleanup()` ran, producing
WinError 32/5 even though the tested runtime behavior itself had succeeded.

v5.0.0 fixes this in two layers:

- the legacy direct-fallback test now tests `direct_start()` in isolation rather than
  consulting a possibly imported real VM Core;
- Windows cleanup uses `taskkill /T /F`, waits for PID death, and retries temporary
  directory cleanup;
- because v4 production no longer uses `ADMIN_RUNTIME_GATE.py` for deployment, that one
  process-spawning legacy simulation is package-qualification-only and is skipped during
  live installed-runtime regression runs;
- the test remains mandatory in release qualification.

No production bot business logic is changed by this hotfix.


## v5.0.0 â€” Canonical Platform Normalisation + Reliability Engineering

This release accumulates the v4.1 and v4.2 roadmap stages into one production checkpoint.

### Platform normalisation
- Adds an authoritative service registry derived from the tested canonical runtime registry.
- Records service ownership, canonical/compatibility entrypoints, version, lifecycle policy,
  config paths, database paths, dependencies, hashes and last verification time.
- Adds a configuration registry that stores paths and SHA-256 only; secret-bearing config
  contents are never serialized.
- Tracks disappeared previously registered configuration as explicit drift.
- Preserves previous runtime identity across refresh so unexpected runtime moves are visible.
- Adds drift snapshots, scores and proposal-only remediation plans.
- Source relocation, deletion and quarantine remain non-automatic.

### Reliability engineering
- Adds historical SLO compliance and burn-rate calculation.
- Adds 30-day incident counts, recurrence, MTTR and MTBF.
- Adds runbook outcome trust scoring and evidence-based certification:
  unproven â†’ provisional â†’ certified.
- Reliability burn or exhausted error budgets can freeze experiments, but cannot grant
  additional autonomy.
- Adds `/configreg`, `/reliability` and `/runbooktrust`.

Default autonomy remains L4 Recover.
