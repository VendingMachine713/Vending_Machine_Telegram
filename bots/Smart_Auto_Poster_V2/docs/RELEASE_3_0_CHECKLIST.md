# Smart Auto Poster V3.0 release checklist

Automated release gate:

1. Compile all Python files.
2. Run the full regression suite.
3. Reconstruct/upgrade a historical V2.2.3 database to schema v6.
4. Verify legacy campaign + sent queue history preservation.
5. Run local pre-flight validation.
6. Run SQLite integrity check.
7. Validate update manifest payload membership + SHA-256 hashes.
8. Scan release package for `.env`, `.session`, database/user-content and known secret patterns.
9. Apply the **exact final ZIP** to a clean legacy baseline and repeat tests/integrity.
10. On the user's PC: Health â†’ Validate â†’ Account identities.
11. `LIVE_TEST` dry run must select exactly the intended canary destination.
12. Send one controlled queue job; verify `sent` history.
13. If using Telegram Admin Control Centre, verify one private authorized-admin interaction and one unauthorized/read-only denial path.
14. Resume unattended production only after the canary succeeds.
