# The UtilBots standard

How every UtilBots bot is built, deployed and billed. Bots are named `<servicetype>bot`, live in
`UnheardOTP/<servicetype>bot.utilbots.com`, and are served at `https://<servicetype>bot.utilbots.com`.
To create one, use the `new-bot` skill (`skills/new-bot`); it automates everything below.

## What lives where

| | Holds |
|---|---|
| **utilbots-core** (this repo, public) | `utilbots_core` Python package: Discord login, server dashboard, plans/entitlements, daily quotas, Stripe billing, admin panel, audit log, `/plan`, bot base class. The reusable deploy workflow. The `new-bot` skill and bot template. `bots.json` port registry. |
| **Each bot repo** (private) | Only bot-specific code: `app/plans.py`, `app/models.py`, cogs, pages, `bot.json` catalog entry, a 20-line `deploy.yml` that calls the core workflow. |
| **utilbots.com** | The catalog site (Node). Bots are listed through its admin API (`publish_catalog.py`). |
| **Home server** | `/mnt/user/appdata/utilbots-shared/.env` (shared tokens) and `/mnt/user/appdata/<slug>/` per bot. |

## Stack
Python 3.12 · py-cord · FastAPI + Jinja · Postgres 16 per bot (SQLAlchemy `create_all`; `utilbots_core.db.add_columns`
for additive changes) · Stripe · one Docker image per bot running two services (`web`, `bot`) plus `db`.

Bots pin the core in `requirements.txt` (`utilbots-core @ git+https://github.com/UnheardOTP/utilbots-core@v0.1.0`).
Releasing the core: bump `version` in `pyproject.toml`, tag `vX.Y.Z`, move the `v0` tag (the workflow ref bots use),
then bump each bot's pin when you want it to pick the change up. A bot never breaks because the core moved.

## Deploy pipeline
Push to `main` → `.github/workflows/deploy-bot.yml` in this repo:
1. **test** — `pytest` (also on pull requests).
2. **build** — image `ghcr.io/unheardotp/<slug>:<sha>` and `:latest`.
3. **deploy** (environment `production`) — joins the tailnet as `tag:ci`, SSHes to `bamphbox.tail5ecf41.ts.net`,
   creates the deploy dir, generates `POSTGRES_PASSWORD`, `SESSION_SECRET`, `PUBLIC_URL`, `WEB_PORT` in the bot's
   `.env` on first run, refuses to continue without the Discord values, copies `docker-compose.prod.yml`, pulls the
   exact `<sha>` image, `compose up -d` as project `<slug>`, and waits for `/healthz` to report the right bot.

Deploys only run when the repo variable `DEPLOY_ENABLED=true` (set by the skill once the bot is provisioned).
Rollback: re-run an older successful workflow run (it redeploys that commit's image).
Repo secrets (same in every bot): `TS_OAUTH_CLIENT_ID`, `TS_OAUTH_SECRET`, `DEPLOY_SSH_PASSWORD`.

## Ports
`bots.json` is the registry. Catalog 3470, StormBot 8080 (legacy), new bots from 3500 up. Nginx Proxy Manager
forwards `<slug>.utilbots.com` → `192.168.0.69:<port>` (via the `deploy-dev-domain` skill, wildcard cert for
`*.utilbots.com`).

## Secrets
- **Shared** — `/mnt/user/appdata/utilbots-shared/.env`, loaded into every bot before its own `.env`:
  `STRIPE_SECRET_KEY`, `ADMIN_IDS`, and API keys several bots use (e.g. `GOFILE_TOKEN`, `PIXELDRAIN_API_KEY`).
  Change it with `skills/new-bot/scripts/push_env.sh --shared <file>`; restart bots to pick it up.
- **Per bot** — `/mnt/user/appdata/<slug>/.env`: Discord app values plus generated ones. `push_env.sh <slug> <file>`.
- **Local** (your machine, never committed): `~/.config/utilbots/github-secrets.env`, `catalog.env`, `<slug>.env`,
  `shared.env`; `~/.config/devdomains.env` for DNS/NPM.
A bot's own `.env` overrides the shared file, so one bot can use a different value when it must.

## Billing (Stripe)
One Stripe account, configured entirely by the core:
- **Prices** come from `app/plans.py` (`price_cents`). On web startup each paid plan gets a monthly Price with lookup
  key `<slug>_<plan>_monthly`. Changing a price creates a new Price and moves the key; existing subscribers keep
  their old price until they change plan.
- **Webhook**: each bot creates its own endpoint `https://<slug>.utilbots.com/stripe/webhook` and stores its signing
  secret in its database. Stripe sends every account event to every endpoint, so each bot only acts on
  subscriptions whose metadata `bot` is its slug.
- **Customer portal**: each bot gets its own portal configuration, so "change plan" only offers that bot's plans.
- Plans are per Discord server; checkout is per server; one trial per server (`TRIAL_DAYS`, default 14).
- Test mode vs live mode is just which `STRIPE_SECRET_KEY` is in the shared env. Switching modes creates the
  catalog again in the new mode automatically.
Without a Stripe key the site still works with admin grants and trials.

## Building a bot
- Gate features with `bot.require(guild_id, "feature", session)`; meter with
  `bot.consume(session, guild_id, "key", amount, plan.limit("key_per_day"), "what")`. Core turns the resulting
  errors into ephemeral upgrade prompts with the billing link.
- Bot-specific settings go in the bot's own tables keyed by `guild_id` (FK to `guilds.id`, cascade delete).
- Website: `create_app(routers=[...], templates_dir=...)`. Bot routes win over core routes with the same path;
  bot templates override core templates by name (`{% extends "core/base.html" %}` reaches the original).
- `GET /healthz` must keep returning `{"ok": true, "bot": "<slug>"}` (the deploy checks it).

## One-time setup (already done for StormBot / utilbots.com)
- Tailscale: OAuth client with `auth_keys` scope and tag `tag:ci`; ACL lets `tag:ci` reach the server on port 22.
- Unraid: Compose Manager Plus plugin (or the pipeline downloads a pinned compose binary).
- Stripe: business details and public branding set in the dashboard.

## Hardening backlog
- Deploys log in as `root` with a password over the tailnet; switch to an SSH key and a non-root user in the
  `docker` group, then change `SSH`/`SCP` in the workflow.
- Add Alembic once a bot needs a non-additive schema change.
