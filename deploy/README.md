# Optional Deployment Scaffolding

These files are optional and are not used by the Windows installer.

- Docker/Compose can run the VM supervisor in a repeatable environment.
- Railway scaffolding is included for later VPS/cloud migration.
- Telegram `.session` files and `.env` secrets must never be baked into an image.
- Persist required runtime/session data with secure volumes/secrets when moving off the Windows PC.
- Keep native Windows operation as the current default until each bot has a confirmed deployment adapter.
