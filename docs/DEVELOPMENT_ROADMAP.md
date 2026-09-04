# Telegram Platform Development Roadmap

Updated: 2026-09-05

## Current checkpoint

The shared VM Brain path through governed Learning/Feedback v2 is merged. The
current canonical sequence is:

`evidence -> inference -> opportunity -> risk -> prediction -> decision -> operator review -> completion -> verified outcome -> learning feedback`

The system remains advisory. Automatic acceptance, Telegram or external
execution, automatic rule/threshold/trust changes, and automatic conflict
resolution remain disabled.

The live Windows checkout also contains preserved Smart Auto Poster v6 work that
is not yet fully represented by `main`. That reconciliation must be completed
before broad new production behaviour is added.

## Priority 0 - protect and reconcile the source of truth

1. **Protect private runtime inputs.** Keep Relationship Manager business-history
   imports, Telegram sessions, databases, local destination inventories, logs,
   diagnostics, and credentials out of Git. Run the full-history public-release
   audit again after any source reconciliation because the repository is public.
2. **Finish focused Smart Auto Poster v6 reconciliation.** Refresh PR #97 onto
   current `main`, run the full platform and Smart Auto Poster matrices, and merge
   only the targeted delivery-safety changes. Preserve Admin Command Centre as
   the sole Telegram admin owner and keep `UNCERTAIN` jobs fail-closed.
3. **Verify the live Windows cutover.** After the reconciled code is merged,
   compare it with the production checkout, take a rollback backup, confirm zero
   in-flight work, deploy without activating a campaign, and verify one runtime
   owner per service.
4. **Close or supersede stale overlapping PRs.** Review PRs #44, #50-#54, #56,
   and #94 against merged `main` and PR #97. Preserve unique tested changes;
   close branches that are obsolete or unsafe to merge wholesale.

Exit criteria: GitHub and Windows have an explicit, recoverable source-of-truth
relationship; private runtime data is excluded; all five primary services are
healthy; no duplicate Telegram workers or admin owners exist.

## Priority 1 - build the operator intelligence surface

1. **Intelligence Centre.** Create one read-only Mission Control view joining
   service health, canonical evidence health, opportunities, risk, predictions,
   decisions, governance status, outcomes, and learning readiness. It must show
   evidence age, provenance, confidence, and why an item needs attention.
2. **Operator Brief.** Produce a compact daily/on-demand brief ranked by urgency,
   expected value, confidence, freshness, and blocking risk. Deduplicate related
   signals and link every recommendation to its canonical audit timeline.
3. **Exception-first Telegram delivery.** Let Admin Command Centre deliver the
   brief and critical operational exceptions to authorised owners only. Start in
   preview mode, add acknowledgement/dismissal controls, rate limits, quiet hours,
   and duplicate suppression. Do not execute the recommended external action.

Exit criteria: an operator can understand system health and the highest-value
next decisions from one surface without opening five bot-specific dashboards.

## Priority 2 - complete product workflows

1. **Smart Auto Poster forum/topic routing.** Finish passive topic discovery,
   explicit handling of ambiguous forums, account capability coverage, and a
   no-send route preview before any live canary.
2. **Universal Search release chain.** Reassess the previously developed v1.4
   Marketplace Intelligence, v1.5 Demand/WTB matching, and v1.6 Match Engine v2
   against current security and canonical contracts. Rebuild as small PRs instead
   of merging stale stacked branches.
3. **Relationship Manager data quality.** Improve Business Memory import
   validation, deduplication, correction/audit ergonomics, and canonical mapping.
   Defer advanced value and concentration analytics until enough real records
   satisfy issue #92's entry criteria.
4. **Recovery and progress consolidation.** Salvage unique work from older
   recovery/progress PRs only after comparing it with current VM Platform
   heartbeats, telemetry, incident handling, and Admin Command Centre surfaces.

Exit criteria: each product workflow is secure, observable, idempotent, and feeds
the shared Brain through canonical aggregate evidence rather than isolated logic.

## Priority 3 - controlled autonomy

Introduce autonomy in reversible stages:

1. recommendation preview;
2. explicit operator approval;
3. dry-run execution plan;
4. bounded execution for a narrow allowlisted action;
5. post-action verification and rollback;
6. automatic suspension on uncertainty, stale evidence, drift, or degraded health.

High-risk actions stay human-approved. Telegram sends, campaign activation,
threshold/rule/trust changes, conflict resolution, and external mutations require
separate capability gates, immutable audit events, kill switches, rate limits,
and proven rollback paths.

## Delivery rules for every milestone

- Start from current `origin/main` in an isolated worktree.
- Prefer one coherent milestone per PR and avoid parallel frameworks.
- Preserve backwards compatibility and canonical IDs; never expose raw Telegram
  IDs, contact IDs, message content, credentials, or private business imports.
- Add failure, malformed-data, missing-storage, idempotency, and no-authority
  regression coverage.
- Run affected component tests and the complete repository CI matrix on the exact
  PR head. Merge only when the combined tree is green.
- Deploy separately from merge with backup, health verification, rollback, and
  no automatic live campaign activation.
