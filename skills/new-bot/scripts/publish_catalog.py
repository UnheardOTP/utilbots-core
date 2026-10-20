#!/usr/bin/env python3
"""Publish a bot's bot.json to the utilbots.com catalog (PUT /api/admin/bots/<slug>, idempotent).

    publish_catalog.py path/to/bot.json [--client-id 123] [--live]

Token: UTILBOTS_TOKEN env var, or UTILBOTS_TOKEN=... in ~/.config/utilbots/catalog.env (never printed).
--client-id fills invite_url; --live sets status=live (default keeps bot.json's status, normally hidden)."""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlencode

API = os.getenv("UTILBOTS_API", "https://utilbots.com")
PERMS = 1024 + 2048 + 16384 + 32768 + 65536


def token() -> str:
    if os.getenv("UTILBOTS_TOKEN"):
        return os.environ["UTILBOTS_TOKEN"]
    f = Path.home() / ".config/utilbots/catalog.env"
    if f.exists():
        for line in f.read_text().splitlines():
            if line.startswith("UTILBOTS_TOKEN="):
                return line.split("=", 1)[1].strip()
    sys.exit("UTILBOTS_TOKEN not set (env or ~/.config/utilbots/catalog.env)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("bot_json", type=Path)
    ap.add_argument("--client-id")
    ap.add_argument("--permissions", type=int, default=PERMS)
    ap.add_argument("--live", action="store_true")
    a = ap.parse_args()
    data = json.loads(a.bot_json.read_text())
    slug = data.pop("slug")
    if a.client_id:
        data["invite_url"] = "https://discord.com/oauth2/authorize?" + urlencode(
            {"client_id": a.client_id, "scope": "bot applications.commands", "permissions": a.permissions})
    if a.live:
        data["status"] = "live"
    data = {k: v for k, v in data.items() if v is not None}
    req = urllib.request.Request(f"{API}/api/admin/bots/{slug}", method="PUT", data=json.dumps(data).encode(),
                                 headers={"Authorization": f"Bearer {token()}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            bot = json.load(r)["bot"]
            print(f"{'created' if r.status == 201 else 'updated'} {slug}: status={bot['status']} {API}")
    except urllib.error.HTTPError as e:
        sys.exit(f"catalog API {e.code}: {e.read().decode()[:500]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
