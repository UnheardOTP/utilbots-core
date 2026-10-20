#!/usr/bin/env bash
# Copy the deploy secrets every bot repo needs from ~/.config/utilbots/github-secrets.env into a repo,
# without printing them. The file holds TS_OAUTH_CLIENT_ID, TS_OAUTH_SECRET, DEPLOY_SSH_PASSWORD.
#   set_github_secrets.sh UnheardOTP/mediabot.utilbots.com
set -euo pipefail
REPO="${1:?usage: set_github_secrets.sh <owner/repo>}"
SRC="${UTILBOTS_GH_SECRETS:-$HOME/.config/utilbots/github-secrets.env}"
[ -f "$SRC" ] || { echo "missing $SRC (see STANDARD.md, one-time setup)" >&2; exit 1; }
for key in TS_OAUTH_CLIENT_ID TS_OAUTH_SECRET DEPLOY_SSH_PASSWORD; do
  value=$(grep -E "^$key=" "$SRC" | head -1 | cut -d= -f2-)
  [ -n "$value" ] || { echo "$key is empty in $SRC" >&2; exit 1; }
  printf '%s' "$value" | gh secret set "$key" --repo "$REPO" >/dev/null
  echo "set $key"
done
