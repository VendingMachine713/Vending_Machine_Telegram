# V5.0.0 release verification

Run `py -m compileall -q smart_autoposter tests`, `py -m unittest discover -s tests -q`, `py app.py validate`, `py app.py integrity`, `py app.py queue-hygiene`, and `py app.py v5-readiness --json-only`. V5 readiness is expected to remain blocked on a live database containing unresolved UNCERTAIN evidence.

# Smart Auto Poster V4.0.1 self-test

Run:

```powershell
py -m compileall -q smart_autoposter tests
py -m unittest discover -s tests -q
py app.py validate
py app.py integrity
py app.py mission-control --campaign main_production_01
py app.py progress --campaign main_production_01 --limit 40
```

Expected automated regression count: 215 tests.


## V6.0.0
Run `py -m unittest discover -s tests -q`, `py app.py validate`, `py app.py integrity`, and `py app.py v6-control --json-only`. Production activation is not part of self-test.

### V6.0.1 live coverage checks
- `py -m unittest tests.test_v601_live_coverage -v`
- Full suite expected: 269 tests.
- `py app.py live-coverage-status --export` is read-only except for report-file creation.
