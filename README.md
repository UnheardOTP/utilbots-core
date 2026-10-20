# utilbots-core

Shared foundation for [UtilBots](https://utilbots.com) Discord bots: the `utilbots_core` Python package
(Discord login, dashboard, plans, Stripe, admin, bot base class), the reusable deploy workflow, and the `new-bot`
skill that scaffolds and ships a bot end to end.

- **[STANDARD.md](STANDARD.md)** — how bots are built, deployed, billed and configured.
- **[skills/new-bot](skills/new-bot/SKILL.md)** — install for Claude Code with
  `ln -s "$PWD/skills/new-bot" ~/.claude/skills/new-bot`, then ask Claude to "make a new bot".
- **[bots.json](bots.json)** — slug and port registry.

```bash
pip install -e '.[test]' && python -m pytest -q
```
