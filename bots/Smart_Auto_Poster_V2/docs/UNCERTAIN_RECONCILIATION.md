# Smart Auto Poster — UNCERTAIN Delivery Reconciliation

The reconciliation engine inspects Telegram history for queue jobs in `uncertain` state without sending or retrying anything.

## Command

```powershell
python app.py reconcile-uncertain
```

Optional JSON output:

```powershell
python app.py reconcile-uncertain --json
```

## Evidence rules

High-confidence `PROVEN_SENT` evidence is limited to:

1. Stored Telegram message IDs that still exist as outgoing messages in the destination, with compatible payload text.
2. Exactly one outgoing text message with the exact normalized caption inside the bounded send window.
3. Exactly one outgoing media album with the exact normalized caption and the expected number of media items inside the bounded send window.

Anything else remains unresolved.

Examples of unresolved classifications include multiple matching posts, media-count mismatch, unavailable account history, Telegram lookup errors, and no match.

## Critical safety rule

**No history match is not proof that a message was never delivered.**

Therefore `NO_MATCH` never authorizes an automatic retry. The engine does not:

- change queue state;
- mark a job sent;
- retry an uncertain delivery;
- send Telegram content;
- download media;
- modify Telegram history.

It only produces evidence and a classification.

## Default history window

The default evidence window is:

- 120 seconds before the recorded delivery-attempt start;
- 900 seconds after the recorded delivery-attempt start;
- maximum 300 inspected history messages per evidence account.

These bounds can be changed from the CLI for investigation.

## Operational purpose

This engine is the evidence layer required before any future automated resolution mechanism. A later resolver may consume only `safe_to_mark_sent=true` results; retry authority remains separate and fail-closed.
