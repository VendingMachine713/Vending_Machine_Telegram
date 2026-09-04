# VM Brain Operator Readiness Surface

## Purpose

Mission Control exposes the canonical Brain migration/readiness state alongside existing incidents, opportunities, decisions, rule health and entity graph summaries.

This is an operator visibility feature only. It does not create recommendations, approve recommendations or grant action authority.

## Mission Control fields

`headline.canonical_readiness`
: Current canonical promotion state, such as `SHADOW_EVIDENCE_REQUIRED` or `READY_FOR_GOVERNED_DEVELOPMENT`.

`headline.canonical_shadow_samples`
: Number of distinct canonical relationship re-engagement inference subjects currently available to the readiness gate.

`headline.canonical_parity`
: Current legacy-versus-canonical parity status.

`attention.canonical_readiness_reasons`
: Explicit hold reasons when the canonical path is not ready for recommendation development.

`canonical`
: Full passive canonical operator summary, including readiness and intelligence audit information.

## Safety boundary

The following remain false on this surface:

- `automatic_acceptance`
- `automatic_execution`
- `external_action_authority`
- `canonical.recommendation_execution_enabled`
- `canonical.automatic_execution`

`READY_FOR_GOVERNED_DEVELOPMENT` means only that the evidence threshold for beginning a separately governed recommendation-development stage has been satisfied. It does not authorise runtime actions.

## Operator behaviour

When readiness is held, operators should use the reported reasons rather than infer readiness from individual opportunities. The intended progression is:

1. collect canonical shadow evidence;
2. maintain legacy/canonical parity;
3. resolve suppression or score drift;
4. satisfy the readiness policy;
5. only then begin a separately governed canonical recommendation implementation.
