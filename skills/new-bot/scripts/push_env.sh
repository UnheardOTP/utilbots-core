#!/usr/bin/env bash
# Merge KEY=VALUE lines from a local file into a .env on the home server, without printing any values.
#   push_env.sh mediabot ~/.config/utilbots/mediabot.env      -> /mnt/user/appdata/mediabot/.env
#   push_env.sh --shared ~/.config/utilbots/shared.env        -> /mnt/user/appdata/utilbots-shared/.env
# Existing keys are replaced, other keys are kept. Then restarts the bot's containers if they exist.
set -euo pipefail
HOST="${UTILBOTS_HOST:-root@bamphbox.tail5ecf41.ts.net}"
APPDATA="${UTILBOTS_APPDATA:-/mnt/user/appdata}"
if [ "${1:-}" = "--shared" ]; then TARGET="$APPDATA/utilbots-shared"; SLUG=""; else SLUG="$1"; TARGET="$APPDATA/$SLUG"; fi
SRC="${2:?usage: push_env.sh <slug>|--shared <file>}"
[ -f "$SRC" ] || { echo "no such file: $SRC" >&2; exit 1; }
keys=$(grep -E '^[A-Z][A-Z0-9_]*=' "$SRC" | cut -d= -f1 | tr '\n' ' ')
[ -n "$keys" ] || { echo "no KEY=VALUE lines in $SRC" >&2; exit 1; }

ssh "$HOST" "umask 077; mkdir -p '$TARGET' && cat > '$TARGET/.env.incoming'" < <(grep -E '^[A-Z][A-Z0-9_]*=' "$SRC")
ssh "$HOST" "TARGET='$TARGET' SLUG='$SLUG' bash -s" <<'EOS'
set -euo pipefail
umask 077
f="$TARGET/.env"; touch "$f"
while IFS= read -r line; do
  k="${line%%=*}"
  grep -v "^$k=" "$f" > "$f.tmp" || true
  printf '%s\n' "$line" >> "$f.tmp"
  mv "$f.tmp" "$f"
done < "$TARGET/.env.incoming"
rm -f "$TARGET/.env.incoming"
chmod 600 "$f"
if [ -n "$SLUG" ] && [ -f "$TARGET/docker-compose.prod.yml" ] && docker ps -q --filter "label=com.docker.compose.project=$SLUG" | grep -q .; then
  cd "$TARGET" && docker compose -p "$SLUG" -f docker-compose.prod.yml up -d >/dev/null && echo "restarted $SLUG"
fi
EOS
echo "updated $TARGET/.env keys: $keys"
