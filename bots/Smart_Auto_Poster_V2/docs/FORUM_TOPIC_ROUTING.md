# Forum Topic Routing

Smart Auto Poster discovers forum topics passively during the normal `scan`
operation. Discovery reads Telegram metadata only; it does not enqueue content,
activate a campaign, or send a message.

Topic visibility is recorded separately for the primary and secondary accounts.
An existing usable route is preserved. A route is selected automatically only
when exactly one usable topic exists or one exact, preferred title is the unique
best match. Ambiguous forums are cleared to `topic_id=NULL` and remain marked for
operator review.

Preferred exact titles, in order, include `General`, `Advertising`,
`Marketplace`, `Buy & Sell`, `Promotions`, and `Main`. Equivalent top-scoring
matches remain ambiguous rather than being guessed.

Before any canary, run:

```powershell
py .\app.py scan
py .\app.py topic-route-preview --only-attention
```

The preview is database-only and always reports:

- `read_only: true`
- `telegram_mutations: false`
- `automatic_send: false`

Do not start a live canary until every intended forum route is `READY`, the
selected account coverage is correct, the queue has no in-flight jobs, and the
normal production safety gate passes.
