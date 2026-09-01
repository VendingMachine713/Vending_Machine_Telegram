# VM Development Workflow

1. Make changes inside the permanent bot folder.
2. Prefer shared VM Core for genuinely cross-bot infrastructure.
3. Run `py vm.py check`.
4. Run bot-specific tests.
5. Record a release baseline with `py vm.py release-baseline <bot>`.
6. Continue development.
7. Build changed/new files with `py vm.py release <bot>`.
8. Never include `.env`, Telegram sessions, or live databases in release packages.
9. Every significant bug should gain a regression test.
10. Destructive operations default to preview/dry-run.
