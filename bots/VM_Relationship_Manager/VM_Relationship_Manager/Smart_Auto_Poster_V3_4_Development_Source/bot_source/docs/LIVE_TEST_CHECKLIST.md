# Permanent LIVE_TEST Deployment Gate

Use the existing safe test destination for every release.

1. Full self-tests pass.
2. `py .\app.py integrity` returns `ok`.
3. `py .\app.py health` has no unexpected readiness errors.
4. `py .\app.py accounts-check` shows distinct Primary and Secondary user IDs.
5. `py .\app.py scan` completes and new groups remain REVIEW + disabled.
6. Preview the LIVE_TEST campaign.
7. Dry-run shows exactly the intended test destination(s).
8. Queue one test job only.
9. Run `py .\app.py worker --once`.
10. Confirm queue status is `sent` and the Telegram test message is visible.
11. Only then start unattended production.

If a send is interrupted while in flight, V2.4 marks it `uncertain`; do not blindly retry without checking Telegram first.
