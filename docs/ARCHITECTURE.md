# VM Platform v1.0 Architecture

The platform keeps each bot independently runnable while providing shared infrastructure.

Telegram
  -> independent bot services
  -> shared VM Core
     - manifests/inventory
     - lifecycle
     - health
     - diagnostics
     - platform DB
     - accounts/destinations registry
     - jobs/events
     - backup/rollback
     - logging
     - support bundles
     - release tooling

The platform does not force bot rewrites. Existing bot internals can migrate toward VM Core incrementally.
