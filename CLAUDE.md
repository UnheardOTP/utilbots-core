# utilbots-core

Shared package + pipeline for every UtilBots bot. Read STANDARD.md first.

- Changes here affect every bot once it bumps its pin. Keep the public surface stable: `configure`, `BotSpec`,
  `Plan`/`PlanSet`, `UtilBot` (`require`, `consume`, `plan_for`), `create_app`, `web.deps` helpers, template names.
- Releasing: bump `pyproject.toml` version and `utilbots_core.__version__`, tag `vX.Y.Z`, move `v0`
  (`git tag -f v0 && git push -f origin v0`). Breaking workflow changes need a new major tag (`v1`).
- Stripe code must stay bot-scoped (metadata `bot`, lookup keys `<slug>_...`, per-bot portal config).
- Tests: `pip install -e '.[test]' && python -m pytest -q`; CI also scaffolds a bot from the template and runs its tests.
- The `new-bot` skill must never print secrets; secret files are moved by `push_env.sh` / `set_github_secrets.sh`.
