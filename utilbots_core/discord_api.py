"""Discord REST helpers for the website (OAuth login, invite links, reading channels/roles with the bot token)."""
import secrets
from urllib.parse import urlencode

import httpx

from . import registry
from .config import settings

API = "https://discord.com/api/v10"
MANAGE_GUILD = 0x20
ADMINISTRATOR = 0x8


def login_url(state: str) -> str:
    return "https://discord.com/oauth2/authorize?" + urlencode({
        "client_id": settings.discord_client_id, "response_type": "code", "scope": "identify guilds",
        "redirect_uri": f"{settings.public_url}/auth/callback", "state": state, "prompt": "none"})


def invite_url(guild_id: int | None = None) -> str:
    params = {"client_id": settings.discord_client_id, "scope": "bot applications.commands",
              "permissions": registry.spec().bot_permissions}
    if guild_id:
        params.update(guild_id=guild_id, disable_guild_select="true")
    return "https://discord.com/oauth2/authorize?" + urlencode(params)


def new_token() -> str:
    return secrets.token_urlsafe(32)


async def exchange_code(code: str) -> str:
    async with httpx.AsyncClient(timeout=15) as http:
        r = await http.post(f"{API}/oauth2/token", data={
            "client_id": settings.discord_client_id, "client_secret": settings.discord_client_secret,
            "grant_type": "authorization_code", "code": code,
            "redirect_uri": f"{settings.public_url}/auth/callback"})
        r.raise_for_status()
        return r.json()["access_token"]


async def fetch_identity(access_token: str) -> tuple[dict, list[dict]]:
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=15, headers=headers) as http:
        me = (await http.get(f"{API}/users/@me")).raise_for_status().json()
        guilds = (await http.get(f"{API}/users/@me/guilds")).raise_for_status().json()
    managed = [{"id": g["id"], "name": g["name"], "icon": g.get("icon"), "owner": g.get("owner", False)}
               for g in guilds
               if g.get("owner") or int(g.get("permissions", 0)) & (MANAGE_GUILD | ADMINISTRATOR)]
    return me, managed


async def bot_get(path: str):
    """GET using the bot token. Returns None if the bot cannot access the resource."""
    if not settings.discord_token:
        return None
    async with httpx.AsyncClient(timeout=15, headers={"Authorization": f"Bot {settings.discord_token}"}) as http:
        r = await http.get(f"{API}{path}")
        return r.json() if r.status_code == 200 else None


async def guild_channels_and_roles(guild_id: int) -> tuple[list[dict], list[dict]]:
    channels = await bot_get(f"/guilds/{guild_id}/channels") or []
    roles = await bot_get(f"/guilds/{guild_id}/roles") or []
    text = sorted((c for c in channels if c["type"] in (0, 5)), key=lambda c: c.get("position", 0))
    roles = sorted((r for r in roles if r["name"] != "@everyone" and not r.get("managed")),
                   key=lambda r: -r["position"])
    return text, roles
