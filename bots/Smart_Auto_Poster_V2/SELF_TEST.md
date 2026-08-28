# Smart Auto Poster V3.0.4 Self-Test

Expected full suite: **123 tests**.

Validated areas include the V3.0 platform, Windows runtime-lock repair, updater repair, project-local `.env` precedence, operator-friendly invalid Admin Bot token handling, and the Windows-stable spread-window determinism test.

Run:

```powershell
py -m unittest discover -s tests -q
py .\app.py validate
py .\app.py integrity
```
