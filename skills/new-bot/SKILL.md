---
name: new-bot
description: Create and ship a new UtilBots Discord bot (<servicetype>bot at <servicetype>bot.utilbots.com) end to end - scaffold the repo from utilbots-core, set GitHub secrets, load the Discord app into the server .env, add DNS and the proxy host, deploy, and list it on utilbots.com. Use when the user wants to start, set up, deploy or launch a new bot, or migrate an existing bot onto the standard.
---

# New UtilBots bot

Everything a bot needs is automated except creating the Discord application. Read `STANDARD.md` in the
utilbots-core checkout (this skill lives at `<core>/skills/new-bot`) if anything below is unclear.
Paths below: `CORE` = the utilbots-core checkout (resolve this skill's real path, three levels up),
`SCRIPTS` = `CORE/skills/new-bot/scripts`.

## Golden rules
- Never ask the user to paste tokens, passwords or keys into chat, never `cat`/print `.env` or
  `~/.config/utilbots/*` files, and never echo secret values in commands. The scripts move secrets without printing them.
- Bot slug = `<servicetype>bot`, lowercase. Repo `UnheardOTP/<slug>.utilbots.com`. Site `https://<slug>.utilbots.com`.
- Ask before anything user-visible or hard to undo: the DNS/proxy apply, flipping `DEPLOY_ENABLED`, publishing `--live`.

## 0. One-time setup (check, don't redo)
Confirm these exist; if one is missing, tell the user exactly what to create and wait:
- `~/.config/utilbots/github-secrets.env` with `TS_OAUTH_CLIENT_ID`, `TS_OAUTH_SECRET`, `DEPLOY_SSH_PASSWORD`
  (the same values the existing bot repos use).
- `~/.config/utilbots/catalog.env` with `UTILBOTS_TOKEN=` (the utilbots.com `ADMIN_TOKEN`).
- `~/.config/devdomains.env` for the `deploy-dev-domain` skill.
- `gh auth status` works, and `ssh root@bamphbox.tail5ecf41.ts.net true` works (tailnet up).
- The server's shared env has `STRIPE_SECRET_KEY` and `ADMIN_IDS`: run
  `ssh root@bamphbox.tail5ecf41.ts.net "grep -c -E '^(STRIPE_SECRET_KEY|ADMIN_IDS)=.' /mnt/user/appdata/utilbots-shared/.env"`
  (prints a count, not values; expect 2). If not, have the user put them in `~/.config/utilbots/shared.env` and run
  `SCRIPTS/push_env.sh --shared ~/.config/utilbots/shared.env`.

## 1. Define the bot
Agree with the user on: slug, display name, emoji, one-line tagline, a ≤700-char description, the slash commands,
and what Free/Plus/Pro get (features, daily limits, monthly price). Default prices: Plus $3, Pro $6.

## 2. Repo + scaffold
```bash
gh repo view UnheardOTP/<slug>.utilbots.com >/dev/null 2>&1 || gh repo create UnheardOTP/<slug>.utilbots.com --private
gh repo clone UnheardOTP/<slug>.utilbots.com <dir>   # skip if already cloned
python3 SCRIPTS/scaffold.py --slug <slug> --name <Name> --emoji <e> --tagline "<tagline>" --out <dir>
```
The scaffold prints the assigned port and records it in `CORE/bots.json` (commit and push that in CORE).
Then build the bot inside `<dir>`: `app/plans.py`, `app/models.py`, cogs in `app/bot/`, pages in `app/web/`,
`bot.json` (description, features ≤8 short strings), README/CLAUDE.md, tests. Keep the core boundary: don't copy core
code into the bot; if the bot needs something every bot would want, add it to utilbots-core instead (bump its version,
tag `vX.Y.Z`, move tag `v0`, and update the bot's `requirements.txt` pin).
Run `pip install -r requirements.txt && python -m pytest -q` until green. Commit and push to `main`
(deploys stay off until step 6, so pushing is safe).

## 3. GitHub secrets
`SCRIPTS/set_github_secrets.sh UnheardOTP/<slug>.utilbots.com`

## 4. Discord application (the one manual step)
Give the user this checklist:
1. https://discord.com/developers/applications → New Application → `<Name>`; set the icon and description.
2. Bot tab → Reset Token → copy it. Turn on any privileged intents the bot needs (say which, if any).
3. OAuth2 → add redirect `https://<slug>.utilbots.com/auth/callback`; copy Client ID and Client Secret.
4. Installation → Install link: None (the site builds the invite link).
5. Save into `~/.config/utilbots/<slug>.env`:
   `DISCORD_TOKEN=…`, `DISCORD_CLIENT_ID=…`, `DISCORD_CLIENT_SECRET=…` (plus any bot-specific keys).
When they confirm, run `SCRIPTS/push_env.sh <slug> ~/.config/utilbots/<slug>.env`.
Bot-specific secrets that every bot could share (e.g. file-host API keys) go to the shared env instead.

## 5. Domain + proxy
Use the `deploy-dev-domain` skill with `--name <slug> --domain utilbots.com --port <port>`: dry run, show the user,
then `--apply` after they agree. The utilbots.com wildcard cert is reused if it exists. `PUBLIC_URL` is already
`https://<slug>.utilbots.com` (set by the first deploy).

## 6. Deploy
```bash
gh variable set DEPLOY_ENABLED --body true --repo UnheardOTP/<slug>.utilbots.com
gh workflow run deploy.yml --repo UnheardOTP/<slug>.utilbots.com --ref main
gh run watch --repo UnheardOTP/<slug>.utilbots.com --exit-status $(gh run list --repo UnheardOTP/<slug>.utilbots.com -L1 --json databaseId -q '.[0].databaseId')
```
If it fails, read `gh run view --log-failed` and fix. Then check `https://<slug>.utilbots.com/healthz`.
Stripe needs nothing: on startup the site creates this bot's products/prices (lookup keys `<slug>_<plan>_monthly`),
its own webhook endpoint and customer-portal configuration. Confirm with
`ssh root@bamphbox.tail5ecf41.ts.net "docker logs <slug>-web-1 2>&1 | grep stripe:"`.

## 7. Catalog
`python3 SCRIPTS/publish_catalog.py <dir>/bot.json --client-id <client id>` (client ID is not secret; ask the user
for it or read it with `grep -o '^DISCORD_CLIENT_ID=.*' ~/.config/utilbots/<slug>.env`). It's published hidden;
when the user says the bot is ready, rerun with `--live`.

## 8. Wrap up
Tell the user: the live URL, the invite link, the admin page (`/admin`, for user IDs in `ADMIN_IDS`), and anything
left for them (Discord app icon, going `--live`, bot verification once it nears 100 servers).
