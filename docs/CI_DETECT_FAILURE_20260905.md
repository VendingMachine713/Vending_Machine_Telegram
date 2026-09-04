# VM Platform CI — Detect affected components failure (2026-09-05)

## Observed behaviour

Multiple unrelated pull requests started failing in the first `Detect affected components` job before any job steps were exposed. Every downstream job was skipped.

Observed independent PR heads:

- PR #94 — Smart Auto Poster preserved-source recovery: run `33896392924` failed in `Detect affected components`.
- PR #96 — VM Brain promotion-gate hardening: run `33896921130` failed in `Detect affected components`.
- PR #97 — Smart Auto Poster delivery reconciliation: runs `33897059659` and `33897264961` failed in `Detect affected components`.

For these runs the job API reports `steps: null`, indicating the failure occurs before the repository-specific compile/test jobs execute. Re-running the failed job on run `33897059659` reproduced the same result.

## Interpretation

Because the same pre-step failure affects unrelated branches/components while the workflow definition is unchanged from earlier successful runs, do not classify downstream bot code as failed from these runs. Treat CI as infrastructure/bootstrap blocked until `Detect affected components` can start normally.

## Safety rule

Do not merge a code PR merely because downstream tests were skipped. Once CI execution is restored, require the normal affected-component quality gate to pass before merge.

## Recovery

1. Retry a failed workflow after the runner/account condition clears.
2. Confirm `Detect affected components` exposes normal checkout/detection steps.
3. Require the appropriate component tests and platform validation to run/pass.
4. Keep deployment/live verification separate from CI success.
