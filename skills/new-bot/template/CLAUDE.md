# __NAME__

A UtilBots Discord bot built on [utilbots-core](https://github.com/UnheardOTP/utilbots-core). Read its
`STANDARD.md` before changing deployment, billing, auth or the dashboard — those live in the core, not here.

- Stack: Python 3.12, py-cord, FastAPI + Jinja, Postgres 16 (SQLAlchemy, `create_all`, no migrations yet), Stripe via core.
- This repo holds only bot-specific code: `app/plans.py` (features, limits, prices — synced to Stripe on deploy),
  `app/models.py`, `app/bot/` (cogs), `app/web/` (pages; routes here override core routes with the same path).
- Gate features with `bot.require(guild_id, "feature")` and count usage with `bot.consume(...)`; core turns
  the errors into upgrade prompts.
- Deploy = push to `main` (tests, GHCR image, home server via Tailscale). Port __PORT__, server dir
  `/mnt/user/appdata/__SLUG__`, public URL https://__SLUG__.utilbots.com.
- Secrets: never commit `.env`; never print values from the server `.env` files.
- Catalog listing on utilbots.com comes from `bot.json` (publish with the new-bot skill's catalog step).
- Tests: `pip install -r requirements.txt && python -m pytest -q` (SQLite, no Discord or Stripe needed).
