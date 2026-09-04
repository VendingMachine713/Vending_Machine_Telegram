# Smart Auto Poster V4.0 Release Checklist

- [ ] Compile Python source/tests.
- [ ] Run entire unittest suite.
- [ ] Validate database/configuration.
- [ ] Run SQLite integrity and foreign-key checks.
- [ ] Simulate v3.5.2 -> v4.0.0 direct-drop update.
- [ ] Verify existing queue rows and canary IDs are preserved.
- [ ] Verify no package script contains `post-now` or generic uncertain retry.
- [ ] Verify Mission Control anti-spam check reports zero unresolved duplicate groups before production activation.
- [ ] Verify Telegram sessions on the Windows host without sending.
- [ ] Verify managed service/scheduler/worker/Admin Bot heartbeats on the Windows host.
- [ ] Finish existing canary and visual receipt gate before main production activation.
