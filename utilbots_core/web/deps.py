"""Request helpers bots use in their own routes: `from utilbots_core.web.deps import *`."""
import secrets
from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from jinja2 import ChoiceLoader, FileSystemLoader, PrefixLoader
from sqlalchemy.orm import Session

from .. import entitlements, registry
from ..config import settings
from ..db import SessionLocal
from ..models import AuditLog, Guild, WebSession

__all__ = ["get_db", "get_session", "require_user", "require_admin", "is_admin", "check_csrf", "render", "back",
           "audit", "managed_guild", "guild_ctx", "templates", "LoginRequired", "SESSION_COOKIE", "STATE_COOKIE"]

CORE_TEMPLATES = Path(__file__).parent / "templates"
SESSION_COOKIE = "ub_session"
STATE_COOKIE = "ub_state"

templates = Jinja2Templates(directory=CORE_TEMPLATES)


def use_templates(bot_dir: Path | None) -> None:
    """Bot templates override core templates of the same name; `{% extends "core/base.html" %}` reaches the
    original when a bot overrides a page but wants to keep its layout."""
    loaders = [FileSystemLoader(str(bot_dir))] if bot_dir and bot_dir.is_dir() else []
    loaders += [FileSystemLoader(str(CORE_TEMPLATES)),
                PrefixLoader({"core": FileSystemLoader(str(CORE_TEMPLATES))})]
    templates.env.loader = ChoiceLoader(loaders)
    spec, plans = registry.current()
    templates.env.globals.update(settings=settings, spec=spec, PLANS=plans.ordered(), PAID=plans.paid,
                                 FEATURES=plans.features)


def _guild_icon(g) -> str:
    gid, icon = (g["id"], g["icon"]) if isinstance(g, dict) else (g.id, g.icon)
    return f"https://cdn.discordapp.com/icons/{gid}/{icon}.png?size=64" if icon else ""


templates.env.filters["guild_icon"] = _guild_icon


def get_db():
    with SessionLocal() as s:
        yield s


class LoginRequired(Exception):
    pass


def get_session(request: Request, db: Session = Depends(get_db)) -> WebSession | None:
    token = request.cookies.get(SESSION_COOKIE)
    ws = db.get(WebSession, token) if token else None
    if ws and ws.expired:
        db.delete(ws)
        db.commit()
        return None
    return ws


def require_user(ws: WebSession | None = Depends(get_session)) -> WebSession:
    if ws is None:
        raise LoginRequired()
    return ws


def require_admin(ws: WebSession = Depends(require_user)) -> WebSession:
    if ws.user_id not in settings.admin_ids:
        raise HTTPException(403, "Site admins only")
    return ws


def is_admin(ws: WebSession | None) -> bool:
    return bool(ws and ws.user_id in settings.admin_ids)


def check_csrf(ws: WebSession, token: str) -> None:
    if not secrets.compare_digest(ws.csrf, token):
        raise HTTPException(403, "Bad CSRF token")


def render(request: Request, name: str, ws: WebSession | None, **ctx):
    return templates.TemplateResponse(request, name, {
        "ws": ws, "is_admin": is_admin(ws), "msg": request.query_params.get("msg"),
        "err": request.query_params.get("err"), **ctx})


def back(url: str, msg: str | None = None, err: str | None = None) -> RedirectResponse:
    q = f"?msg={quote(msg)}" if msg else f"?err={quote(err)}" if err else ""
    return RedirectResponse(url + q, status_code=303)


def audit(db: Session, actor: int | None, action: str, target: str = "", detail: str = "") -> None:
    db.add(AuditLog(actor_id=actor, action=action, target=target, detail=detail[:500]))


def managed_guild(ws: WebSession, guild_id: int) -> dict:
    """Guild summary from the user's Discord session if they may manage it (site admins may manage any)."""
    for g in ws.guilds:
        if int(g["id"]) == guild_id:
            return g
    if is_admin(ws):
        return {"id": str(guild_id), "name": "", "icon": None, "owner": False}
    raise HTTPException(403, "You can't manage that server")


async def guild_ctx(db: Session, ws: WebSession, guild_id: int) -> Guild:
    """The installed guild the current user may manage, or 403/404."""
    summary = managed_guild(ws, guild_id)
    guild = db.get(Guild, guild_id)
    if guild is None or not guild.installed:
        raise HTTPException(404, "The bot isn't in that server yet.")
    if not guild.name and summary["name"]:
        guild.name = summary["name"]
    return guild


def plan_for(db: Session, guild_id: int):
    return entitlements.effective_plan(db, guild_id)
